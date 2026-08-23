"""Прогон матрицы: задачи × модели × профили × повторы.

Повторы обязательны. Одиночный успешный прогон агента не значит ничего —
разброс между прогонами одной и той же пары доходил до 6 раз по шагам и деньгам.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from harness.backends import BACKENDS, RunReport
from harness.profiles import PROFILES
from harness.task import Task, get as get_task


@dataclass
class Matrix:
    tasks: list[str]
    models: list[str]
    profiles: list[str] = field(default_factory=lambda: [])
    backend: str = "browser-use"
    repeats: int = 1
    max_steps: int | None = None
    headless: bool = True
    verify: bool = True

    def cells(self) -> list[tuple[Task, str, str]]:
        out = []
        for tname in self.tasks:
            t = get_task(tname)
            profs = self.profiles or [t.profile]
            for m in self.models:
                for p in profs:
                    if p not in PROFILES:
                        raise KeyError(f"Нет профиля {p!r}. Есть: {', '.join(PROFILES)}")
                    out.append((t, m, p))
        return out


async def run_matrix(mx: Matrix, on_result=None) -> list[RunReport]:
    backend = BACKENDS[mx.backend]
    reports: list[RunReport] = []
    for task, model, prof in mx.cells():
        if task.setup:
            task.setup()
        for i in range(1, mx.repeats + 1):
            rep = await backend.run(
                task, model, PROFILES[prof],
                max_steps=mx.max_steps or task.max_steps,
                headless=mx.headless,
            )
            rep.attempts = i
            if rep.ok and mx.verify:
                try:
                    rep.problems = task.verify(rep.data)
                except Exception as exc:  # noqa: BLE001 — упавшая проверка это провал, а не успех
                    rep.problems = [f"проверка упала: {exc!r}"]
                rep.verified = not rep.problems
                if task.summary:
                    try:
                        rep.summary = task.summary(rep.data)
                    except Exception:  # noqa: BLE001
                        pass
            elif not rep.ok:
                rep.problems = ["агент не вернул данные по схеме"]
            reports.append(rep)
            if on_result:
                on_result(rep, i, mx.repeats)
    return reports


def save(reports: list[RunReport], path: str | Path, with_data: bool = False) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([r.as_dict(with_data) for r in reports],
                            ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def run(task: str, model: str, profile: str | None = None, **kw) -> RunReport:
    """Синхронный однократный прогон — для скриптов и ноутбуков."""
    t = get_task(task)
    mx = Matrix(tasks=[task], models=[model], profiles=[profile or t.profile], **kw)
    return asyncio.run(run_matrix(mx))[0]
