"""Цикл «модель ↔ инструменты» для двух семейств API.

Провайдеров два не из любви к дублированию, а потому что форматы tool-use у
Anthropic и OpenAI несовместимы, а прослойка вроде litellm добавила бы к замеру
свой слой поведения. Всё, что может быть общим — системный промпт, схемы
инструментов, лимит шагов, учёт токенов — общее.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from sandbox import tools
from sandbox.box import Box

SYSTEM = (
    "Ты работаешь в изолированной песочнице. Рабочий каталог — /workspace.\n"
    "У тебя есть шелл с обычным текстовым инструментарием (cat, grep, awk, sed, "
    "sort, uniq, cut, find, wc, jq и т.п.), но нет ни python, ни node, ни сети.\n"
    "Считай сам, а не на глаз: если нужна сумма или отбор — сделай это командой.\n"
    "Когда результат записан на диск в том виде, который просили, вызови done."
)


@dataclass
class Trace:
    steps: int = 0
    calls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    tok_in: int = 0
    tok_cached: int = 0
    tok_out: int = 0
    seconds: float = 0.0
    summary: str = ""
    stopped: str = ""  # почему цикл кончился: done | max_steps | no_tool_call


def run(model: str, provider: str, box: Box, prompt: str, max_steps: int = 30) -> Trace:
    if provider == "anthropic":
        return _anthropic(model, box, prompt, max_steps)
    if provider in ("openai", "compat"):
        return _openai(model, box, prompt, max_steps)
    raise ValueError(f"провайдер {provider} в песочнице пока не поддержан")


def _anthropic(model: str, box: Box, prompt: str, max_steps: int) -> Trace:
    from anthropic import Anthropic

    client = Anthropic()
    tr = Trace()
    started = time.time()
    messages: list[dict] = [{"role": "user", "content": prompt}]
    schema = tools.anthropic_schema()

    while tr.steps < max_steps:
        tr.steps += 1
        resp = client.messages.create(
            model=model,
            max_tokens=8000,
            system=SYSTEM,
            tools=schema,
            messages=messages,
        )
        u = resp.usage
        tr.tok_in += getattr(u, "input_tokens", 0) or 0
        tr.tok_cached += getattr(u, "cache_read_input_tokens", 0) or 0
        tr.tok_out += getattr(u, "output_tokens", 0) or 0

        calls = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        messages.append({"role": "assistant", "content": resp.content})
        if not calls:
            tr.stopped = "no_tool_call"
            tr.summary = "".join(
                getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
            ).strip()
            break

        results = []
        finished = False
        for c in calls:
            args = dict(c.input or {})
            tr.calls.append(_label(c.name, args))
            out = tools.dispatch(box, c.name, args)
            if out.startswith("ошибка:"):
                tr.errors.append(out)
            results.append({"type": "tool_result", "tool_use_id": c.id, "content": out})
            if c.name == "done":
                tr.summary = str(args.get("summary", ""))
                finished = True
        messages.append({"role": "user", "content": results})
        if finished:
            tr.stopped = "done"
            break
    else:
        tr.stopped = "max_steps"

    tr.seconds = time.time() - started
    return tr


def _openai(model: str, box: Box, prompt: str, max_steps: int) -> Trace:
    from openai import OpenAI

    client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None)
    tr = Trace()
    started = time.time()
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ]
    schema = tools.openai_schema()

    while tr.steps < max_steps:
        tr.steps += 1
        resp = client.chat.completions.create(
            model=model, tools=schema, messages=messages
        )
        u = resp.usage
        if u:
            cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            tr.tok_in += (u.prompt_tokens or 0) - cached
            tr.tok_cached += cached
            tr.tok_out += u.completion_tokens or 0

        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        calls = msg.tool_calls or []
        if not calls:
            tr.stopped = "no_tool_call"
            tr.summary = (msg.content or "").strip()
            break

        finished = False
        for c in calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tr.calls.append(_label(c.function.name, args))
            out = tools.dispatch(box, c.function.name, args)
            if out.startswith("ошибка:"):
                tr.errors.append(out)
            messages.append({"role": "tool", "tool_call_id": c.id, "content": out})
            if c.function.name == "done":
                tr.summary = str(args.get("summary", ""))
                finished = True
        if finished:
            tr.stopped = "done"
            break
    else:
        tr.stopped = "max_steps"

    tr.seconds = time.time() - started
    return tr


def _label(name: str, args: dict) -> str:
    if name == "bash":
        cmd = str(args.get("command", "")).replace("\n", " ")
        return f"bash: {cmd[:120]}"
    if name in ("write_file", "read_file"):
        return f"{name}: {args.get('path', '')}"
    return name
