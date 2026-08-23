"""Проверка допущений об апстриме.

Харнесс опирается на несколько внутренних деталей browser-use. Если апстрим их
поменяет, наш код должен сломаться громко и в одном понятном месте, а не тихо и
посреди прогона. `python -m harness doctor` проверяет всё это за пару секунд.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def pkg_dir() -> Path:
    import browser_use

    return Path(browser_use.__file__).resolve().parent


def version() -> str:
    from importlib.metadata import version as v

    return v("browser-use")


def _read(rel: str) -> str:
    return (pkg_dir() / rel).read_text(encoding="utf-8", errors="replace")


def check_integrity() -> Check:
    """Никто не правил установленный пакет руками — все файлы совпадают с хешами из RECORD."""
    dist = pkg_dir().parent / f"browser_use-{version()}.dist-info" / "RECORD"
    if not dist.exists():
        return Check("целостность пакета", False, f"нет {dist}")
    root, bad, missing, total = dist.parent.parent, [], 0, 0
    for row in csv.reader(dist.open()):
        if len(row) < 3 or not row[1].startswith("sha256="):
            continue
        f = root / row[0]
        total += 1
        if not f.exists():
            missing += 1
            continue
        h = base64.urlsafe_b64encode(hashlib.sha256(f.read_bytes()).digest()).rstrip(b"=").decode()
        if h != row[1][7:]:
            bad.append(row[0])
    ok = not bad and not missing
    return Check("целостность пакета", ok,
                 f"{total} файлов, изменено {len(bad)}, отсутствует {missing}"
                 + (f" → {bad[:3]}" if bad else ""))


def check_coordinate_api() -> Check:
    """Мы включаем клики по координатам сами, минуя зашитый в апстрим список моделей."""
    from browser_use import Tools

    if not hasattr(Tools, "set_coordinate_clicking"):
        return Check("API координатных кликов", False,
                     "у Tools больше нет set_coordinate_clicking — смотри harness/capabilities.py")
    t = Tools()
    t.set_coordinate_clicking(True)
    on = getattr(t, "_coordinate_clicking_enabled", None)
    return Check("API координатных кликов", on is True, f"флаг после включения: {on}")


def check_coordinate_allowlist() -> Check:
    """Апстрим сам включает координаты только избранным моделям. Нам важно знать состав списка:
    если модель в нём есть, наш форсинг ничего не меняет; если нет — меняет всё."""
    src = _read("agent/service.py")
    m = re.search(r"supports_coordinate_clicking\s*=\s*any\((.*?)\)\s*\n", src, re.S)
    if not m:
        return Check("список моделей апстрима", False,
                     "не нашёл блок supports_coordinate_clicking — апстрим переписал логику")
    pats = re.findall(r"'([^']+)'", m.group(1))
    return Check("список моделей апстрима", bool(pats), f"{len(pats)} шаблонов: {', '.join(pats)}")


def check_tools_before_action_model() -> Check:
    """Включать координаты нужно ДО конструктора Agent: он строит схему действий позже,
    на строке _setup_action_models. Если апстрим поменяет порядок, включение потеряется."""
    src = _read("agent/service.py")
    i_tools = src.find("set_coordinate_clicking")
    i_setup = src.find("self._setup_action_models()")
    ok = -1 < i_tools < i_setup
    return Check("порядок сборки Agent", ok,
                 f"set_coordinate_clicking@{i_tools} < _setup_action_models@{i_setup}")


def check_structured_output() -> Check:
    """Весь контракт харнесса стоит на history.structured_output."""
    from browser_use.agent.views import AgentHistoryList

    ok = "structured_output" in dir(AgentHistoryList)
    return Check("structured_output у истории", ok, "есть" if ok else "поля больше нет")


def check_index_is_backend_node_id() -> Check:
    """Индекс элемента, по которому кликает агент, — это backendNodeId из CDP.
    Отсюда следует его нестабильность между загрузками страницы; на этом стоит вся
    архитектура 'читает агент, кликает скрипт'."""
    src = _read("dom/serializer/serializer.py")
    ok = "_allocate_selector_index" in src and "backend_node_id" in src
    return Check("индекс = backendNodeId", ok,
                 "подтверждено в dom/serializer/serializer.py" if ok else "разметка индексов изменилась")


def check_visibility_filter() -> Check:
    """Элементы с opacity:0 не попадают в карту — из-за этого агент не видит кастомные
    чекбоксы и тогглы. Проверено эмпирически в index_probe.py."""
    src = _read("dom/serializer/serializer.py") + _read("dom/views.py")
    ok = "opacity" in src
    return Check("фильтр видимости по opacity", ok,
                 "фильтр на месте" if ok else "упоминаний opacity нет — поведение могло измениться")


CHECKS = [
    check_integrity,
    check_coordinate_api,
    check_coordinate_allowlist,
    check_tools_before_action_model,
    check_structured_output,
    check_index_is_backend_node_id,
    check_visibility_filter,
]


def run_all() -> list[Check]:
    out = []
    for fn in CHECKS:
        try:
            out.append(fn())
        except Exception as exc:  # noqa: BLE001
            out.append(Check(fn.__name__, False, f"проверка упала: {exc!r}"))
    return out
