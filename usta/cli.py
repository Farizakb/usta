"""Usta command line (SPEC §14). Same composition root as the API."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from usta.app.config import Settings
from usta.app.wiring import App, build_app
from usta.core.errors import UstaError
from usta.core.events import Event
from usta.core.run import RunState, StopReason

AppFactory = Callable[..., Awaitable[App]]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="usta", description="Usta work agent")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a task as $USTA_USER")
    run.add_argument("task")
    answer = sub.add_parser("answer", help="answer a run parked on its budget")
    answer.add_argument("run_id")
    answer.add_argument("decision", choices=["yes", "no"])
    cancel = sub.add_parser("cancel", help="cancel a run")
    cancel.add_argument("run_id")
    sub.add_parser("recover", help="resume runs a crash left running or queued")
    user = sub.add_parser("user", help="add or update a user")
    user.add_argument("user_id")
    user.add_argument("--name")
    user.add_argument("--scope", action="append", default=[])
    return p


def format_event(ev: Event) -> str:
    d = ev.data
    match ev.type:
        case "run_started":
            return f"▶ run {ev.run_id}"
        case "model_call":
            return f"[turn {d['turn']}] {d['model']} · {d['stop']} · ${d['cost_usd']:.4f}"
        case "tool_call":
            return f"  → {d['name']} {json.dumps(d['input'], ensure_ascii=False)}"
        case "tool_result":
            status = "error" if d["is_error"] else "ok"
            return f"  ← {d['name']}: {status} ({d['chars']} chars)"
        case "todo_updated":
            return "  ☐ " + " | ".join(f"[{i['status']}] {i['content']}" for i in d["items"])
        case "step_done":
            return f"  · ${d['cost_usd']:.4f} so far"
        case "parked":
            question = (d.get("question") or {}).get("text", "")
            return f"⏸ {d['status']}: {question}  (usta answer {ev.run_id} yes|no)"
        case "finished":
            detail = f": {d['detail']}" if d.get("detail") else ""
            return f"■ {d['stop_reason']}{detail} · {d['turns']} turns · ${d['cost_usd']:.4f}"
    return f"{ev.type} {json.dumps(d, ensure_ascii=False)}"


async def _print_event(ev: Event) -> None:
    print(format_event(ev), flush=True)


def _exit_code(run: RunState) -> int:
    if run.is_parked:
        return 3
    if run.is_finished and run.stop_reason != StopReason.DONE:
        return 1
    if run.is_finished:
        print("\n" + run.final_text())
    return 0


async def _main(args: argparse.Namespace, settings: Settings, app_factory: AppFactory) -> int:
    if args.command == "run" and not settings.user:
        raise UstaError("set USTA_USER to the user id that runs tasks (see `usta user`)")
    app = await app_factory(settings, on_event=_print_event)
    try:
        match args.command:
            case "user":
                await app.store.add_user(args.user_id, args.name or args.user_id, args.scope)
                print(f"user {args.user_id} saved")
                return 0
            case "recover":
                ids = await app.worker.recover()
                print(f"recovered {len(ids)} run(s)")
                return 0
            case "run":
                run = await app.worker.submit(settings.user, args.task)
                run = await app.worker.execute(run.id)
            case "answer":
                run = await app.worker.answer_budget(args.run_id, args.decision == "yes")
            case "cancel":
                was_finished = (await app.store.load(args.run_id)).is_finished
                run = await app.worker.cancel(args.run_id)
                if was_finished:
                    return _exit_code(run)
                if run.is_finished and run.stop_reason == StopReason.CANCELLED:
                    print("cancelled")
                    return 0
                if (
                    not run.is_finished
                ):  # running: only the flag is set; the loop stops at its next step
                    print("cancel requested")
                    return 0
                return _exit_code(run)
            case _:
                raise UstaError(f"unknown command {args.command}")
        return _exit_code(run)
    finally:
        await app.aclose()


def main(argv: list[str] | None = None, *, app_factory: AppFactory = build_app) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings()
        return asyncio.run(_main(args, settings, app_factory))
    except (UstaError, ValidationError, ValueError, KeyError) as e:  # e.g. unknown run id
        print(f"usta: {e}", file=sys.stderr)
        return 2
