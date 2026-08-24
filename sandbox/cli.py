"""python -m sandbox <команда>"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from sandbox.box import WORKER_DIR, Box, BoxError, Server
from sandbox.tasks import TASKS

RUNS = Path(__file__).resolve().parent.parent / "runs"


def _money(v):
    return "—" if v is None else f"${v:.4f}"


def cmd_doctor(args) -> int:
    ok = True

    def line(name, good, note=""):
        nonlocal ok
        ok = ok and good
        print(f"{'да ' if good else 'НЕТ'}  {name}{'  — ' + note if note else ''}")

    line("node", shutil.which("node") is not None)
    line("npx", shutil.which("npx") is not None)
    line("зависимости воркера", (WORKER_DIR / "node_modules").exists(),
         f"иначе: cd {WORKER_DIR} && npm install")
    if not ok:
        return 1

    srv = Server(port=args.port)
    try:
        srv.start()
    except BoxError as e:
        line("wrangler dev", False, str(e))
        return 1
    try:
        line("песочница", True, "переиспользована" if srv.reused else "поднята с нуля")
        box = Box("doctor", port=srv.port)
        box.reset()
        box.write("/workspace/probe.txt", "one\ntwo\nthree\n")
        r = box.exec("wc -l < probe.txt")
        line("shell + файловая система", r.ok and r.stdout.strip() == "3", r.stdout.strip() or r.stderr.strip())
        r = box.exec("printf '1\\n2\\n3\\n' | awk '{s+=$1} END {print s}'")
        line("awk", r.ok and r.stdout.strip() == "6", r.stdout.strip() or r.stderr.strip())
        r = box.exec("echo '{\"a\":[1,2,3]}' | jq -c .a")
        line("jq", r.ok and r.stdout.strip() == "[1,2,3]", r.stdout.strip() or r.stderr.strip())
        r = box.exec("curl -s https://example.com")
        line("сеть закрыта", not r.ok, "как и задумано")
        box.reset()
    finally:
        srv.stop()
    return 0 if ok else 1


def cmd_tasks(args) -> int:
    for name, t in TASKS.items():
        print(f"{name:8} шагов до {t.max_steps}")
        if t.truth:
            print(f"         правильный ответ: {json.dumps(t.truth(), ensure_ascii=False)}")
        print(f"         {t.prompt.splitlines()[0]}")
    return 0


def cmd_run(args) -> int:
    from sandbox.runner import run_matrix

    names = args.tasks or list(TASKS)
    bad = [n for n in names if n not in TASKS]
    if bad:
        print(f"нет таких задач: {bad}. Есть: {list(TASKS)}", file=sys.stderr)
        return 2

    results = []

    def show(r):
        results.append(r)
        mark = "ok " if r.verified else "нет"
        print(
            f"{mark} {r.task:8} {r.model:32} шагов {r.steps:3}  "
            f"{r.seconds:6.1f}с  {_money(r.cost)}  {r.stopped}",
            flush=True,
        )
        for p in r.problems[:4]:
            print(f"       {p}", flush=True)

    run_matrix(args.models, names, repeats=args.repeats, port=args.port, on_result=show)

    good = sum(1 for r in results if r.verified)
    total_cost = sum(r.cost or 0 for r in results)
    print(f"\nсошлось {good} из {len(results)}, всего {_money(total_cost)}")

    if args.save:
        RUNS.mkdir(exist_ok=True)
        path = RUNS / args.save
        path.write_text(json.dumps([r.as_dict() for r in results], ensure_ascii=False, indent=2))
        print(f"отчёт: {path}")
    return 0 if good == len(results) and results else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sandbox", description="Харнесс поверх Cloudflare Computer")
    ap.add_argument("--port", type=int, default=None, help="порт wrangler dev")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="проверить, что песочница вообще работает")
    d.set_defaults(func=cmd_doctor)

    t = sub.add_parser("tasks", help="какие есть задачи и какой у них правильный ответ")
    t.set_defaults(func=cmd_tasks)

    r = sub.add_parser("run", help="прогнать модели по задачам")
    r.add_argument("-m", "--models", nargs="+", required=True)
    r.add_argument("-t", "--tasks", nargs="*")
    r.add_argument("-n", "--repeats", type=int, default=1)
    r.add_argument("--save", default=None, help="имя файла отчёта в runs/")
    r.set_defaults(func=cmd_run)

    args = ap.parse_args(argv)
    return args.func(args)
