"""Инструменты, которые агент получает поверх песочницы.

Схемы описаны один раз в нейтральном виде и переводятся в формат конкретного
провайдера. Иначе сравнение моделей меряло бы разницу в формулировках схем,
а не разницу в моделях.
"""
from __future__ import annotations

from typing import Any

from sandbox.box import Box, BoxError

MAX_OUT = 8000  # столько символов вывода отдаём модели; хвост режем явной пометкой

SPECS: list[dict[str, Any]] = [
    {
        "name": "bash",
        "description": (
            "Выполнить команду в шелле песочницы. Рабочий каталог — /workspace. "
            "Доступны cat, ls, grep, sed, awk, sort, uniq, head, tail, wc, tr, cut, "
            "find, xargs, base64, md5sum, sha256sum, tar, gzip, git, jq. "
            "Интерпретаторов python и node нет, сети нет."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Команда целиком, одной строкой."}
            },
            "required": ["command"],
        },
    },
    {
        "name": "write_file",
        "description": "Записать текст в файл под /workspace, создав каталоги по пути.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Путь, например /workspace/answer.json"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "read_file",
        "description": "Прочитать файл под /workspace целиком.",
        "schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "done",
        "description": "Объявить задачу выполненной. Вызывать только когда результат уже на диске.",
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Что сделано, одной-двумя фразами."}
            },
            "required": ["summary"],
        },
    },
]

NAMES = [s["name"] for s in SPECS]


def anthropic_schema() -> list[dict]:
    return [
        {"name": s["name"], "description": s["description"], "input_schema": s["schema"]}
        for s in SPECS
    ]


def openai_schema() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["schema"],
            },
        }
        for s in SPECS
    ]


def _clip(text: str) -> str:
    if len(text) <= MAX_OUT:
        return text
    return text[:MAX_OUT] + f"\n…обрезано, всего {len(text)} символов"


def dispatch(box: Box, name: str, args: dict) -> str:
    """Выполнить вызов инструмента. Ошибки возвращаем текстом: агент должен их видеть."""
    try:
        if name == "bash":
            r = box.exec(str(args.get("command", "")))
            parts = []
            if r.stdout:
                parts.append(_clip(r.stdout))
            if r.stderr:
                parts.append("stderr:\n" + _clip(r.stderr))
            if r.exit_code != 0:
                parts.append(f"код возврата {r.exit_code}")
            return "\n".join(parts) or "(пустой вывод, код 0)"
        if name == "write_file":
            box.write(str(args["path"]), str(args.get("content", "")))
            return f"записано {args['path']}"
        if name == "read_file":
            return _clip(box.read(str(args["path"])))
        if name == "done":
            return "принято"
        return f"нет такого инструмента: {name}"
    except BoxError as e:
        return f"ошибка: {e}"
    except KeyError as e:
        return f"не хватает аргумента {e}"
