"""Command line entry point: ``python -m pipeline <command> [--offline]``."""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from collector.run import collect_github
from pipeline.config import ConfigError, load_settings
from pipeline.context import open_context
from pipeline.stages import analyze_pending

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("skillscope")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pipeline", description="Skillscope pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect", help="discover and snapshot repositories from GitHub")
    collect.add_argument("--offline", action="store_true", help="use data/samples instead of APIs")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings(os.environ, offline=args.offline, root=ROOT)
    except ConfigError as exc:
        print(f"Configuración inválida: {exc}", file=sys.stderr)
        return 2

    ctx = open_context(settings)
    try:
        if args.command == "collect":
            result = collect_github(
                ctx.settings, ctx.clock, ctx.http, ctx.state, ctx.snapshots, ROOT, ctx.catalog
            )
            analyzed = analyze_pending(ctx.snapshots, ctx.catalog, ctx.state, ctx.clock.now())
            ctx.state.save()
            report = result.report.to_dict() | {"analysis": asdict(analyzed)}
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if result.report.status != "failed" else 1
    finally:
        ctx.close()
    return 0
