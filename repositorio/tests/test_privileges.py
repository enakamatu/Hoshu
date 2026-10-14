"""Unit tests for source/privileges.py."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from source.privileges import (
    AdministrativePrivilegesRequiredError,
    PrivilegeChecker,
    ensure_admin,
    is_admin,
    require_admin,
)
from source.service_adapter import WindowsServiceAdapter


class TestPrivilegeChecker(unittest.TestCase):
    def test_is_admin_true_windows(self) -> None:
        checker = PrivilegeChecker()
        with patch("sys.platform", "win32"), \
             patch("ctypes.windll.shell32.IsUserAnAdmin", return_value=1):
            self.assertTrue(checker.is_admin())

    def test_is_admin_false_windows(self) -> None:
        checker = PrivilegeChecker()
        with patch("sys.platform", "win32"), \
             patch("ctypes.windll.shell32.IsUserAnAdmin", return_value=0):
            self.assertFalse(checker.is_admin())

    def test_is_admin_handles_attribute_or_os_error(self) -> None:
        checker = PrivilegeChecker()
        with patch("sys.platform", "win32"), \
             patch("ctypes.windll.shell32.IsUserAnAdmin", side_effect=OSError("Access denied")):
            self.assertFalse(checker.is_admin())

    def test_ensure_admin_success(self) -> None:
        checker = PrivilegeChecker()
        with patch.object(checker, "is_admin", return_value=True):
            # Should not raise
            checker.ensure_admin("safe_action")

    def test_ensure_admin_raises_error(self) -> None:
        checker = PrivilegeChecker()
        with patch.object(checker, "is_admin", return_value=False):
            with self.assertRaises(AdministrativePrivilegesRequiredError) as ctx:
                checker.ensure_admin("stop services")
            self.assertIn("stop services", str(ctx.exception))
            self.assertIn("Run as Administrator", str(ctx.exception))


class TestRequireAdminDecorator(unittest.IsolatedAsyncioTestCase):
    def test_require_admin_sync_success(self) -> None:
        mock_checker = MagicMock(spec=PrivilegeChecker)
        mock_checker.is_admin.return_value = True

        @require_admin(action="sync_task", checker=mock_checker)
        def my_task(x: int) -> int:
            return x * 2

        self.assertEqual(my_task(5), 10)
        mock_checker.ensure_admin.assert_called_once_with("sync_task")

    def test_require_admin_sync_failure(self) -> None:
        mock_checker = MagicMock(spec=PrivilegeChecker)
        mock_checker.ensure_admin.side_effect = AdministrativePrivilegesRequiredError("sync_task")

        @require_admin(action="sync_task", checker=mock_checker)
        def my_task() -> str:
            return "should not run"

        with self.assertRaises(AdministrativePrivilegesRequiredError):
            my_task()

    async def test_require_admin_async_success(self) -> None:
        mock_checker = MagicMock(spec=PrivilegeChecker)
        mock_checker.is_admin.return_value = True

        @require_admin(action="async_task", checker=mock_checker)
        async def my_async_task(val: str) -> str:
            return f"hello {val}"

        result = await my_async_task("world")
        self.assertEqual(result, "hello world")
        mock_checker.ensure_admin.assert_called_once_with("async_task")

    async def test_require_admin_async_failure(self) -> None:
        mock_checker = MagicMock(spec=PrivilegeChecker)
        mock_checker.ensure_admin.side_effect = AdministrativePrivilegesRequiredError("async_task")

        @require_admin(action="async_task", checker=mock_checker)
        async def my_async_task() -> str:
            return "should not run"

        with self.assertRaises(AdministrativePrivilegesRequiredError):
            await my_async_task()


class TestServiceAdapterPrivilegeEnforcement(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.mock_checker = MagicMock(spec=PrivilegeChecker)
        self.mock_checker.ensure_admin.side_effect = AdministrativePrivilegesRequiredError("test action")
        self.adapter = WindowsServiceAdapter(
            privilege_checker=self.mock_checker,
            enforce_admin=True,
        )

    async def test_start_service_enforces_admin(self) -> None:
        with self.assertRaises(AdministrativePrivilegesRequiredError):
            await self.adapter.start_service("Spooler")

    async def test_stop_service_enforces_admin(self) -> None:
        with self.assertRaises(AdministrativePrivilegesRequiredError):
            await self.adapter.stop_service("Spooler")

    async def test_restart_service_enforces_admin(self) -> None:
        with self.assertRaises(AdministrativePrivilegesRequiredError):
            await self.adapter.restart_service("Spooler")


if __name__ == "__main__":
    unittest.main()
