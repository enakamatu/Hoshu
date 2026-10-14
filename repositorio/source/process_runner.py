"""Asynchronous process execution utility adhering to Hoshu TRD architecture."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Sequence


class ProcessExecutionError(Exception):
    """Raised when an external process terminates with a non-zero exit code."""

    def __init__(
        self,
        command: Sequence[str],
        exit_code: int,
        stdout: str,
        stderr: str,
    ) -> None:
        self.command = list(command)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        cmd_str = " ".join(command)
        message = (
            f"Command '{cmd_str}' failed with exit code {exit_code}.\n"
            f"STDOUT:\n{stdout}\n"
            f"STDERR:\n{stderr}"
        )
        super().__init__(message)


@dataclass(frozen=True)
class ProcessResult:
    """Encapsulates output and exit code from an external process."""

    command: list[str]
    exit_code: int
    stdout: str
    stderr: str


class AsyncProcessRunner:
    """Asynchronous process runner capturing separated stdout and stderr buffers."""

    async def run(
        self,
        command: Sequence[str],
        cwd: str | os.PathLike[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
        check: bool = True,
    ) -> ProcessResult:
        """Executes an external command asynchronously.

        Args:
            command: Sequence of command arguments.
            cwd: Working directory for process execution.
            env: Optional environment variables dictionary.
            timeout: Maximum execution time in seconds.
            check: If True, raises ProcessExecutionError when exit_code != 0.

        Returns:
            ProcessResult with exit code, stdout, and stderr.

        Raises:
            ProcessExecutionError: If check=True and exit code is non-zero.
            TimeoutError: If execution exceeds specified timeout.
        """
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        try:
            if timeout is not None:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            else:
                stdout_bytes, stderr_bytes = await process.communicate()
        except asyncio.TimeoutError as exc:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()
            cmd_str = " ".join(command)
            raise TimeoutError(
                f"Command '{cmd_str}' timed out after {timeout} seconds."
            ) from exc

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        exit_code = process.returncode if process.returncode is not None else -1

        result = ProcessResult(
            command=list(command),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )

        if check and exit_code != 0:
            raise ProcessExecutionError(
                command=command,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            )

        return result
