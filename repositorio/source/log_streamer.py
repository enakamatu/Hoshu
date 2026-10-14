"""Server-Sent Events (SSE) log streaming manager for Hoshu Cockpit."""

from __future__ import annotations

import datetime
import json
import queue
import threading
from typing import Generator


class LogStreamManager:
    """Pub/Sub manager for streaming log messages to web interface via SSE."""

    def __init__(self, max_history: int = 50) -> None:
        self._subscribers: set[queue.Queue[dict[str, str]]] = set()
        self._lock = threading.Lock()
        self._history: list[dict[str, str]] = []
        self._max_history = max_history

    def broadcast(
        self,
        message: str,
        level: str = "INFO",
        channel: str = "system",
    ) -> dict[str, str]:
        """Broadcasts a log message to all active subscribers.

        Args:
            message: Log text content.
            level: Log level (INFO, WARN, ERROR, SUCCESS).
            channel: Channel category (e.g. system, services, devops, patch).

        Returns:
            The created log record dictionary.
        """
        now = datetime.datetime.now()
        record = {
            "timestamp": now.strftime("%H:%M:%S"),
            "channel": channel,
            "level": level.upper(),
            "message": message,
        }

        with self._lock:
            self._history.append(record)
            if len(self._history) > self._max_history:
                self._history.pop(0)

            subscribers_snapshot = list(self._subscribers)

        for subscriber in subscribers_snapshot:
            try:
                subscriber.put_nowait(record)
            except queue.Full:
                # Subscriber queue full, drop or ignore
                pass

        return record

    def subscribe(self) -> queue.Queue[dict[str, str]]:
        """Subscribes a new client queue to log broadcasts."""
        subscriber_queue: queue.Queue[dict[str, str]] = queue.Queue(maxsize=100)
        with self._lock:
            # Replay recent history for initial context
            for historical_record in self._history[-10:]:
                subscriber_queue.put_nowait(historical_record)
            self._subscribers.add(subscriber_queue)
        return subscriber_queue

    def unsubscribe(self, subscriber_queue: queue.Queue[dict[str, str]]) -> None:
        """Removes a client queue from subscribers."""
        with self._lock:
            self._subscribers.discard(subscriber_queue)

    def get_history(self) -> list[dict[str, str]]:
        """Returns the cached recent log records."""
        with self._lock:
            return list(self._history)

    @staticmethod
    def format_sse(data: dict[str, str] | str, event: str | None = None) -> str:
        """Formats data into standard Server-Sent Events (SSE) string."""
        payload = json.dumps(data) if isinstance(data, dict) else str(data)
        lines = []
        if event:
            lines.append(f"event: {event}")
        lines.append(f"data: {payload}\n\n")
        return "\n".join(lines)

    def sse_generator(
        self,
        timeout: float = 1.0,
        heartbeat_interval: float = 15.0,
    ) -> Generator[str, None, None]:
        """Yields SSE-formatted messages for Flask streaming responses."""
        subscriber_queue = self.subscribe()
        last_heartbeat = datetime.datetime.now()

        try:
            # Initial connection event
            yield self.format_sse(
                {"message": "Conectado ao streaming de logs em tempo real."},
                event="connected",
            )

            while True:
                try:
                    record = subscriber_queue.get(timeout=timeout)
                    yield self.format_sse(record, event="log")
                except queue.Empty:
                    # Send heartbeat comment to keep connection alive
                    now = datetime.datetime.now()
                    if (now - last_heartbeat).total_seconds() >= heartbeat_interval:
                        last_heartbeat = now
                        yield ": heartbeat\n\n"
        finally:
            self.unsubscribe(subscriber_queue)
