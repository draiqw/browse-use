"""Бэкенд — то, чем крутится задача. Сейчас один, browser-use.

Слой существует ради того, чтобы добавить второй (Stagehand, свой цикл на CDP,
облачный агент) не переписывая ни задачи, ни отчёты.
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from typing import Protocol

from pydantic import BaseModel

from harness.models import make_model, parse_spec
from harness.pricing import cost_of, is_free
from harness.profiles import PROFILES, Profile
from harness.task import Task

# Апстрим по умолчанию шлёт анонимную телеметрию. Для работы с финансовыми
# страницами это лишнее — выключаем, если пользователь явно не включил обратно.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")


@dataclass
class RunReport:
    task: str
    model: str
    profile: str
    backend: str
    ok: bool = False              # агент вернул данные по схеме
    verified: bool = False        # данные прошли проверку
    problems: list[str] = field(default_factory=list)
    attempts: int = 0
    steps: int = 0
    seconds: float = 0.0
    tok_in: int = 0
    tok_cached: int = 0
    tok_out: int = 0
    cost: float | None = None
    actions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    summary: str = ""
    data: BaseModel | None = None

    @property
    def tokens(self) -> int:
        return self.tok_in + self.tok_out

    def as_dict(self, with_data: bool = True) -> dict:
        d = asdict(self)
        d.pop("data", None)
        d["tokens"] = self.tokens
        if with_data and self.data is not None:
            d["data"] = self.data.model_dump(mode="json")
        return d


class Backend(Protocol):
    name: str

    async def run(self, task: Task, model: str, profile: Profile,
                  max_steps: int, headless: bool) -> RunReport: ...


class BrowserUseBackend:
    name = "browser-use"

    async def run(self, task: Task, model: str, profile: Profile,
                  max_steps: int, headless: bool = True) -> RunReport:
        from browser_use import Agent, Browser

        rep = RunReport(task=task.name, model=model, profile=profile.name, backend=self.name)
        started = time.time()
        browser = Browser(headless=headless)
        try:
            agent = Agent(
                task=task.prompt,
                llm=make_model(model),
                browser=browser,
                output_model_schema=task.schema,
                tools=profile.build_tools(),
                **profile.agent_kwargs(),
            )
            history = await agent.run(max_steps=max_steps)
            rep.steps = history.number_of_steps()
            rep.actions = [a for a in history.action_names() if a]
            rep.errors = [str(e) for e in history.errors() if e]
            if history.usage:
                u = history.usage
                rep.tok_in, rep.tok_cached = u.total_prompt_tokens, u.total_prompt_cached_tokens
                rep.tok_out = u.total_completion_tokens
            rep.data = history.structured_output
            rep.ok = rep.data is not None
        except Exception as exc:  # noqa: BLE001
            rep.errors.append(repr(exc))
        finally:
            await browser.kill()

        rep.seconds = time.time() - started
        _, bare = parse_spec(model)
        rep.cost = 0.0 if is_free(model) else cost_of(bare, rep.tok_in - rep.tok_cached,
                                                      rep.tok_cached, rep.tok_out)
        return rep


BACKENDS: dict[str, Backend] = {b.name: b for b in [BrowserUseBackend()]}
