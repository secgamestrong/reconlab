from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from .spec import LabSpec


def render_compose(spec: LabSpec, run_id: str, expires_at: datetime) -> str:
    labels = {
        "io.secgamestrong.reconlab.managed": "true",
        "io.secgamestrong.reconlab.name": spec.name,
        "io.secgamestrong.reconlab.run": run_id,
        "io.secgamestrong.reconlab.expires-at": expires_at.astimezone(timezone.utc).isoformat(),
    }
    services: dict[str, object] = {}
    for service in spec.services:
        definition: dict[str, object] = {
            "image": service.image,
            "init": True,
            "read_only": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "pids_limit": 128,
            "mem_limit": "256m",
            "cpus": "1.0",
            "tmpfs": ["/tmp:rw,noexec,nosuid,size=16m"],
            "networks": ["lab"],
            "labels": dict(labels),
        }
        if "nginx" in service.image.lower():
            definition["tmpfs"] = [
                "/tmp:rw,noexec,nosuid,size=16m",
                "/var/cache/nginx:rw,noexec,nosuid,size=32m",
                "/var/run:rw,noexec,nosuid,size=8m",
            ]
        if service.command:
            definition["command"] = list(service.command)
        if service.ports:
            definition["ports"] = [
                f"127.0.0.1:{port.host}:{port.container}/{port.protocol}" for port in service.ports
            ]
        services[service.name] = definition
    document = {
        "services": services,
        "networks": {"lab": {"driver": "bridge", "internal": True}},
    }
    return yaml.safe_dump(document, sort_keys=False, default_flow_style=False)


def write_compose(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
