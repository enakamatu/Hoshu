"""Unit tests for source/services_config.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from source.services_config import (
    ConfigFileNotFoundError,
    ConfigValidationError,
    ServicesConfigLoader,
)


class TestServicesConfigLoader(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = ServicesConfigLoader()
        self.repo_root = Path(__file__).resolve().parent.parent
        self.default_config_path = self.repo_root / "config" / "services.json"

    def test_load_default_services_json(self) -> None:
        """Tests that the repository's default config/services.json loads successfully."""
        services = self.loader.load_from_file(self.default_config_path)

        self.assertEqual(len(services), 5)
        self.assertEqual(self.loader.version, "1.0")

        # Verify sorted by order ascending
        orders = [s.order for s in services]
        self.assertEqual(orders, [1, 2, 3, 4, 5])

        # Verify first service
        first = services[0]
        self.assertEqual(first.id, ".01_TOTVS|LicenseVirtual")
        self.assertEqual(first.startup_type, "Automatic")
        self.assertEqual(first.order, 1)

    def test_shutdown_order_is_reversed(self) -> None:
        """RF01: A ordem de parada deve ser inversa a ordem de subida."""
        self.loader.load_from_file(self.default_config_path)

        start_order = [s.order for s in self.loader.get_services(order_ascending=True)]
        stop_order = [s.order for s in self.loader.get_services(order_ascending=False)]

        self.assertEqual(start_order, [1, 2, 3, 4, 5])
        self.assertEqual(stop_order, [5, 4, 3, 2, 1])

    def test_get_service_by_id_and_name(self) -> None:
        self.loader.load_from_file(self.default_config_path)

        svc = self.loader.get_service_by_id(".02_TOTVS|DBAccess")
        self.assertIsNotNone(svc)
        self.assertEqual(svc.order, 2)

        svc_name = self.loader.get_service_by_name(".03_TOTVS|Broker_Master")
        self.assertIsNotNone(svc_name)
        self.assertEqual(svc_name.order, 3)

        self.assertIsNone(self.loader.get_service_by_id("non_existent"))
        self.assertIsNone(self.loader.get_service_by_name("non_existent"))

    def test_file_not_found(self) -> None:
        with self.assertRaises(ConfigFileNotFoundError):
            self.loader.load_from_file(Path("non_existent_path.json"))

    def test_invalid_json_syntax(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            tf.write("{ invalid json")
            tf_path = Path(tf.name)

        try:
            with self.assertRaises(ConfigValidationError):
                self.loader.load_from_file(tf_path)
        finally:
            tf_path.unlink(missing_ok=True)

    def test_missing_version(self) -> None:
        payload = {
            "services": [
                {
                    "id": "svc1",
                    "display_name": "Service 1",
                    "service_name": "Service1",
                    "startup_type": "Automatic",
                    "order": 1,
                }
            ]
        }
        with self.assertRaises(ConfigValidationError) as ctx:
            self.loader.load_from_dict(payload)
        self.assertIn("version", str(ctx.exception))

    def test_empty_services_list(self) -> None:
        payload = {"version": "1.0", "services": []}
        with self.assertRaises(ConfigValidationError) as ctx:
            self.loader.load_from_dict(payload)
        self.assertIn("must not be empty", str(ctx.exception))

    def test_duplicate_id(self) -> None:
        payload = {
            "version": "1.0",
            "services": [
                {
                    "id": "dup",
                    "display_name": "S1",
                    "service_name": "S1",
                    "startup_type": "Automatic",
                    "order": 1,
                },
                {
                    "id": "dup",
                    "display_name": "S2",
                    "service_name": "S2",
                    "startup_type": "Automatic",
                    "order": 2,
                },
            ],
        }
        with self.assertRaises(ConfigValidationError) as ctx:
            self.loader.load_from_dict(payload)
        self.assertIn("Duplicate service id", str(ctx.exception))

    def test_duplicate_order(self) -> None:
        payload = {
            "version": "1.0",
            "services": [
                {
                    "id": "s1",
                    "display_name": "S1",
                    "service_name": "S1",
                    "startup_type": "Automatic",
                    "order": 1,
                },
                {
                    "id": "s2",
                    "display_name": "S2",
                    "service_name": "S2",
                    "startup_type": "Automatic",
                    "order": 1,
                },
            ],
        }
        with self.assertRaises(ConfigValidationError) as ctx:
            self.loader.load_from_dict(payload)
        self.assertIn("Duplicate order", str(ctx.exception))

    def test_invalid_startup_type(self) -> None:
        payload = {
            "version": "1.0",
            "services": [
                {
                    "id": "s1",
                    "display_name": "S1",
                    "service_name": "S1",
                    "startup_type": "InvalidType",
                    "order": 1,
                }
            ],
        }
        with self.assertRaises(ConfigValidationError) as ctx:
            self.loader.load_from_dict(payload)
        self.assertIn("Invalid startup_type", str(ctx.exception))

    def test_order_must_be_positive_integer(self) -> None:
        payload = {
            "version": "1.0",
            "services": [
                {
                    "id": "s1",
                    "display_name": "S1",
                    "service_name": "S1",
                    "startup_type": "Automatic",
                    "order": 0,
                }
            ],
        }
        with self.assertRaises(ConfigValidationError) as ctx:
            self.loader.load_from_dict(payload)
        self.assertIn("positive integer", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
