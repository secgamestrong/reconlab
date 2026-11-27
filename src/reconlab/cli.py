from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .compose import write_compose
from .lifecycle import down, parse_ttl, plan, status, sweep, up
from .spec import load_spec


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="reconlab", description="Plan and manage local isolated Docker labs")
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a lab definition")
    validate.add_argument("file", type=Path)
    plan_command = commands.add_parser("plan", help="render an isolated Docker Compose plan without starting it")
    plan_command.add_argument("file", type=Path)
    plan_command.add_argument("--ttl", default="4h")
    plan_command.add_argument("--out", type=Path)
    start = commands.add_parser("up", help="start a lab with an explicit local TTL")
    start.add_argument("file", type=Path)
    start.add_argument("--ttl", required=True)
    stop = commands.add_parser("down", help="stop and remove a managed lab")
    stop.add_argument("name")
    inspect = commands.add_parser("status", help="show the state of a managed lab")
    inspect.add_argument("name")
    commands.add_parser("sweep", help="stop expired managed labs")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "validate":
            spec = load_spec(args.file)
            print(f"valid lab {spec.name}: {len(spec.services)} service(s)")
        elif args.command == "plan":
            spec = load_spec(args.file)
            rendered = plan(spec, parse_ttl(args.ttl))
            if args.out is None:
                sys.stdout.write(rendered)
            else:
                write_compose(args.out, rendered)
                print(f"wrote plan to {args.out}")
        elif args.command == "up":
            up(load_spec(args.file), parse_ttl(args.ttl))
        elif args.command == "down":
            down(args.name)
        elif args.command == "status":
            status(args.name)
        elif args.command == "sweep":
            sweep()
        return 0
    except (OSError, ValueError) as error:
        print(f"reconlab: {error}", file=sys.stderr)
        return 2
