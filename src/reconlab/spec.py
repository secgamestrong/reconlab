from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml

_NAME = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")
_PROTOCOLS = {"tcp", "udp"}
_ALLOWED_SERVICE_KEYS = {"image", "command", "ports"}
_ALLOWED_PORT_KEYS = {"host", "container", "protocol"}


@dataclass(frozen=True)
class PortBinding:
    host: int
    container: int
    protocol: str


@dataclass(frozen=True)
class Service:
    name: str
    image: str
    command: tuple[str, ...]
    ports: tuple[PortBinding, ...]


@dataclass(frozen=True)
class LabSpec:
    name: str
    services: tuple[Service, ...]


def load_spec(path: Path) -> LabSpec:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot read lab file {path}: {error}") from error
    if len(raw_text) > 256 * 1024:
        raise ValueError("lab file exceeds the 256 KiB limit")
    try:
        document = yaml.safe_load(raw_text)
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("lab definition must be a YAML mapping")
    if set(document) != {"apiVersion", "name", "services"}:
        raise ValueError("lab definition must contain only apiVersion, name, and services")
    if document["apiVersion"] != "reconlab/v1":
        raise ValueError("apiVersion must be reconlab/v1")
    name = document["name"]
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("name must be a lowercase slug with letters, digits, and hyphens")
    raw_services = document["services"]
    if not isinstance(raw_services, dict) or not 1 <= len(raw_services) <= 10:
        raise ValueError("services must contain between 1 and 10 entries")

    services: list[Service] = []
    for service_name, definition in sorted(raw_services.items()):
        if not isinstance(service_name, str) or not _NAME.fullmatch(service_name):
            raise ValueError(f"invalid service name: {service_name!r}")
        if not isinstance(definition, dict):
            raise ValueError(f"service {service_name} must be a mapping")
        unknown = set(definition) - _ALLOWED_SERVICE_KEYS
        if unknown:
            raise ValueError(f"service {service_name} has unsupported keys: {', '.join(sorted(unknown))}")
        image = definition.get("image")
        if not isinstance(image, str) or not _IMAGE.fullmatch(image):
            raise ValueError(f"service {service_name} requires a valid image reference")
        command = definition.get("command", [])
        if not isinstance(command, list) or any(not isinstance(part, str) or len(part) > 1024 for part in command):
            raise ValueError(f"service {service_name} command must be a list of strings up to 1024 characters")
        ports = definition.get("ports", [])
        if not isinstance(ports, list) or len(ports) > 20:
            raise ValueError(f"service {service_name} ports must be a list with at most 20 entries")
        bindings = tuple(_parse_port(service_name, item) for item in ports)
        services.append(Service(service_name, image, tuple(command), bindings))
    return LabSpec(name=name, services=tuple(services))


def _parse_port(service_name: str, value: Any) -> PortBinding:
    if not isinstance(value, dict) or set(value) - _ALLOWED_PORT_KEYS:
        raise ValueError(f"service {service_name} has an invalid port binding")
    host = value.get("host")
    container = value.get("container")
    protocol = value.get("protocol", "tcp")
    if isinstance(host, bool) or not isinstance(host, int) or not 1 <= host <= 65535:
        raise ValueError(f"service {service_name} host port must be 1 through 65535")
    if isinstance(container, bool) or not isinstance(container, int) or not 1 <= container <= 65535:
        raise ValueError(f"service {service_name} container port must be 1 through 65535")
    if protocol not in _PROTOCOLS:
        raise ValueError(f"service {service_name} protocol must be tcp or udp")
    return PortBinding(host, container, protocol)
