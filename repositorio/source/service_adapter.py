"""Windows Service Manager adapter using sc.exe."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from source.process_runner import AsyncProcessRunner, ProcessResult
from source.privileges import PrivilegeChecker
from source.services_config import ServiceConfig


class ServiceState(str, Enum):
    """Normalized Windows Service states."""

    STOPPED = "STOPPED"
    START_PENDING = "START_PENDING"
    STOP_PENDING = "STOP_PENDING"
    RUNNING = "RUNNING"
    CONTINUE_PENDING = "CONTINUE_PENDING"
    PAUSE_PENDING = "PAUSE_PENDING"
    PAUSED = "PAUSED"
    UNKNOWN = "UNKNOWN"


_STATE_CODE_MAP: dict[int, ServiceState] = {
    1: ServiceState.STOPPED,
    2: ServiceState.START_PENDING,
    3: ServiceState.STOP_PENDING,
    4: ServiceState.RUNNING,
    5: ServiceState.CONTINUE_PENDING,
    6: ServiceState.PAUSE_PENDING,
    7: ServiceState.PAUSED,
}


class ServiceManagerError(Exception):
    """Base exception for Service Manager errors."""


class ServiceNotFoundError(ServiceManagerError):
    """Raised when the specified Windows service is not installed."""


class ServiceCommandError(ServiceManagerError):
    """Raised when sc.exe returns an unexpected error."""


class ServiceTimeoutError(ServiceManagerError):
    """Raised when a service transition times out."""


@dataclass(frozen=True)
class ServiceStatus:
    """Detailed status representation of a Windows Service."""

    service_name: str
    state: ServiceState
    state_code: int
    win32_exit_code: int
    service_exit_code: int
    raw_output: str


def parse_sc_query_output(output: str, service_name: str) -> ServiceStatus:
    """Parses standard sc.exe query output across locales (e.g. en-US, pt-BR).

    Args:
        output: Raw stdout from sc.exe query.
        service_name: Name of the queried service.

    Returns:
        Structured ServiceStatus object.

    Raises:
        ServiceCommandError: If output cannot be parsed.
    """
    state_match = re.search(
        r"(?:STATE|ESTADO)\s*:\s*(\d+)\s+([A-Z_]+)",
        output,
        re.IGNORECASE,
    )

    if not state_match:
        raise ServiceCommandError(
            f"Could not parse service state from sc.exe output for '{service_name}'. Output:\n{output}"
        )

    state_code = int(state_match.group(1))
    state_str = state_match.group(2).upper()
    state = _STATE_CODE_MAP.get(state_code)

    if state is None:
        try:
            state = ServiceState(state_str)
        except ValueError:
            state = ServiceState.UNKNOWN

    win32_match = re.search(
        r"(?:WIN32_EXIT_CODE|C[ÓO\ufffd]DIGO_DE_SA[ÍI\ufffd]DA_DO_WIN32)\s*:\s*(\d+)",
        output,
        re.IGNORECASE,
    )
    service_exit_match = re.search(
        r"(?:SERVICE_EXIT_CODE|C[ÓO\ufffd]DIGO_DE_SA[ÍI\ufffd]DA_DO_SERVI[ÇC\ufffd]O)\s*:\s*(\d+)",
        output,
        re.IGNORECASE,
    )

    win32_exit_code = int(win32_match.group(1)) if win32_match else 0
    service_exit_code = int(service_exit_match.group(1)) if service_exit_match else 0

    return ServiceStatus(
        service_name=service_name,
        state=state,
        state_code=state_code,
        win32_exit_code=win32_exit_code,
        service_exit_code=service_exit_code,
        raw_output=output,
    )


class WindowsServiceAdapter:
    """Adapter for interacting with Windows Service Control Manager via sc.exe."""

    def __init__(
        self,
        runner: AsyncProcessRunner | None = None,
        sc_binary: str = "sc.exe",
        taskkill_binary: str = "taskkill.exe",
        privilege_checker: PrivilegeChecker | None = None,
        enforce_admin: bool = False,
    ) -> None:
        self._runner = runner or AsyncProcessRunner()
        self._sc_binary = sc_binary
        self._taskkill_binary = taskkill_binary
        self._privilege_checker = privilege_checker or PrivilegeChecker()
        self._enforce_admin = enforce_admin

    async def query_status(self, service_name: str) -> ServiceStatus:
        """Asynchronously queries the status of a Windows service.

        Args:
            service_name: Windows service name (e.g. '.01_TOTVS|LicenseVirtual').

        Returns:
            ServiceStatus with current state and exit codes.

        Raises:
            ServiceNotFoundError: If service is not installed (sc code 1060).
            ServiceCommandError: If sc.exe fails or output is invalid.
        """
        command = [self._sc_binary, "query", service_name]
        result: ProcessResult = await self._runner.run(command, check=False)

        combined_output = f"{result.stdout}\n{result.stderr}"

        if result.exit_code != 0:
            if (
                "1060" in combined_output
                or "não existe" in combined_output.lower()
                or "does not exist" in combined_output.lower()
            ):
                raise ServiceNotFoundError(
                    f"Windows service '{service_name}' does not exist as an installed service."
                )
            raise ServiceCommandError(
                f"Failed to query service '{service_name}' (exit code {result.exit_code}):\n{combined_output}"
            )

        return parse_sc_query_output(result.stdout, service_name)

    def query_status_sync(self, service_name: str) -> ServiceStatus:
        """Synchronous helper for query_status."""
        return asyncio.run(self.query_status(service_name))

    async def get_service_pid(self, service_name: str) -> int:
        """Queries the Process ID (PID) of a running service using 'sc queryex'."""
        command = [self._sc_binary, "queryex", service_name]
        result: ProcessResult = await self._runner.run(command, check=False)

        if result.exit_code != 0:
            return 0

        pid_match = re.search(r"PID\s*:\s*(\d+)", result.stdout, re.IGNORECASE)
        return int(pid_match.group(1)) if pid_match else 0

    async def wait_for_state(
        self,
        service_name: str,
        target_state: ServiceState,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
    ) -> ServiceStatus:
        """Waits asynchronously for a service to reach a target state.

        Args:
            service_name: Service name to monitor.
            target_state: Desired ServiceState (e.g. RUNNING, STOPPED).
            timeout: Maximum wait time in seconds.
            poll_interval: Interval between queries in seconds.

        Returns:
            ServiceStatus once target state is achieved.

        Raises:
            ServiceTimeoutError: If target state is not reached within timeout.
        """
        deadline = time.monotonic() + timeout
        last_status: ServiceStatus | None = None

        while True:
            last_status = await self.query_status(service_name)
            if last_status.state == target_state:
                return last_status
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(poll_interval)

        current_state = last_status.state if last_status else ServiceState.UNKNOWN
        raise ServiceTimeoutError(
            f"Service '{service_name}' timed out after {timeout}s waiting for state '{target_state}' "
            f"(current state: '{current_state}')."
        )

    async def start_service(
        self,
        service_name: str,
        wait: bool = True,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> ServiceStatus:
        """Starts a Windows service.

        Args:
            service_name: Name of the service to start.
            wait: Whether to block until the service is in RUNNING state.
            timeout: Maximum seconds to wait for RUNNING state.
            poll_interval: Polling frequency in seconds.

        Returns:
            ServiceStatus representing the service state.

        Raises:
            AdministrativePrivilegesRequiredError: If enforce_admin=True and process is not elevated.
            ServiceNotFoundError: If service is not installed.
            ServiceCommandError: If command execution fails.
            ServiceTimeoutError: If wait=True and service doesn't reach RUNNING within timeout.
        """
        if self._enforce_admin:
            self._privilege_checker.ensure_admin(f"start service '{service_name}'")

        initial_status = await self.query_status(service_name)
        if initial_status.state == ServiceState.RUNNING:
            return initial_status

        command = [self._sc_binary, "start", service_name]
        result: ProcessResult = await self._runner.run(command, check=False)
        combined_output = f"{result.stdout}\n{result.stderr}"

        if result.exit_code != 0:
            is_already_running = (
                "1056" in combined_output
                or "already running" in combined_output.lower()
                or "já está sendo executada" in combined_output.lower()
            )
            if not is_already_running:
                raise ServiceCommandError(
                    f"Failed to start service '{service_name}' (exit code {result.exit_code}):\n{combined_output}"
                )

        if wait:
            return await self.wait_for_state(
                service_name,
                target_state=ServiceState.RUNNING,
                timeout=timeout,
                poll_interval=poll_interval,
            )

        return await self.query_status(service_name)

    def start_service_sync(
        self,
        service_name: str,
        wait: bool = True,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> ServiceStatus:
        """Synchronous helper for start_service."""
        return asyncio.run(
            self.start_service(
                service_name=service_name,
                wait=wait,
                timeout=timeout,
                poll_interval=poll_interval,
            )
        )

    async def stop_service(
        self,
        service_name: str,
        wait: bool = True,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
        force_kill_on_timeout: bool = False,
    ) -> ServiceStatus:
        """Stops a Windows service with TRD 60s default timeout and optional escalation.

        Args:
            service_name: Name of the service to stop.
            wait: Whether to block until the service is in STOPPED state.
            timeout: Maximum seconds to wait before timing out (TRD default: 60s).
            poll_interval: Polling frequency in seconds.
            force_kill_on_timeout: If True, escalate to taskkill on timeout per TRD.

        Returns:
            ServiceStatus representing the stopped service.

        Raises:
            AdministrativePrivilegesRequiredError: If enforce_admin=True and process is not elevated.
            ServiceNotFoundError: If service is not installed.
            ServiceCommandError: If command execution fails.
            ServiceTimeoutError: If service fails to stop within timeout.
        """
        if self._enforce_admin:
            self._privilege_checker.ensure_admin(f"stop service '{service_name}'")

        initial_status = await self.query_status(service_name)
        if initial_status.state == ServiceState.STOPPED:
            return initial_status

        command = [self._sc_binary, "stop", service_name]
        result: ProcessResult = await self._runner.run(command, check=False)
        combined_output = f"{result.stdout}\n{result.stderr}"

        if result.exit_code != 0:
            is_already_stopped = (
                "1062" in combined_output
                or "not been started" in combined_output.lower()
                or "não foi iniciado" in combined_output.lower()
            )
            if not is_already_stopped:
                raise ServiceCommandError(
                    f"Failed to stop service '{service_name}' (exit code {result.exit_code}):\n{combined_output}"
                )

        if wait:
            try:
                return await self.wait_for_state(
                    service_name,
                    target_state=ServiceState.STOPPED,
                    timeout=timeout,
                    poll_interval=poll_interval,
                )
            except ServiceTimeoutError:
                if not force_kill_on_timeout:
                    raise

                # TRD: Timeout padrão de 60s antes de escalonar para encerramento forçado
                pid = await self.get_service_pid(service_name)
                if pid > 0:
                    kill_cmd = [self._taskkill_binary, "/F", "/PID", str(pid)]
                    await self._runner.run(kill_cmd, check=False)
                    return await self.wait_for_state(
                        service_name,
                        target_state=ServiceState.STOPPED,
                        timeout=min(5.0, timeout),
                        poll_interval=poll_interval,
                    )
                raise

        return await self.query_status(service_name)

    def stop_service_sync(
        self,
        service_name: str,
        wait: bool = True,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
        force_kill_on_timeout: bool = False,
    ) -> ServiceStatus:
        """Synchronous helper for stop_service."""
        return asyncio.run(
            self.stop_service(
                service_name=service_name,
                wait=wait,
                timeout=timeout,
                poll_interval=poll_interval,
                force_kill_on_timeout=force_kill_on_timeout,
            )
        )

    async def restart_service(
        self,
        service_name: str,
        stop_timeout: float = 60.0,
        start_timeout: float = 30.0,
        poll_interval: float = 1.0,
        force_kill_on_timeout: bool = False,
    ) -> ServiceStatus:
        """Restarts a Windows service (stop followed by start).

        Args:
            service_name: Name of the service.
            stop_timeout: Seconds to wait for service to stop.
            start_timeout: Seconds to wait for service to start.
            poll_interval: Polling frequency in seconds.
            force_kill_on_timeout: If True, escalate to taskkill on stop timeout.

        Returns:
            ServiceStatus representing the newly running service.
        """
        if self._enforce_admin:
            self._privilege_checker.ensure_admin(f"restart service '{service_name}'")

        await self.stop_service(
            service_name,
            wait=True,
            timeout=stop_timeout,
            poll_interval=poll_interval,
            force_kill_on_timeout=force_kill_on_timeout,
        )
        return await self.start_service(
            service_name,
            wait=True,
            timeout=start_timeout,
            poll_interval=poll_interval,
        )

    def restart_service_sync(
        self,
        service_name: str,
        stop_timeout: float = 60.0,
        start_timeout: float = 30.0,
        poll_interval: float = 1.0,
        force_kill_on_timeout: bool = False,
    ) -> ServiceStatus:
        """Synchronous helper for restart_service."""
        return asyncio.run(
            self.restart_service(
                service_name=service_name,
                stop_timeout=stop_timeout,
                start_timeout=start_timeout,
                poll_interval=poll_interval,
                force_kill_on_timeout=force_kill_on_timeout,
            )
        )

    async def query_multiple(
        self,
        service_names: Sequence[str],
    ) -> dict[str, ServiceStatus]:
        """Queries status of multiple services concurrently.

        Args:
            service_names: List or sequence of service names.

        Returns:
            Dictionary mapping service_name to ServiceStatus.
        """
        tasks = [self.query_status(name) for name in service_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        status_map: dict[str, ServiceStatus] = {}
        for name, res in zip(service_names, results):
            if isinstance(res, Exception):
                raise res
            status_map[name] = res

        return status_map

    async def start_services_sequence(
        self,
        services: Sequence[ServiceConfig],
        wait: bool = True,
        timeout_per_service: float = 30.0,
        poll_interval: float = 1.0,
    ) -> list[ServiceStatus]:
        """Starts a sequence of services in ASCENDING order (order 1 -> 2 -> ... -> N).

        Args:
            services: Sequence of ServiceConfig objects.
            wait: Whether to await RUNNING state for each before starting next.
            timeout_per_service: Timeout seconds per service.
            poll_interval: Polling frequency in seconds.

        Returns:
            List of ServiceStatus for each service in execution order.
        """
        ordered = sorted(services, key=lambda s: s.order)
        results: list[ServiceStatus] = []
        for svc in ordered:
            status = await self.start_service(
                service_name=svc.service_name,
                wait=wait,
                timeout=timeout_per_service,
                poll_interval=poll_interval,
            )
            results.append(status)
        return results

    def start_services_sequence_sync(
        self,
        services: Sequence[ServiceConfig],
        wait: bool = True,
        timeout_per_service: float = 30.0,
        poll_interval: float = 1.0,
    ) -> list[ServiceStatus]:
        """Synchronous helper for start_services_sequence."""
        return asyncio.run(
            self.start_services_sequence(
                services=services,
                wait=wait,
                timeout_per_service=timeout_per_service,
                poll_interval=poll_interval,
            )
        )

    async def stop_services_sequence(
        self,
        services: Sequence[ServiceConfig],
        wait: bool = True,
        timeout_per_service: float = 60.0,
        poll_interval: float = 1.0,
        force_kill_on_timeout: bool = False,
    ) -> list[ServiceStatus]:
        """Stops a sequence of services in REVERSE order per RF01 (order N -> ... -> 2 -> 1).

        Args:
            services: Sequence of ServiceConfig objects.
            wait: Whether to await STOPPED state before proceeding.
            timeout_per_service: Timeout in seconds per service (default 60s per TRD).
            poll_interval: Polling frequency in seconds.
            force_kill_on_timeout: If True, escalate to taskkill on stop timeout.

        Returns:
            List of ServiceStatus in reverse shutdown order.
        """
        ordered = sorted(services, key=lambda s: s.order, reverse=True)
        results: list[ServiceStatus] = []
        for svc in ordered:
            status = await self.stop_service(
                service_name=svc.service_name,
                wait=wait,
                timeout=timeout_per_service,
                poll_interval=poll_interval,
                force_kill_on_timeout=force_kill_on_timeout,
            )
            results.append(status)
        return results

    def stop_services_sequence_sync(
        self,
        services: Sequence[ServiceConfig],
        wait: bool = True,
        timeout_per_service: float = 60.0,
        poll_interval: float = 1.0,
        force_kill_on_timeout: bool = False,
    ) -> list[ServiceStatus]:
        """Synchronous helper for stop_services_sequence."""
        return asyncio.run(
            self.stop_services_sequence(
                services=services,
                wait=wait,
                timeout_per_service=timeout_per_service,
                poll_interval=poll_interval,
                force_kill_on_timeout=force_kill_on_timeout,
            )
        )

    async def restart_services_sequence(
        self,
        services: Sequence[ServiceConfig],
        stop_timeout: float = 60.0,
        start_timeout: float = 30.0,
        poll_interval: float = 1.0,
        force_kill_on_timeout: bool = False,
    ) -> list[ServiceStatus]:
        """Restarts all services: first stops all in REVERSE order (N -> 1), then starts all in ASCENDING order (1 -> N)."""
        await self.stop_services_sequence(
            services=services,
            wait=True,
            timeout_per_service=stop_timeout,
            poll_interval=poll_interval,
            force_kill_on_timeout=force_kill_on_timeout,
        )
        return await self.start_services_sequence(
            services=services,
            wait=True,
            timeout_per_service=start_timeout,
            poll_interval=poll_interval,
        )

    def restart_services_sequence_sync(
        self,
        services: Sequence[ServiceConfig],
        stop_timeout: float = 60.0,
        start_timeout: float = 30.0,
        poll_interval: float = 1.0,
        force_kill_on_timeout: bool = False,
    ) -> list[ServiceStatus]:
        """Synchronous helper for restart_services_sequence."""
        return asyncio.run(
            self.restart_services_sequence(
                services=services,
                stop_timeout=stop_timeout,
                start_timeout=start_timeout,
                poll_interval=poll_interval,
                force_kill_on_timeout=force_kill_on_timeout,
            )
        )
