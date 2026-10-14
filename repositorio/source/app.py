"""Flask application factory and API endpoints for Hoshu Cockpit."""

from __future__ import annotations

import datetime
import os
import platform
import sys
from pathlib import Path
from typing import Any

# Ensure repository root is on sys.path when executed directly as a script
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from flask import Flask, Response, jsonify, render_template, request

from source.backup_manager import BackupManager
from source.log_streamer import LogStreamManager
from source.privileges import (
    AdministrativePrivilegesRequiredError,
    PrivilegeChecker,
)
from source.service_adapter import (
    ServiceManagerError,
    ServiceNotFoundError,
    WindowsServiceAdapter,
)
from source.services_config import ServiceConfig, ServicesConfigLoader


def create_app(
    config_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    adapter: WindowsServiceAdapter | None = None,
    privilege_checker: PrivilegeChecker | None = None,
    log_streamer: LogStreamManager | None = None,
    template_folder: str | Path | None = None,
) -> Flask:
    """Application factory for Hoshu Cockpit.

    Args:
        config_path: Path to services.json.
        backup_dir: Directory for storing/listing backups.
        adapter: Custom WindowsServiceAdapter instance (e.g. for testing).
        privilege_checker: Custom PrivilegeChecker instance.
        log_streamer: Custom LogStreamManager instance.
        template_folder: Path to directory containing Jinja templates.

    Returns:
        Configured Flask instance.
    """
    repo_root = Path(__file__).resolve().parent.parent

    if template_folder is None:
        template_path = repo_root / "template"
    else:
        template_path = Path(template_folder)

    app = Flask(__name__, template_folder=str(template_path))
    app.config["JSON_SORT_KEYS"] = False

    # Initialize components
    actual_config_path = (
        Path(config_path) if config_path else repo_root / "config" / "services.json"
    )
    actual_backup_dir = (
        Path(backup_dir) if backup_dir else repo_root / "backups"
    )

    loader = ServicesConfigLoader()
    if actual_config_path.exists():
        loader.load_from_file(actual_config_path)

    checker = privilege_checker or PrivilegeChecker()
    service_adapter = adapter or WindowsServiceAdapter(privilege_checker=checker)
    backup_mgr = BackupManager(backup_dir=actual_backup_dir)
    streamer = log_streamer or LogStreamManager()

    # Initial system log
    streamer.broadcast(
        f"Hoshu inicializado no host '{platform.node()}'. Privilégio: {'Admin' if checker.is_admin() else 'Usuário Padrão'}.",
        level="INFO",
        channel="system",
    )

    app.extensions["loader"] = loader
    app.extensions["service_adapter"] = service_adapter
    app.extensions["privilege_checker"] = checker
    app.extensions["backup_manager"] = backup_mgr
    app.extensions["log_streamer"] = streamer

    def _common_context() -> dict[str, Any]:
        now = datetime.datetime.now()
        return {
            "host_name": platform.node() or "localhost",
            "is_admin": checker.is_admin(),
            "server_time": now.strftime("%H:%M:%S"),
        }

    @app.route("/")
    def index() -> str:
        services = loader.get_services(order_ascending=True)
        backups = [
            {
                "name": p.name,
                "size": p.stat().st_size,
                "mtime": datetime.datetime.fromtimestamp(
                    p.stat().st_mtime, tz=datetime.timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
            for p in backup_mgr.list_backups()
        ]
        return render_template(
            "index.html",
            active_page="cockpit",
            services=services,
            backups=backups,
            **_common_context(),
        )

    @app.route("/services")
    def services_view() -> str:
        services = loader.get_services(order_ascending=True)
        return render_template(
            "services.html",
            active_page="services",
            services=services,
            **_common_context(),
        )

    @app.route("/patch")
    def patch_view() -> str:
        return render_template(
            "patch.html",
            active_page="patch",
            **_common_context(),
        )

    @app.route("/devops")
    def devops_view() -> str:
        return render_template(
            "devops.html",
            active_page="devops",
            **_common_context(),
        )

    @app.route("/backups")
    def backups_view() -> str:
        backups = [
            {
                "name": p.name,
                "size": p.stat().st_size,
                "mtime": datetime.datetime.fromtimestamp(
                    p.stat().st_mtime, tz=datetime.timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
            for p in backup_mgr.list_backups()
        ]
        return render_template(
            "backups.html",
            active_page="backups",
            backups=backups,
            **_common_context(),
        )

    @app.route("/api/system/status", methods=["GET"])
    def get_system_status() -> Any:
        return jsonify(
            {
                "host_name": platform.node() or "localhost",
                "os": platform.platform(),
                "is_admin": checker.is_admin(),
                "server_time": datetime.datetime.now().isoformat(),
            }
        )

    @app.route("/api/services", methods=["GET"])
    def list_services() -> Any:
        services = loader.get_services(order_ascending=True)
        results = []

        for svc in services:
            try:
                status = service_adapter.query_status_sync(svc.service_name)
                state = status.state.value
                win32_code = status.win32_exit_code
            except ServiceNotFoundError:
                state = "NOT_INSTALLED"
                win32_code = -1
            except Exception:
                state = "ERROR"
                win32_code = -1

            results.append(
                {
                    "id": svc.id,
                    "display_name": svc.display_name,
                    "service_name": svc.service_name,
                    "startup_type": svc.startup_type,
                    "order": svc.order,
                    "state": state,
                    "win32_exit_code": win32_code,
                }
            )

        return jsonify({"services": results, "total": len(results)})

    @app.route("/api/services/<service_id>/<action>", methods=["POST"])
    def handle_service_action(service_id: str, action: str) -> Any:
        if action not in ("start", "stop", "restart"):
            return jsonify({"error": f"Invalid action '{action}'. Allowed: start, stop, restart."}), 400

        svc = loader.get_service_by_id(service_id)
        if not svc:
            return jsonify({"error": f"Service with ID '{service_id}' not found in configuration."}), 404

        streamer.broadcast(
            f"Disparando ação '{action.upper()}' no serviço '{svc.display_name}' ({svc.service_name})...",
            level="INFO",
            channel="services",
        )

        try:
            if action == "start":
                status = service_adapter.start_service_sync(svc.service_name, wait=True)
            elif action == "stop":
                status = service_adapter.stop_service_sync(svc.service_name, wait=True)
            else:
                status = service_adapter.restart_service_sync(svc.service_name)

            streamer.broadcast(
                f"Serviço '{svc.display_name}' atualizado para o estado: {status.state.value} (Win32 Code: {status.win32_exit_code}).",
                level="SUCCESS",
                channel="services",
            )

            return jsonify(
                {
                    "message": f"Action '{action}' executed successfully on '{service_id}'.",
                    "service_id": service_id,
                    "service_name": svc.service_name,
                    "state": status.state.value,
                    "win32_exit_code": status.win32_exit_code,
                }
            )

        except AdministrativePrivilegesRequiredError as exc:
            streamer.broadcast(f"Acesso negado para ação '{action}' em '{svc.display_name}': {exc}", level="ERROR", channel="services")
            return jsonify({"error": str(exc), "code": "ADMIN_REQUIRED"}), 403
        except ServiceNotFoundError as exc:
            streamer.broadcast(f"Serviço '{svc.service_name}' não encontrado no Windows.", level="ERROR", channel="services")
            return jsonify({"error": str(exc), "code": "SERVICE_NOT_FOUND"}), 404
        except ServiceManagerError as exc:
            streamer.broadcast(f"Erro no serviço '{svc.display_name}': {exc}", level="ERROR", channel="services")
            return jsonify({"error": str(exc), "code": "SERVICE_ERROR"}), 500
        except Exception as exc:
            streamer.broadcast(f"Falha inesperada: {exc}", level="ERROR", channel="services")
            return jsonify({"error": f"Unexpected error: {exc}", "code": "INTERNAL_ERROR"}), 500

    @app.route("/api/services/batch/<action>", methods=["POST"])
    def handle_batch_action(action: str) -> Any:
        if action not in ("start", "stop", "restart"):
            return jsonify({"error": f"Invalid batch action '{action}'. Allowed: start, stop, restart."}), 400

        services = loader.get_services(order_ascending=True)
        if not services:
            return jsonify({"error": "No services loaded in configuration."}), 400

        try:
            if action == "start":
                streamer.broadcast(
                    "Iniciando todos os serviços em ordem crescente (1 ➔ N)...",
                    level="INFO",
                    channel="services",
                )
                statuses = service_adapter.start_services_sequence_sync(services)
                order_desc = "ordem crescente (1 ➔ N)"
            elif action == "stop":
                streamer.broadcast(
                    "Parando todos os serviços em ordem inversa (N ➔ 1) conforme RF01...",
                    level="INFO",
                    channel="services",
                )
                statuses = service_adapter.stop_services_sequence_sync(services)
                order_desc = "ordem inversa (N ➔ 1 - RF01)"
            else:
                streamer.broadcast(
                    "Reiniciando todos os serviços (Parada inversa N ➔ 1 e Subida 1 ➔ N)...",
                    level="INFO",
                    channel="services",
                )
                statuses = service_adapter.restart_services_sequence_sync(services)
                order_desc = "parada inversa (N ➔ 1) seguida de subida (1 ➔ N)"

            streamer.broadcast(
                f"Todos os {len(statuses)} serviços processados com sucesso ({order_desc}).",
                level="SUCCESS",
                channel="services",
            )

            return jsonify(
                {
                    "message": f"Todos os serviços foram executados com sucesso ({order_desc}).",
                    "action": action,
                    "order_applied": order_desc,
                    "total_processed": len(statuses),
                    "services": [
                        {
                            "service_name": s.service_name,
                            "state": s.state.value,
                            "win32_exit_code": s.win32_exit_code,
                        }
                        for s in statuses
                    ],
                }
            )

        except AdministrativePrivilegesRequiredError as exc:
            streamer.broadcast(
                f"Acesso negado para ação em lote '{action}': {exc}",
                level="ERROR",
                channel="services",
            )
            return jsonify({"error": str(exc), "code": "ADMIN_REQUIRED"}), 403
        except ServiceManagerError as exc:
            streamer.broadcast(
                f"Erro na execução em lote: {exc}",
                level="ERROR",
                channel="services",
            )
            return jsonify({"error": str(exc), "code": "SERVICE_ERROR"}), 500
        except Exception as exc:
            streamer.broadcast(
                f"Falha inesperada na execução em lote: {exc}",
                level="ERROR",
                channel="services",
            )
            return jsonify({"error": f"Unexpected error: {exc}", "code": "INTERNAL_ERROR"}), 500

    @app.route("/api/backups", methods=["GET"])
    def list_backups_api() -> Any:
        archives = backup_mgr.list_backups()
        data = [
            {
                "name": p.name,
                "path": str(p),
                "size_bytes": p.stat().st_size,
                "modified_at": datetime.datetime.fromtimestamp(
                    p.stat().st_mtime, tz=datetime.timezone.utc
                ).isoformat(),
            }
            for p in archives
        ]
        return jsonify({"backups": data, "total": len(data)})

    @app.route("/api/logs/stream", methods=["GET"])
    def stream_logs() -> Response:
        """Server-Sent Events endpoint streaming real-time log messages."""
        return Response(
            streamer.sse_generator(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.route("/api/logs/history", methods=["GET"])
    def get_logs_history() -> Any:
        """Returns the recent in-memory log history."""
        return jsonify({"logs": streamer.get_history()})

    return app


if __name__ == "__main__":
    server_app = create_app()
    server_app.run(host="127.0.0.1", port=5000, debug=True)
