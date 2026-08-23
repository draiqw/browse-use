"""Совместимость со старыми скриптами полигона.

Логика переехала в пакет harness; здесь остался прежний интерфейс, чтобы
cbr_rates.py, run_task.py и заметки из README продолжали работать.
Для нового кода: from harness import run, Matrix, run_matrix.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Type, TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel

from harness.backends import BrowserUseBackend
from harness.models import make_model as make_llm  # noqa: F401 — старое имя
from harness.pricing import cost_of  # noqa: F401
from harness.profiles import EXTRACT_RULES as RULES, NOISY_ACTIONS, PROFILES  # noqa: F401
from harness.task import Task

load_dotenv()

T = TypeVar("T", bound=BaseModel)

COORD_PATTERNS = ("claude-sonnet-4", "claude-opus-4", "claude-fable-5", "gemini-3-pro", "browser-use/")
"""Список моделей, которым апстрим сам разрешает клики по координатам.
Актуальность проверяется в `python -m harness doctor`; профиль act-coords обходит его."""


@dataclass
class RunReport:
    model: str
    ok: bool = False
    attempts: int = 0
    steps: int = 0
    seconds: float = 0.0
    tokens: int = 0
    tok_in: int = 0
    tok_cached: int = 0
    tok_out: int = 0
    cost: float = 0.0
    errors: list = field(default_factory=list)
    data: BaseModel | None = None


async def extract(
    task: str,
    schema: Type[T],
    model: str = "gpt-5-mini",
    max_steps: int = 20,
    attempts: int = 2,
    headless: bool = True,
    lean: bool = True,
) -> RunReport:
    rep = RunReport(model=model)
    started = time.time()
    backend = BrowserUseBackend()
    profile = PROFILES["extract" if lean else "raw"]
    t = Task(name="ad-hoc", prompt=task, schema=schema, verify=lambda d: [], max_steps=max_steps)

    for attempt in range(1, attempts + 1):
        rep.attempts = attempt
        r = await backend.run(t, model, profile, max_steps=max_steps, headless=headless)
        rep.steps += r.steps
        rep.errors += r.errors
        rep.tok_in += r.tok_in
        rep.tok_cached += r.tok_cached
        rep.tok_out += r.tok_out
        rep.tokens = rep.tok_in + rep.tok_out
        rep.cost += r.cost or 0.0
        if r.ok:
            rep.ok, rep.data = True, r.data
            break

    rep.seconds = time.time() - started
    return rep


def print_report(rep: RunReport, extra: str = ""):
    print("\n=== ОТЧЁТ ===")
    print(f"модель  : {rep.model}")
    print(f"успех   : {rep.ok}  (попыток: {rep.attempts})")
    print(f"шагов   : {rep.steps}   время: {rep.seconds:.1f}s")
    print(f"токены  : {rep.tokens} (in {rep.tok_in} / cached {rep.tok_cached} / out {rep.tok_out})")
    real = cost_of(rep.model, rep.tok_in - rep.tok_cached, rep.tok_cached, rep.tok_out)
    print(f"цена    : ${real:.4f}" if real is not None else f"цена    : ${rep.cost:.4f} (по счётчику)")
    if rep.errors:
        print(f"ошибки  : {rep.errors[:5]}")
    if extra:
        print(extra)
