"""Прогон задачи в песочнице и отчёт в том же формате, что у браузерного харнесса."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field

from harness.models import missing_key, parse_spec
from harness.pricing import cost_of, is_free
from sandbox import agent
from sandbox.box import Box, Server
from sandbox.tasks import TASKS, Task


@dataclass
class SandboxReport:
    task: str
    model: str
    backend: str = "cfcomputer"
    verified: bool = False
    problems: list[str] = field(default_factory=list)
    stopped: str = ""
    steps: int = 0
    seconds: float = 0.0
    tok_in: int = 0
    tok_cached: int = 0
    tok_out: int = 0
    cost: float | None = None
    calls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    summary: str = ""

    def as_dict(self) -> dict:
        d = asdict(self)
        d["tokens"] = self.tok_in + self.tok_cached + self.tok_out
        return d


def run_once(spec: str, task: Task, port: int | None = None, max_steps: int | None = None) -> SandboxReport:
    provider, model = parse_spec(spec)
    need = missing_key(provider)
    if need:
        raise RuntimeError(f"Провайдер {provider}: нет {need}. Положи в .env рядом с проектом.")

    box = Box(f"{task.name}-{uuid.uuid4().hex[:8]}", port=port)
    started = time.time()
    box.reset()
    task.seed(box)

    tr = agent.run(model, provider, box, task.prompt, max_steps or task.max_steps)
    verified, problems = task.verify(box)

    cost = None if is_free(model) else cost_of(model, tr.tok_in, tr.tok_cached, tr.tok_out)
    return SandboxReport(
        task=task.name,
        model=spec,
        verified=verified,
        problems=problems,
        stopped=tr.stopped,
        steps=tr.steps,
        seconds=round(time.time() - started, 1),
        tok_in=tr.tok_in,
        tok_cached=tr.tok_cached,
        tok_out=tr.tok_out,
        cost=cost,
        calls=tr.calls,
        errors=tr.errors,
        summary=tr.summary,
    )


def run_matrix(specs: list[str], names: list[str], repeats: int = 1,
               port: int | None = None, on_result=None) -> list[SandboxReport]:
    out: list[SandboxReport] = []
    srv = Server(port=port)
    with srv:
        for name in names:
            task = TASKS[name]
            for spec in specs:
                for _ in range(repeats):
                    try:
                        r = run_once(spec, task, port=srv.port)
                    except Exception as e:
                        r = SandboxReport(task=name, model=spec, problems=[f"{type(e).__name__}: {e}"])
                    out.append(r)
                    if on_result:
                        on_result(r)
    return out
