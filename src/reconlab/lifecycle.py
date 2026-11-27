from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from .compose import render_compose, write_compose
from .spec import LabSpec

_DURATION = re.compile(r"^([1-9][0-9]*)([smhd])$")
_MIN_TTL = 5 * 60
_MAX_TTL = 24 * 60 * 60


@dataclass
class RunState:
    schema_version: int
    lab_name: str
    project: str
    run_id: str
    compose_file: str
    created_at: str
    expires_at: str


def parse_ttl(value: str) -> timedelta:
    match = _DURATION.fullmatch(value)
    if match is None:
        raise ValueError("TTL must be an integer duration such as 30m, 4h, or 1d")
    amount, unit = int(match.group(1)), match.group(2)
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    if not _MIN_TTL <= seconds <= _MAX_TTL:
        raise ValueError("TTL must be between 5 minutes and 24 hours")
    return timedelta(seconds=seconds)


def state_root() -> Path:
    root = Path(os.environ.get("RECONLAB_HOME", Path.home() / ".reconlab")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def plan(spec: LabSpec, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    expires_at = now + ttl
    return render_compose(spec, run_id, expires_at)


def up(spec: LabSpec, ttl: timedelta) -> RunState:
    existing = find_state(spec.name)
    if existing is not None:
        raise ValueError(f"lab {spec.name} already has a managed run; use status, down, or sweep first")
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires = now + ttl
    run_dir = state_root() / "runs" / f"{spec.name}-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    compose_file = run_dir / "compose.yaml"
    write_compose(compose_file, render_compose(spec, run_id, expires))
    state = RunState(
        schema_version=1,
        lab_name=spec.name,
        project=f"reconlab-{spec.name}",
        run_id=run_id,
        compose_file=str(compose_file),
        created_at=now.isoformat(),
        expires_at=expires.isoformat(),
    )
    write_state(state)
    try:
        _compose(state, ["up", "-d", "--remove-orphans"])
    except ValueError:
        try:
            _compose(state, ["down", "--remove-orphans"])
        except ValueError:
            pass
        _remove_state(state)
        raise
    print(f"lab {spec.name} started; scheduled TTL metadata expires at {expires.isoformat()}")
    print("TTL cleanup runs when you invoke reconlab sweep; it is not a background daemon.")
    return state


def down(name: str) -> None:
    state = find_state(name)
    if state is None:
        raise ValueError(f"no managed lab named {name}")
    _compose(state, ["down", "--remove-orphans"])
    _remove_state(state)
    print(f"lab {name} stopped")


def status(name: str) -> None:
    state = find_state(name)
    if state is None:
        print(f"no managed lab named {name}")
        return
    print(f"lab: {state.lab_name}")
    print(f"project: {state.project}")
    print(f"expires at: {state.expires_at}")
    _compose(state, ["ps", "--all"])


def sweep() -> int:
    states_dir = state_root() / "runs"
    if not states_dir.exists():
        print("no managed labs")
        return 0
    now = datetime.now(timezone.utc)
    removed = 0
    for state_file in sorted(states_dir.glob("*/state.json")):
        try:
            state = _read_state(state_file)
        except ValueError as error:
            print(f"skip invalid state {state_file}: {error}", file=sys.stderr)
            continue
        if datetime.fromisoformat(state.expires_at) <= now:
            _compose(state, ["down", "--remove-orphans"])
            _remove_state(state)
            print(f"stopped expired lab {state.lab_name}")
            removed += 1
    print(f"sweep complete: {removed} expired lab(s) stopped")
    return removed


def find_state(name: str) -> RunState | None:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", name):
        raise ValueError("lab name must be a lowercase slug")
    states_dir = state_root() / "runs"
    if not states_dir.exists():
        return None
    matches = list(states_dir.glob(f"{name}-*/state.json"))
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"multiple managed runs found for {name}; inspect {states_dir}")
    return _read_state(matches[0])


def write_state(state: RunState) -> None:
    path = Path(state.compose_file).parent / "state.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_state(path: Path) -> RunState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        state = RunState(**raw)
    except (OSError, ValueError, TypeError) as error:
        raise ValueError(str(error)) from error
    if type(state.schema_version) is not int or state.schema_version != 1:
        raise ValueError("unsupported state schema version")
    if any(not isinstance(value, str) for value in (
        state.lab_name, state.project, state.run_id, state.compose_file,
        state.created_at, state.expires_at,
    )):
        raise ValueError("state fields must be strings")
    if not Path(state.compose_file).is_absolute():
        raise ValueError("compose path in state must be absolute")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", state.lab_name):
        raise ValueError("invalid lab name in state")
    if state.project != "reconlab-" + state.lab_name:
        raise ValueError("invalid Docker project in state")
    try:
        uuid.UUID(state.run_id)
    except ValueError as error:
        raise ValueError("invalid run id in state") from error
    runs_root = (state_root() / "runs").resolve()
    compose_path = Path(state.compose_file).resolve()
    state_path = path.resolve()
    if (compose_path.name != "compose.yaml" or compose_path.parent.parent != runs_root or
            state_path != compose_path.parent / "state.json" or
            compose_path.parent.name != state.lab_name + "-" + state.run_id):
        raise ValueError("state path is outside the ReconLab run directory")
    state.compose_file = str(compose_path)
    try:
        expires = datetime.fromisoformat(state.expires_at)
        created = datetime.fromisoformat(state.created_at)
    except (TypeError, ValueError) as error:
        raise ValueError("state timestamps must be ISO-8601 values") from error
    if expires.tzinfo is None or created.tzinfo is None:
        raise ValueError("state timestamps must include a timezone")
    return state


def _remove_state(state: RunState) -> None:
    run_dir = Path(state.compose_file).resolve().parent
    runs_root = (state_root() / "runs").resolve()
    if run_dir.parent != runs_root:
        raise ValueError("refusing to remove a path outside the ReconLab run directory")
    if run_dir.exists():
        shutil.rmtree(run_dir)


def _compose(state: RunState, arguments: list[str]) -> None:
    command = [
        "docker", "compose", "--project-name", state.project,
        "--file", state.compose_file, *arguments,
    ]
    try:
        result = subprocess.run(command, check=False, timeout=180)
    except FileNotFoundError as error:
        raise ValueError("Docker Compose was not found; install Docker Desktop or Docker Compose v2") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError("Docker Compose timed out; inspect the project with docker compose") from error
    if result.returncode != 0:
        raise ValueError(f"Docker Compose exited with status {result.returncode}")
