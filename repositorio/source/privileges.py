"""Administrative privileges validation module adhering to TRD security standards."""

from __future__ import annotations

import ctypes
import functools
import inspect
import os
import sys
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class PrivilegeError(Exception):
    """Base exception for privilege-related issues."""


class AdministrativePrivilegesRequiredError(PrivilegeError):
    """Raised when an operation requiring Windows Administrator privileges is attempted without elevation."""

    def __init__(self, action: str = "this operation") -> None:
        self.action = action
        message = (
            f"Administrative privileges are required to perform {action}. "
            f"Please run Hoshu from an elevated shell (Run as Administrator)."
        )
        super().__init__(message)


class PrivilegeChecker:
    """Checks and enforces process privilege levels."""

    def is_admin(self) -> bool:
        """Determines if the current process is running with administrative privileges.

        Returns:
            True if running elevated (Admin/root), False otherwise.
        """
        if sys.platform == "win32":
            try:
                return bool(ctypes.windll.shell32.IsUserAnAdmin())
            except (AttributeError, OSError):
                return False
        else:
            # POSIX fallback
            try:
                return os.geteuid() == 0  # type: ignore[attr-defined]
            except AttributeError:
                return False

    def ensure_admin(self, action: str = "this operation") -> None:
        """Enforces that the current process has administrative privileges.

        Args:
            action: Description of the privileged action being attempted.

        Raises:
            AdministrativePrivilegesRequiredError: If not running as Administrator.
        """
        if not self.is_admin():
            raise AdministrativePrivilegesRequiredError(action)


_default_checker = PrivilegeChecker()


def is_admin() -> bool:
    """Convenience function to check administrative status using default checker."""
    return _default_checker.is_admin()


def ensure_admin(action: str = "this operation") -> None:
    """Convenience function to enforce administrative privileges using default checker."""
    _default_checker.ensure_admin(action)


def require_admin(
    action: str | None = None,
    checker: PrivilegeChecker | None = None,
) -> Callable[[F], F]:
    """Decorator for functions/methods that strictly require administrative privileges.

    Works seamlessly on both synchronous and asynchronous functions.

    Args:
        action: Optional description of the action (defaults to function name).
        checker: Optional PrivilegeChecker instance (defaults to global checker).
    """

    def decorator(func: F) -> F:
        active_checker = checker or _default_checker
        action_name = action or f"'{func.__name__}'"

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                active_checker.ensure_admin(action_name)
                return await func(*args, **kwargs)

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            active_checker.ensure_admin(action_name)
            return func(*args, **kwargs)

        return sync_wrapper  # type: ignore[return-value]

    return decorator
