"""Module for loading and validating Hoshu service configurations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Base exception for configuration-related errors."""


class ConfigFileNotFoundError(ConfigError):
    """Raised when the configuration file does not exist."""


class ConfigValidationError(ConfigError):
    """Raised when configuration content fails validation rules."""


@dataclass(frozen=True)
class ServiceConfig:
    """Represents a validated Windows service configuration."""

    id: str
    display_name: str
    service_name: str
    startup_type: str
    order: int


class ServicesConfigLoader:
    """Loads, validates, and provides access to services defined in configuration."""

    REQUIRED_FIELDS: tuple[str, ...] = (
        "id",
        "display_name",
        "service_name",
        "startup_type",
        "order",
    )

    VALID_STARTUP_TYPES: tuple[str, ...] = (
        "Automatic",
        "Manual",
        "Disabled",
        "Automatic (Delayed Start)",
    )

    def __init__(self) -> None:
        self._services: list[ServiceConfig] = []
        self._version: str = ""

    @property
    def version(self) -> str:
        """Returns the configuration version."""
        return self._version

    @property
    def services(self) -> list[ServiceConfig]:
        """Returns the loaded services list."""
        return list(self._services)

    def load_from_file(self, file_path: str | Path) -> list[ServiceConfig]:
        """Loads and validates service configuration from a JSON file.

        Args:
            file_path: Path to the JSON configuration file.

        Returns:
            List of validated ServiceConfig instances sorted by default order.

        Raises:
            ConfigFileNotFoundError: If the file does not exist.
            ConfigValidationError: If file is not valid JSON or violates schema.
        """
        path = Path(file_path)
        if not path.is_file():
            raise ConfigFileNotFoundError(f"Configuration file not found: {path}")

        try:
            with path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
        except json.JSONDecodeError as exc:
            raise ConfigValidationError(
                f"Configuration file has invalid JSON syntax: {exc}"
            ) from exc
        except OSError as exc:
            raise ConfigError(f"Failed to read configuration file: {exc}") from exc

        return self.load_from_dict(data)

    def load_from_dict(self, data: Any) -> list[ServiceConfig]:
        """Loads and validates service configuration from a dictionary.

        Args:
            data: Raw dictionary payload containing version and services.

        Returns:
            List of validated ServiceConfig instances.

        Raises:
            ConfigValidationError: If schema rules are violated.
        """
        if not isinstance(data, dict):
            raise ConfigValidationError(
                "Root configuration must be a JSON object (dictionary)."
            )

        version = data.get("version")
        if not version or not isinstance(version, str):
            raise ConfigValidationError(
                "Configuration must contain a non-empty string 'version' field."
            )
        self._version = version

        raw_services = data.get("services")
        if not isinstance(raw_services, list):
            raise ConfigValidationError(
                "Configuration 'services' field must be a list."
            )

        if not raw_services:
            raise ConfigValidationError(
                "Configuration 'services' list must not be empty."
            )

        seen_ids: set[str] = set()
        seen_service_names: set[str] = set()
        seen_orders: set[int] = set()
        validated_services: list[ServiceConfig] = []

        for index, item in enumerate(raw_services):
            service = self._validate_service_item(item, index)

            if service.id in seen_ids:
                raise ConfigValidationError(
                    f"Duplicate service id '{service.id}' found at index {index}."
                )
            if service.service_name in seen_service_names:
                raise ConfigValidationError(
                    f"Duplicate service_name '{service.service_name}' found at index {index}."
                )
            if service.order in seen_orders:
                raise ConfigValidationError(
                    f"Duplicate order '{service.order}' found at index {index} for service '{service.id}'."
                )

            seen_ids.add(service.id)
            seen_service_names.add(service.service_name)
            seen_orders.add(service.order)
            validated_services.append(service)

        # Default sort by order ascending
        self._services = sorted(validated_services, key=lambda s: s.order)
        return list(self._services)

    def _validate_service_item(self, item: Any, index: int) -> ServiceConfig:
        """Validates an individual service entry."""
        if not isinstance(item, dict):
            raise ConfigValidationError(
                f"Service item at index {index} must be a dictionary."
            )

        for field in self.REQUIRED_FIELDS:
            if field not in item:
                raise ConfigValidationError(
                    f"Missing required field '{field}' in service at index {index}."
                )

        service_id = item["id"]
        if not isinstance(service_id, str) or not service_id.strip():
            raise ConfigValidationError(
                f"Field 'id' at index {index} must be a non-empty string."
            )

        display_name = item["display_name"]
        if not isinstance(display_name, str) or not display_name.strip():
            raise ConfigValidationError(
                f"Field 'display_name' at index {index} must be a non-empty string."
            )

        service_name = item["service_name"]
        if not isinstance(service_name, str) or not service_name.strip():
            raise ConfigValidationError(
                f"Field 'service_name' at index {index} must be a non-empty string."
            )

        startup_type = item["startup_type"]
        if not isinstance(startup_type, str) or not startup_type.strip():
            raise ConfigValidationError(
                f"Field 'startup_type' at index {index} must be a non-empty string."
            )
        if startup_type not in self.VALID_STARTUP_TYPES:
            valid_types = ", ".join(self.VALID_STARTUP_TYPES)
            raise ConfigValidationError(
                f"Invalid startup_type '{startup_type}' at index {index}. Allowed: {valid_types}."
            )

        order = item["order"]
        if not isinstance(order, int) or isinstance(order, bool) or order <= 0:
            raise ConfigValidationError(
                f"Field 'order' at index {index} must be a positive integer greater than 0."
            )

        return ServiceConfig(
            id=service_id.strip(),
            display_name=display_name.strip(),
            service_name=service_name.strip(),
            startup_type=startup_type.strip(),
            order=order,
        )

    def get_services(self, order_ascending: bool = True) -> list[ServiceConfig]:
        """Returns the list of services sorted by execution order.

        Args:
            order_ascending: True for startup order (1, 2, ...),
                            False for shutdown/stop order (... , 2, 1) per RF01.
        """
        return sorted(self._services, key=lambda s: s.order, reverse=not order_ascending)

    def get_service_by_id(self, service_id: str) -> ServiceConfig | None:
        """Finds a service by its unique id."""
        for service in self._services:
            if service.id == service_id:
                return service
        return None

    def get_service_by_name(self, service_name: str) -> ServiceConfig | None:
        """Finds a service by its Windows service_name."""
        for service in self._services:
            if service.service_name == service_name:
                return service
        return None
