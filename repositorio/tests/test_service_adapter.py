"""Unit tests for source/service_adapter.py and process_runner.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from source.process_runner import AsyncProcessRunner, ProcessResult
from source.service_adapter import (
    ServiceCommandError,
    ServiceNotFoundError,
    ServiceState,
    ServiceTimeoutError,
    WindowsServiceAdapter,
    parse_sc_query_output,
)
from source.services_config import ServiceConfig

SAMPLE_EN_RUNNING = """
SERVICE_NAME: .01_TOTVS|LicenseVirtual
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)
        WIN32_EXIT_CODE    : 0  (0x0)
        SERVICE_EXIT_CODE  : 0  (0x0)
        CHECKPOINT         : 0x0
        WAIT_HINT          : 0x0
"""

SAMPLE_PT_RUNNING = """
NOME_DO_SERVIÇO: Spooler 
    TIPO                       : 110  WIN32_OWN_PROCESS  (interactive)
    ESTADO                     : 4  RUNNING 
                                (STOPPABLE, NOT_PAUSABLE, IGNORES_SHUTDOWN)
    CÓDIGO_DE_SAÍDA_DO_WIN32   : 0  (0x0)
    CÓDIGO_DE_SAÍDA_DO_SERVIÇO : 0  (0x0)
    PONTO_DE_VERIFICAÇÃO       : 0x0
    AGUARDAR_DICA              : 0x0
"""

SAMPLE_STOPPED = """
SERVICE_NAME: .02_TOTVS|DBAccess
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 1  STOPPED
        WIN32_EXIT_CODE    : 0  (0x0)
        SERVICE_EXIT_CODE  : 0  (0x0)
        CHECKPOINT         : 0x0
        WAIT_HINT          : 0x0
"""

SAMPLE_START_PENDING = """
SERVICE_NAME: .03_TOTVS|Broker_Master
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 2  START_PENDING
        WIN32_EXIT_CODE    : 0  (0x0)
        SERVICE_EXIT_CODE  : 0  (0x0)
"""

SAMPLE_STOP_PENDING = """
SERVICE_NAME: .03_TOTVS|Broker_Slave1
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 3  STOP_PENDING
        WIN32_EXIT_CODE    : 0  (0x0)
        SERVICE_EXIT_CODE  : 0  (0x0)
"""

SAMPLE_QUERYEX_WITH_PID = """
SERVICE_NAME: Spooler
        TYPE               : 110  WIN32_OWN_PROCESS  (interactive)
        STATE              : 4  RUNNING
        WIN32_EXIT_CODE    : 0  (0x0)
        SERVICE_EXIT_CODE  : 0  (0x0)
        CHECKPOINT         : 0x0
        WAIT_HINT          : 0x0
        PID                : 4321
        FLAGS              :
"""


class TestParseScQueryOutput(unittest.TestCase):
    def test_parse_en_running(self) -> None:
        status = parse_sc_query_output(SAMPLE_EN_RUNNING, ".01_TOTVS|LicenseVirtual")
        self.assertEqual(status.service_name, ".01_TOTVS|LicenseVirtual")
        self.assertEqual(status.state, ServiceState.RUNNING)
        self.assertEqual(status.state_code, 4)
        self.assertEqual(status.win32_exit_code, 0)
        self.assertEqual(status.service_exit_code, 0)

    def test_parse_pt_running(self) -> None:
        status = parse_sc_query_output(SAMPLE_PT_RUNNING, "Spooler")
        self.assertEqual(status.service_name, "Spooler")
        self.assertEqual(status.state, ServiceState.RUNNING)
        self.assertEqual(status.state_code, 4)
        self.assertEqual(status.win32_exit_code, 0)

    def test_parse_stopped(self) -> None:
        status = parse_sc_query_output(SAMPLE_STOPPED, ".02_TOTVS|DBAccess")
        self.assertEqual(status.state, ServiceState.STOPPED)
        self.assertEqual(status.state_code, 1)

    def test_parse_start_pending(self) -> None:
        status = parse_sc_query_output(SAMPLE_START_PENDING, ".03_TOTVS|Broker_Master")
        self.assertEqual(status.state, ServiceState.START_PENDING)
        self.assertEqual(status.state_code, 2)

    def test_parse_stop_pending(self) -> None:
        status = parse_sc_query_output(SAMPLE_STOP_PENDING, ".03_TOTVS|Broker_Slave1")
        self.assertEqual(status.state, ServiceState.STOP_PENDING)
        self.assertEqual(status.state_code, 3)

    def test_parse_invalid_output(self) -> None:
        with self.assertRaises(ServiceCommandError):
            parse_sc_query_output("Invalid output without state line", "TestSvc")


class TestWindowsServiceAdapter(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.mock_runner = AsyncMock(spec=AsyncProcessRunner)
        self.adapter = WindowsServiceAdapter(runner=self.mock_runner)

    async def test_query_status_running_success(self) -> None:
        self.mock_runner.run.return_value = ProcessResult(
            command=["sc.exe", "query", "Spooler"],
            exit_code=0,
            stdout=SAMPLE_PT_RUNNING,
            stderr="",
        )

        status = await self.adapter.query_status("Spooler")
        self.assertEqual(status.service_name, "Spooler")
        self.assertEqual(status.state, ServiceState.RUNNING)
        self.mock_runner.run.assert_called_once_with(["sc.exe", "query", "Spooler"], check=False)

    async def test_query_status_service_not_found(self) -> None:
        self.mock_runner.run.return_value = ProcessResult(
            command=["sc.exe", "query", "UnknownService"],
            exit_code=1,
            stdout="[SC] EnumQueryServicesStatus:OpenService FALHA 1060:\nO serviço não existe como serviço instalado.",
            stderr="",
        )

        with self.assertRaises(ServiceNotFoundError):
            await self.adapter.query_status("UnknownService")

    async def test_query_status_unexpected_error(self) -> None:
        self.mock_runner.run.return_value = ProcessResult(
            command=["sc.exe", "query", "BadService"],
            exit_code=5,
            stdout="Access Denied",
            stderr="Error 5",
        )

        with self.assertRaises(ServiceCommandError) as ctx:
            await self.adapter.query_status("BadService")
        self.assertIn("exit code 5", str(ctx.exception))

    async def test_get_service_pid(self) -> None:
        self.mock_runner.run.return_value = ProcessResult(
            command=["sc.exe", "queryex", "Spooler"],
            exit_code=0,
            stdout=SAMPLE_QUERYEX_WITH_PID,
            stderr="",
        )
        pid = await self.adapter.get_service_pid("Spooler")
        self.assertEqual(pid, 4321)

    async def test_start_service_already_running(self) -> None:
        # Initial query returns RUNNING, should not call 'sc start'
        self.mock_runner.run.return_value = ProcessResult(
            command=["sc.exe", "query", "Spooler"],
            exit_code=0,
            stdout=SAMPLE_PT_RUNNING,
            stderr="",
        )
        status = await self.adapter.start_service("Spooler")
        self.assertEqual(status.state, ServiceState.RUNNING)
        self.assertEqual(self.mock_runner.run.call_count, 1)

    async def test_start_service_stopped_to_running(self) -> None:
        # 1. query (STOPPED) -> 2. sc start -> 3. query (RUNNING)
        self.mock_runner.run.side_effect = [
            ProcessResult(["sc.exe", "query", "Svc"], 0, SAMPLE_STOPPED, ""),
            ProcessResult(["sc.exe", "start", "Svc"], 0, "START_PENDING", ""),
            ProcessResult(["sc.exe", "query", "Svc"], 0, SAMPLE_EN_RUNNING, ""),
        ]

        status = await self.adapter.start_service("Svc", wait=True, poll_interval=0.01)
        self.assertEqual(status.state, ServiceState.RUNNING)

    async def test_start_service_timeout(self) -> None:
        def runner_mock(cmd, check=False):
            if "start" in cmd:
                return ProcessResult(cmd, 0, "START_PENDING", "")
            return ProcessResult(cmd, 0, SAMPLE_STOPPED, "")

        self.mock_runner.run.side_effect = runner_mock

        with self.assertRaises(ServiceTimeoutError):
            await self.adapter.start_service("Svc", wait=True, timeout=0.02, poll_interval=0.005)

    async def test_stop_service_already_stopped(self) -> None:
        self.mock_runner.run.return_value = ProcessResult(
            command=["sc.exe", "query", "Svc"],
            exit_code=0,
            stdout=SAMPLE_STOPPED,
            stderr="",
        )
        status = await self.adapter.stop_service("Svc")
        self.assertEqual(status.state, ServiceState.STOPPED)
        self.assertEqual(self.mock_runner.run.call_count, 1)

    async def test_stop_service_running_to_stopped(self) -> None:
        # 1. query (RUNNING) -> 2. sc stop -> 3. query (STOPPED)
        self.mock_runner.run.side_effect = [
            ProcessResult(["sc.exe", "query", "Svc"], 0, SAMPLE_EN_RUNNING, ""),
            ProcessResult(["sc.exe", "stop", "Svc"], 0, "STOP_PENDING", ""),
            ProcessResult(["sc.exe", "query", "Svc"], 0, SAMPLE_STOPPED, ""),
        ]

        status = await self.adapter.stop_service("Svc", wait=True, poll_interval=0.01)
        self.assertEqual(status.state, ServiceState.STOPPED)

    async def test_stop_service_force_kill_on_timeout(self) -> None:
        running_status = parse_sc_query_output(SAMPLE_EN_RUNNING, "Svc")
        stopped_status = parse_sc_query_output(SAMPLE_STOPPED, "Svc")

        # Mock initial query (running) and stop command (accepted)
        self.mock_runner.run.side_effect = [
            ProcessResult(["sc.exe", "query", "Svc"], 0, SAMPLE_EN_RUNNING, ""),
            ProcessResult(["sc.exe", "stop", "Svc"], 0, "STOP_PENDING", ""),
            ProcessResult(["sc.exe", "queryex", "Svc"], 0, SAMPLE_QUERYEX_WITH_PID, ""),
            ProcessResult(["taskkill.exe", "/F", "/PID", "4321"], 0, "SUCCESS", ""),
        ]

        with patch.object(
            self.adapter,
            "wait_for_state",
            side_effect=[
                ServiceTimeoutError("Timeout waiting for stop"),
                stopped_status,
            ],
        ) as mock_wait:
            status = await self.adapter.stop_service(
                "Svc",
                wait=True,
                timeout=60.0,
                force_kill_on_timeout=True,
            )
            self.assertEqual(status.state, ServiceState.STOPPED)
            self.assertEqual(mock_wait.call_count, 2)

    async def test_restart_service(self) -> None:
        with patch.object(self.adapter, "stop_service", new_callable=AsyncMock) as mock_stop, \
             patch.object(self.adapter, "start_service", new_callable=AsyncMock) as mock_start:
            mock_start.return_value = parse_sc_query_output(SAMPLE_EN_RUNNING, "Svc")

            res = await self.adapter.restart_service("Svc", poll_interval=0.01)
            self.assertEqual(res.state, ServiceState.RUNNING)
            mock_stop.assert_called_once()
            mock_start.assert_called_once()

    def test_sync_wrappers(self) -> None:
        with patch.object(self.adapter, "start_service", new_callable=AsyncMock) as mock_start, \
             patch.object(self.adapter, "stop_service", new_callable=AsyncMock) as mock_stop, \
             patch.object(self.adapter, "restart_service", new_callable=AsyncMock) as mock_restart:
            mock_status = parse_sc_query_output(SAMPLE_EN_RUNNING, "Svc")
            mock_start.return_value = mock_status
            mock_stop.return_value = parse_sc_query_output(SAMPLE_STOPPED, "Svc")
            mock_restart.return_value = mock_status

            self.assertEqual(self.adapter.start_service_sync("Svc").state, ServiceState.RUNNING)
            self.assertEqual(self.adapter.stop_service_sync("Svc").state, ServiceState.STOPPED)
            self.assertEqual(self.adapter.restart_service_sync("Svc").state, ServiceState.RUNNING)

    async def test_query_multiple(self) -> None:
        self.mock_runner.run.side_effect = [
            ProcessResult(["sc.exe", "query", "Svc1"], 0, SAMPLE_EN_RUNNING, ""),
            ProcessResult(["sc.exe", "query", "Svc2"], 0, SAMPLE_STOPPED, ""),
        ]

        result = await self.adapter.query_multiple(["Svc1", "Svc2"])
        self.assertEqual(len(result), 2)
        self.assertEqual(result["Svc1"].state, ServiceState.RUNNING)
        self.assertEqual(result["Svc2"].state, ServiceState.STOPPED)

    async def test_start_services_sequence_ascending_order(self) -> None:
        s1 = ServiceConfig("s1", "S1", "Service1", "Automatic", 1)
        s2 = ServiceConfig("s2", "S2", "Service2", "Automatic", 2)
        s3 = ServiceConfig("s3", "S3", "Service3", "Automatic", 3)

        call_order = []
        async def mock_start(service_name, **kwargs):
            call_order.append(service_name)
            return parse_sc_query_output(SAMPLE_EN_RUNNING, service_name)

        with patch.object(self.adapter, "start_service", side_effect=mock_start):
            results = await self.adapter.start_services_sequence([s3, s1, s2])
            self.assertEqual(call_order, ["Service1", "Service2", "Service3"])
            self.assertEqual(len(results), 3)

    async def test_stop_services_sequence_reverse_order_rf01(self) -> None:
        s1 = ServiceConfig("s1", "S1", "Service1", "Automatic", 1)
        s2 = ServiceConfig("s2", "S2", "Service2", "Automatic", 2)
        s3 = ServiceConfig("s3", "S3", "Service3", "Automatic", 3)

        call_order = []
        async def mock_stop(service_name, **kwargs):
            call_order.append(service_name)
            return parse_sc_query_output(SAMPLE_STOPPED, service_name)

        with patch.object(self.adapter, "stop_service", side_effect=mock_stop):
            results = await self.adapter.stop_services_sequence([s1, s3, s2])
            # RF01: Ordem de parada deve ser estritamente inversa (3 -> 2 -> 1)
            self.assertEqual(call_order, ["Service3", "Service2", "Service1"])
            self.assertEqual(len(results), 3)


if __name__ == "__main__":
    unittest.main()
