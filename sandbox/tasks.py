"""Задачи для песочницы.

Правило то же, что и в браузерном харнессе: у задачи должна быть проверка,
которая не зависит от того, что агент про себя рассказал. Здесь это просто —
фикстуры генерируются детерминированно, поэтому правильный ответ считается
на нашей стороне из тех же данных.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Callable

from sandbox.box import Box

ANSWER = "/workspace/answer.json"


@dataclass
class Task:
    name: str
    prompt: str
    seed: Callable[[Box], None]
    verify: Callable[[Box], tuple[bool, list[str]]]
    max_steps: int = 30
    truth: Callable[[], object] | None = None


# ---------------------------------------------------------------- ledger

CATEGORIES = ["продукты", "транспорт", "аренда", "связь", "развлечения"]
_MONTHS = ["2026-05", "2026-06", "2026-07"]


def _ledger_rows() -> list[dict]:
    """Выписка. Генератор детерминированный, иначе проверку нельзя было бы посчитать заранее."""
    rng = random.Random(20260824)
    rows = []
    for i in range(240):
        rows.append(
            {
                "id": f"T{i:04d}",
                "date": f"{rng.choice(_MONTHS)}-{rng.randint(1, 28):02d}",
                "category": rng.choice(CATEGORIES),
                "amount": round(rng.uniform(120, 9000), 2),
                "status": rng.choices(["posted", "pending", "declined"], [8, 1, 1])[0],
            }
        )
    return rows


def _ledger_truth() -> dict[str, float]:
    totals: dict[str, float] = {}
    for r in _ledger_rows():
        if r["date"].startswith("2026-07") and r["status"] == "posted":
            totals[r["category"]] = round(totals.get(r["category"], 0.0) + r["amount"], 2)
    return {k: round(v, 2) for k, v in sorted(totals.items())}


def _ledger_seed(box: Box) -> None:
    rows = _ledger_rows()
    head = "id,date,category,amount,status"
    body = "\n".join(
        f"{r['id']},{r['date']},{r['category']},{r['amount']:.2f},{r['status']}" for r in rows
    )
    box.write("/workspace/data/tx.csv", f"{head}\n{body}\n")
    # Приманка: прошлогодняя выписка в том же каталоге и с тем же форматом.
    old = "\n".join(
        f"O{i:04d},2025-07-{(i % 28) + 1:02d},{CATEGORIES[i % 5]},{1000 + i}.00,posted"
        for i in range(60)
    )
    box.write("/workspace/data/tx_2025.csv", f"{head}\n{old}\n")
    box.write(
        "/workspace/README.txt",
        "Выписки лежат в data/. Суммы в рублях. Статусы: posted, pending, declined.\n",
    )


LEDGER_PROMPT = f"""В /workspace/data лежат выписки по счёту.

Посчитай сумму трат по каждой категории за июль 2026 года, учитывая только
операции со статусом posted. Операции с другими статусами и из других месяцев
не считаются. В каталоге есть и посторонние файлы — смотри на даты.

Запиши результат в {ANSWER} — плоский JSON-объект вида
{{"категория": сумма, ...}}, сумма — число с двумя знаками после запятой.
Никаких других ключей в объекте быть не должно."""


def _ledger_verify(box: Box) -> tuple[bool, list[str]]:
    want = _ledger_truth()
    try:
        got = json.loads(box.read(ANSWER))
    except Exception as e:
        return False, [f"{ANSWER} не читается или не JSON: {e}"]
    if not isinstance(got, dict):
        return False, [f"ожидался объект, получен {type(got).__name__}"]

    problems = []
    extra = set(got) - set(want)
    missing = set(want) - set(got)
    if extra:
        problems.append(f"лишние категории: {sorted(extra)}")
    if missing:
        problems.append(f"нет категорий: {sorted(missing)}")
    for k in sorted(set(got) & set(want)):
        try:
            v = float(got[k])
        except (TypeError, ValueError):
            problems.append(f"{k}: не число ({got[k]!r})")
            continue
        if abs(v - want[k]) > 0.01:
            problems.append(f"{k}: {v:.2f}, а надо {want[k]:.2f}")
    return not problems, problems


# ---------------------------------------------------------------- needle

_NEEDLE = "TOKEN-4C7A19E3"


def _needle_seed(box: Box) -> None:
    rng = random.Random(777)
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
    files: dict[str, list[str]] = {}
    for i in range(60):
        d = f"/workspace/vault/{rng.choice(words)}/{rng.choice(words)}"
        files.setdefault(f"{d}/note{i:02d}.txt", []).append(
            "\n".join(rng.choice(words) for _ in range(rng.randint(5, 40)))
        )
    paths = sorted(files)
    # Приманки: похожи на ключ, но формат другой — восемь шестнадцатеричных знаков после TOKEN-.
    decoys = ["TOKEN-XYZ", "TOKEN-4C7A19E", "token-4c7a19e3", "TOKEN_4C7A19E3", "TOKEN-4C7A19E31"]
    for path, decoy in zip(paths[:5], decoys):
        files[path].append(decoy)
    files[paths[37]].append(_NEEDLE)
    for path, chunks in files.items():
        box.write(path, "\n".join(chunks) + "\n")


NEEDLE_PROMPT = """В /workspace/vault лежит дерево текстовых файлов.

Ровно в одном из них спрятан ключ вида TOKEN-XXXXXXXX, где X — заглавная
шестнадцатеричная цифра (0-9 или A-F), ровно восемь штук. Похожие строки,
не подходящие под этот формат, — приманки.

Найди ключ и запиши в /workspace/answer.json объект {"token": "TOKEN-..."}."""


def _needle_verify(box: Box) -> tuple[bool, list[str]]:
    try:
        got = json.loads(box.read(ANSWER))
    except Exception as e:
        return False, [f"{ANSWER} не читается или не JSON: {e}"]
    if not isinstance(got, dict) or "token" not in got:
        return False, ["в ответе нет ключа token"]
    if str(got["token"]).strip() != _NEEDLE:
        return False, [f"ключ {got['token']!r}, а надо {_NEEDLE!r}"]
    return True, []


TASKS: dict[str, Task] = {
    "ledger": Task("ledger", LEDGER_PROMPT, _ledger_seed, _ledger_verify, 30, _ledger_truth),
    "needle": Task("needle", NEEDLE_PROMPT, _needle_seed, _needle_verify, 20, lambda: _NEEDLE),
}
