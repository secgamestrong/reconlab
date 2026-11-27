# ReconLab

ReconLab reads a small YAML lab definition and creates a locked-down Docker Compose project for local practice. It binds declared ports to 127.0.0.1, uses an internal Docker network, drops Linux capabilities, sets containers read-only, disables privilege escalation, and applies process and memory limits.

This public implementation is local Docker only. It does not provision cloud infrastructure with Terraform, capture packets, install Sysmon or auditd, or run a background TTL daemon. The expiration time is recorded in local state; run reconlab sweep to stop expired labs.

## Requirements

- Python 3.11+
- Docker Engine with Docker Compose v2

## Install

    python -m venv .venv
    # Windows: .venv\Scripts\activate
    # macOS/Linux: source .venv/bin/activate
    python -m pip install -e .

## Validate, inspect, and start

    reconlab validate examples/web-lab.yaml
    reconlab plan examples/web-lab.yaml --ttl 4h
    reconlab up examples/web-lab.yaml --ttl 4h
    reconlab status demo-web
    reconlab down demo-web
    reconlab sweep

Planning and validation only read local files. The up command may pull the images named in the YAML from their configured container registry and starts containers. Review image sources and pin production or sensitive lab images by digest.

## Lab definition

    apiVersion: reconlab/v1
    name: demo-web
    services:
      web:
        image: nginx:1.27
        ports:
          - host: 8080
            container: 80
            protocol: tcp

Only image, command, and loopback-published port bindings are accepted. Host mounts, host networking, privileged mode, environment variables, capabilities, and arbitrary Compose overrides are intentionally not accepted by this schema.

## Data handling and limitations

- Generated state and Compose projects are stored under ~/.reconlab by default. Set RECONLAB_HOME to choose another local directory.
- Compose projects use an internal network to prevent normal external routing from lab containers. This is a useful boundary, not a complete sandbox against a compromised Docker host or kernel.
- Port mappings are bound to loopback only.
- No host directories are mounted into containers.
- TTL metadata is enforced only when reconlab sweep is run. It does not run on a timer.
- Stopping a lab does not delete named volumes, though this implementation does not define any.

No license is included. Public visibility does not grant permission to reuse or redistribute this code.
