"""Задача = что сделать + какая схема на выходе + чем проверить результат.

Проверка обязательна. Без неё «агент что-то вернул» и «агент вернул правду» —
неразличимые события, а на деньгах это недопустимо.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel


@dataclass(frozen=True)
class Task:
    name: str
    prompt: str
    schema: type[BaseModel]
    verify: Callable[[BaseModel], list[str]]
    """Возвращает список нарушений. Пустой список = результат сошёлся с эталоном."""
    profile: str = "extract"
    max_steps: int = 20
    summary: Callable[[BaseModel], str] | None = None
    setup: Callable[[], None] | None = None
    """Подготовка перед прогоном: поднять локальный сервер, сгенерировать фикстуру."""
    needs_network: bool = True
    note: str = ""


_REGISTRY: dict[str, Task] = {}


def register(task: Task) -> Task:
    _REGISTRY[task.name] = task
    return task


def all_tasks() -> dict[str, Task]:
    if not _REGISTRY:
        import tasks  # noqa: F401  — импорт наполняет реестр
    return _REGISTRY


def get(name: str) -> Task:
    t = all_tasks().get(name)
    if not t:
        raise KeyError(f"Нет задачи {name!r}. Есть: {', '.join(sorted(all_tasks()))}")
    return t
