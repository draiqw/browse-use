"""Проверки без LLM и без денег: то, что должно работать всегда.

Отвечает на вопрос «я сломал харнесс своей правкой или нет» за пару секунд,
не тратя ни одного токена.
"""
from __future__ import annotations

from harness.upstream import Check


def t_model_factory() -> Check:
    """Фабрика моделей ставит лимит ответа туда, где он у провайдера называется по-своему,
    и не подсовывает классу параметров, которых у него нет."""
    from harness.models import make_model

    o = make_model("openai:gpt-5-mini", max_output_tokens=32000)
    ok_openai = getattr(o, "max_completion_tokens", None) == 32000 and o.temperature == 0.0
    l = make_model("ollama:qwen3:8b", max_output_tokens=32000)  # у ChatOllama нет ни того, ни другого
    ok_ollama = l.model == "qwen3:8b" and not hasattr(l, "temperature")
    return Check("фабрика моделей", ok_openai and ok_ollama,
                 f"openai лимит={getattr(o, 'max_completion_tokens', None)}, ollama создан без лишних полей")


def t_profiles() -> Check:
    """Профили собирают разные наборы действий, координаты включаются только там, где заявлено."""
    from harness.profiles import PROFILES

    rows, bad = [], []
    for name, p in PROFILES.items():
        tools = p.build_tools()
        acts = set(tools.registry.registry.actions)
        coord = bool(getattr(tools, "_coordinate_clicking_enabled", False))
        if coord != p.coordinates:
            bad.append(f"{name}: координаты {coord} != {p.coordinates}")
        if p.coordinates and "coordinate_x" not in tools.registry.registry.actions["click"].param_model.model_fields:
            bad.append(f"{name}: координаты включены, но у click нет coordinate_x")
        if name in ("act", "act-coords") and "evaluate" in acts:
            bad.append(f"{name}: evaluate должен быть выключен")
        rows.append(f"{name}={len(acts)}")
    return Check("профили", not bad, "; ".join(bad) if bad else "действий: " + ", ".join(rows))


def t_tasks() -> Check:
    """У каждой задачи есть схема и проверка, и проверка ловит заведомо неверные данные."""
    from harness.task import all_tasks

    bad = []
    for name, t in all_tasks().items():
        if not t.schema or not callable(t.verify):
            bad.append(f"{name}: нет схемы или проверки")
    # проверка обязана ругаться на подделку
    from tasks.clickgate import Gate, verify

    if not verify(Gate(code="GATE-0000", enabled=["Депозит"])):
        bad.append("clickgate: проверка пропустила неверный код")
    if verify(Gate(code="GATE-8190", enabled=["Специальный счёт 40802", "Депозит"])):
        bad.append("clickgate: проверка забраковала верный ответ")
    return Check("задачи", not bad, "; ".join(bad) if bad else f"{len(all_tasks())} задач, проверки различают верное и неверное")


def t_fixture() -> Check:
    """Офлайновая фикстура генерируется и отдаётся по http."""
    import urllib.request

    from tasks.clickgate import setup

    url = setup()
    body = urllib.request.urlopen(url, timeout=5).read().decode()
    ok = "opacity:0" in body.replace(" ", "") and body.count("type=\"checkbox\"") == 4
    return Check("фикстура clickgate", ok, f"{url}, {len(body)} байт, 4 скрытых чекбокса")


def t_pricing() -> Check:
    """Цена считается по реестру и отличает известную модель от неизвестной."""
    from harness.pricing import cost_of

    known = cost_of("gpt-5-mini", 1_000_000, 0, 0)
    unknown = cost_of("несуществующая-модель-xyz", 1000, 0, 100)
    ok = known and known > 0 and unknown is None
    return Check("подсчёт цены", bool(ok), f"gpt-5-mini 1M входных = ${known:.4f}, неизвестная = {unknown}")


def t_report() -> Check:
    """Отчёт собирается из пустого и из заполненного прогона, не падая."""
    from harness.backends import RunReport
    from harness.report import line, table

    r = RunReport(task="t", model="m", profile="p", backend="b", ok=True, verified=True,
                  steps=3, seconds=10.0, tok_in=100, tok_out=50, cost=0.01)
    ok = "OK" in line(r) and "сошлось" in table([r])
    return Check("отчёты", ok, "строка и таблица собираются")


CHECKS = [t_model_factory, t_profiles, t_tasks, t_fixture, t_pricing, t_report]


def run_all() -> list[Check]:
    out = []
    for fn in CHECKS:
        try:
            out.append(fn())
        except Exception as exc:  # noqa: BLE001
            out.append(Check(fn.__name__, False, f"упало: {exc!r}"))
    return out
