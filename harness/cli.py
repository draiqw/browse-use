"""Командная строка харнесса.

    python -m harness doctor                  проверить допущения об апстриме
    python -m harness models                  какие провайдеры готовы к работе
    python -m harness tasks                   список задач и профилей
    python -m harness run -t cbr -m openai:gpt-5-mini -r 3
    python -m harness run -t clickgate -m openai:gpt-5-mini -p act -p act-coords
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()


def cmd_doctor(args) -> int:
    from harness.upstream import run_all, version

    print(f"browser-use {version()}")
    bad = 0
    for c in run_all():
        print(("  OK    " if c.ok else "  СЛОМ  ") + f"{c.name:30} {c.detail}")
        bad += not c.ok
    if bad:
        print(f"\nСломано допущений: {bad}. Смотри harness/upstream.py — там написано, "
              f"на что именно мы опирались и что чинить.")
    return 1 if bad else 0


def cmd_models(args) -> int:
    from harness.models import PROVIDERS, available

    for name, ok, note in available():
        print(f"  {'готов' if ok else '  —  '}  {name:12} {note}")
    print("\nСпецификация модели: провайдер:модель, например openai:gpt-5-mini, "
          "anthropic:claude-haiku-4-5-20251001, ollama:qwen3:8b")
    return 0


def cmd_tasks(args) -> int:
    from harness.profiles import PROFILES
    from harness.task import all_tasks

    print("ЗАДАЧИ")
    for name, t in sorted(all_tasks().items()):
        net = "сеть" if t.needs_network else "офлайн"
        print(f"  {name:12} профиль={t.profile:12} шагов<={t.max_steps:<3} [{net}] {t.note}")
    print("\nПРОФИЛИ")
    for name, p in PROFILES.items():
        flags = []
        if p.coordinates:
            flags.append("координаты")
        if p.flash:
            flags.append("без размышлений")
        if p.lean:
            flags.append("урезанный набор действий")
        print(f"  {name:14} {', '.join(flags) or 'полный набор':38} {p.note}")
    return 0


def cmd_run(args) -> int:
    from harness import report as rep_mod
    from harness.runner import Matrix, run_matrix, save

    mx = Matrix(
        tasks=args.task, models=args.model, profiles=args.profile or [],
        backend=args.backend, repeats=args.repeats, max_steps=args.max_steps,
        headless=not args.headed, verify=not args.no_verify,
    )
    cells = mx.cells()
    print(f"Матрица: {len(cells)} пар × {args.repeats} повтор(ов) = {len(cells) * args.repeats} прогонов\n")

    def show(r, i, total):
        print(rep_mod.line(r) + (f"   [повтор {i}/{total}]" if total > 1 else ""))

    reports = asyncio.run(run_matrix(mx, on_result=show))

    print("\n" + rep_mod.table(reports))
    if args.md:
        print("\n" + rep_mod.markdown(reports))
    if args.out:
        print(f"\nсохранено: {save(reports, args.out, with_data=args.with_data)}")

    good = sum(1 for r in reports if r.verified)
    print(f"\nсошлось {good}/{len(reports)} прогонов")
    return 0 if good == len(reports) else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="harness", description="Харнесс поверх browser-use")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="проверить допущения об апстриме").set_defaults(fn=cmd_doctor)
    sub.add_parser("models", help="доступные провайдеры").set_defaults(fn=cmd_models)
    sub.add_parser("tasks", help="задачи и профили").set_defaults(fn=cmd_tasks)

    r = sub.add_parser("run", help="прогнать матрицу задача × модель × профиль")
    r.add_argument("-t", "--task", action="append", required=True)
    r.add_argument("-m", "--model", action="append", required=True)
    r.add_argument("-p", "--profile", action="append", help="по умолчанию профиль задачи")
    r.add_argument("-r", "--repeats", type=int, default=1)
    r.add_argument("--max-steps", type=int, default=None)
    r.add_argument("--backend", default="browser-use")
    r.add_argument("--out", default="", help="куда сложить JSON с прогонами")
    r.add_argument("--with-data", action="store_true", help="класть в JSON и сами извлечённые данные")
    r.add_argument("--md", action="store_true", help="ещё и markdown-таблица")
    r.add_argument("--headed", action="store_true", help="показывать браузер")
    r.add_argument("--no-verify", action="store_true")
    r.set_defaults(fn=cmd_run)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
