"""Unit tests for Flask API and Cockpit endpoints in source/app.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from source.app import create_app
from source.privileges import AdministrativePrivilegesRequiredError, PrivilegeChecker
from source.service_adapter import ServiceState, ServiceStatus, WindowsServiceAdapter


class TestAppEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temp_dir.name)
        self.backup_dir = self.root_path / "backups"
        self.backup_dir.mkdir()

        # Mock adapter
        self.mock_adapter = MagicMock(spec=WindowsServiceAdapter)
        self.mock_checker = MagicMock(spec=PrivilegeChecker)
        self.mock_checker.is_admin.return_value = True

        # Default query status returns RUNNING
        sample_status = ServiceStatus(
            service_name="test_svc",
            state=ServiceState.RUNNING,
            state_code=4,
            win32_exit_code=0,
            service_exit_code=0,
            raw_output="",
        )
        self.mock_adapter.query_status_sync.return_value = sample_status
        self.mock_adapter.start_service_sync.return_value = sample_status
        self.mock_adapter.stop_service_sync.return_value = ServiceStatus(
            service_name="test_svc",
            state=ServiceState.STOPPED,
            state_code=1,
            win32_exit_code=0,
            service_exit_code=0,
            raw_output="",
        )
        self.mock_adapter.restart_service_sync.return_value = sample_status

        self.app = create_app(
            backup_dir=self.backup_dir,
            adapter=self.mock_adapter,
            privilege_checker=self.mock_checker,
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_index_page(self) -> None:
        """GET / should render the HTML cockpit."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Hoshu", html)
        self.assertIn("Cockpit Operacional", html)
        self.assertIn(".01_TOTVS|LicenseVirtual", html)
        self.assertIn("toggleSidebarCollapse", html)
        self.assertIn("theme-switch", html)
        self.assertIn("Operador Hoshu", html)

    def test_services_panel_page(self) -> None:
        """GET /services should render the dedicated Services panel."""
        response = self.client.get("/services")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Gerenciamento de Serviços Windows", html)
        self.assertIn(".01_TOTVS|LicenseVirtual", html)

    def test_patch_panel_page(self) -> None:
        """GET /patch should render the dedicated Patch panel."""
        response = self.client.get("/patch")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Pipeline de Aplicação de Patches ERP", html)
        self.assertIn("Garantia de Rollback", html)

    def test_devops_panel_page(self) -> None:
        """GET /devops should render the dedicated DevOps panel."""
        response = self.client.get("/devops")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("DevOps & Esteira de Compilação Git", html)
        self.assertIn("devops-branch", html)

    def test_backups_panel_page(self) -> None:
        """GET /backups should render the dedicated Backups panel."""
        response = self.client.get("/backups")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Snapshots e Backups do Repositório", html)

    def test_api_system_status(self) -> None:
        """GET /api/system/status returns machine and privilege status."""
        response = self.client.get("/api/system/status")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("host_name", data)
        self.assertTrue(data["is_admin"])

    def test_api_list_services(self) -> None:
        """GET /api/services returns JSON with services and live states."""
        response = self.client.get("/api/services")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("services", data)
        self.assertEqual(data["total"], 5)
        first_svc = data["services"][0]
        self.assertEqual(first_svc["id"], ".01_TOTVS|LicenseVirtual")
        self.assertEqual(first_svc["state"], "RUNNING")

    def test_api_start_service(self) -> None:
        """POST /api/services/<id>/start executes start_service."""
        response = self.client.post("/api/services/.01_TOTVS%7CLicenseVirtual/start")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["state"], "RUNNING")
        self.mock_adapter.start_service_sync.assert_called_once_with(".01_TOTVS|LicenseVirtual", wait=True)

    def test_api_stop_service(self) -> None:
        """POST /api/services/<id>/stop executes stop_service."""
        response = self.client.post("/api/services/.01_TOTVS%7CLicenseVirtual/stop")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["state"], "STOPPED")
        self.mock_adapter.stop_service_sync.assert_called_once_with(".01_TOTVS|LicenseVirtual", wait=True)

    def test_api_restart_service(self) -> None:
        """POST /api/services/<id>/restart executes restart_service."""
        response = self.client.post("/api/services/.01_TOTVS%7CLicenseVirtual/restart")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["state"], "RUNNING")
        self.mock_adapter.restart_service_sync.assert_called_once_with(".01_TOTVS|LicenseVirtual")

    def test_api_invalid_action(self) -> None:
        response = self.client.post("/api/services/.01_TOTVS%7CLicenseVirtual/destroy")
        self.assertEqual(response.status_code, 400)

    def test_api_service_not_found(self) -> None:
        response = self.client.post("/api/services/non_existent/start")
        self.assertEqual(response.status_code, 404)

    def test_api_action_admin_required_error(self) -> None:
        self.mock_adapter.start_service_sync.side_effect = AdministrativePrivilegesRequiredError("start")
        response = self.client.post("/api/services/.01_TOTVS%7CLicenseVirtual/start")
        self.assertEqual(response.status_code, 403)
        data = response.get_json()
        self.assertEqual(data["code"], "ADMIN_REQUIRED")

    def test_api_list_backups(self) -> None:
        # Create dummy backup file
        (self.backup_dir / "backup_test.zip").write_bytes(b"PK000")
        response = self.client.get("/api/backups")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["backups"][0]["name"], "backup_test.zip")

    def test_api_batch_start(self) -> None:
        self.mock_adapter.start_services_sequence_sync.return_value = [
            ServiceStatus("svc1", ServiceState.RUNNING, 4, 0, 0, "")
        ]
        response = self.client.post("/api/services/batch/start")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["action"], "start")
        self.assertIn("ordem crescente", data["order_applied"])

    def test_api_batch_stop_rf01(self) -> None:
        self.mock_adapter.stop_services_sequence_sync.return_value = [
            ServiceStatus("svc1", ServiceState.STOPPED, 1, 0, 0, "")
        ]
        response = self.client.post("/api/services/batch/stop")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["action"], "stop")
        self.assertIn("ordem inversa", data["order_applied"])


if __name__ == "__main__":
    unittest.main()
