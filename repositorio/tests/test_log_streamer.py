"""Unit tests for LogStreamManager and SSE streaming in source/log_streamer.py."""

from __future__ import annotations

import json
import unittest

from source.app import create_app
from source.log_streamer import LogStreamManager


class TestLogStreamManager(unittest.TestCase):
    def setUp(self) -> None:
        self.streamer = LogStreamManager(max_history=5)

    def test_broadcast_and_history(self) -> None:
        rec = self.streamer.broadcast("Test message 1", level="INFO", channel="system")
        self.assertEqual(rec["message"], "Test message 1")
        self.assertEqual(rec["level"], "INFO")
        self.assertEqual(rec["channel"], "system")
        self.assertIn("timestamp", rec)

        history = self.streamer.get_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["message"], "Test message 1")

    def test_history_limit(self) -> None:
        for i in range(10):
            self.streamer.broadcast(f"Msg {i}")

        history = self.streamer.get_history()
        self.assertEqual(len(history), 5)
        self.assertEqual(history[-1]["message"], "Msg 9")

    def test_subscribe_receives_broadcasts(self) -> None:
        q = self.streamer.subscribe()
        self.streamer.broadcast("Broadcasted to subscriber")

        item = q.get(timeout=1.0)
        self.assertEqual(item["message"], "Broadcasted to subscriber")
        self.streamer.unsubscribe(q)

    def test_unsubscribe(self) -> None:
        q = self.streamer.subscribe()
        self.streamer.unsubscribe(q)
        self.streamer.broadcast("After unsubscribe")

        self.assertTrue(q.empty())

    def test_format_sse(self) -> None:
        formatted = LogStreamManager.format_sse({"foo": "bar"}, event="test_event")
        self.assertIn("event: test_event\n", formatted)
        self.assertIn('data: {"foo": "bar"}\n\n', formatted)

    def test_sse_generator_initial_event(self) -> None:
        gen = self.streamer.sse_generator(timeout=0.01)
        first_event = next(gen)
        self.assertIn("event: connected", first_event)
        self.assertIn("Conectado ao streaming", first_event)


class TestAppSSEEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.streamer = LogStreamManager()
        self.app = create_app(log_streamer=self.streamer)
        self.client = self.app.test_client()

    def test_get_logs_history(self) -> None:
        self.streamer.broadcast("History check message", level="SUCCESS", channel="devops")
        response = self.client.get("/api/logs/history")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("logs", data)
        messages = [entry["message"] for entry in data["logs"]]
        self.assertIn("History check message", messages)

    def test_stream_logs_headers(self) -> None:
        response = self.client.get("/api/logs/stream")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/event-stream")
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache")


if __name__ == "__main__":
    unittest.main()
