"""Профиль агента — это способ вести браузер, независимый от модели.

Одна и та же модель в разных профилях ведёт себя по-разному, и сравнивать надо
именно пары (модель, профиль). Профиль собирает Tools и параметры Agent; сам
апстрим не трогаем.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Агент по своей инициативе лез писать файлы, снимать PDF и жать кнопки — лишние
# шаги и деньги. Для чистого извлечения оставляем только навигацию, чтение и done.
NOISY_ACTIONS = [
    "write_file", "read_file", "replace_file", "save_as_pdf", "upload_file",
    "screenshot", "evaluate", "close", "search",
]

# Правила компенсируют слабость мелких моделей: они ошибаются в селекторах и не
# восстанавливаются после ошибки инструмента.
EXTRACT_RULES = """
ПРАВИЛА ИЗВЛЕЧЕНИЯ ДАННЫХ:
1. Для получения текста и таблиц предпочитай extract_structured_data — не ковыряй DOM селекторами.
2. Если используешь CSS-селектор и получил ошибку "Invalid CSS selector" — это твоя ошибка,
   исправь её и повтори НЕМЕДЛЕННО. Частая причина: id начинается с цифры,
   тогда пиши [id="123"], а не #123.
3. Любая ошибка инструмента — не повод завершать задачу. Меняй подход и продолжай.
4. Не завершай задачу частичным результатом с оговорками. Либо полные данные по схеме,
   либо продолжай работать до исчерпания шагов.
5. Не кликай ничего, кроме навигации, если в задаче не сказано иначе.
"""

# Для профилей, которые меряют работу с интерфейсом, JS-исполнение должно быть закрыто.
UI_ONLY = ("write_file", "read_file", "replace_file", "save_as_pdf", "upload_file", "evaluate")

# Для профилей, которые меряют работу с интерфейсом, JS-исполнение должно быть закрыто.
UI_ONLY = ("write_file", "read_file", "replace_file", "save_as_pdf", "upload_file", "evaluate")

ACT_RULES = """
ПРАВИЛА ДЕЙСТВИЙ НА СТРАНИЦЕ:
1. Индексы элементов пересчитываются после каждой перезагрузки страницы. Никогда не
   используй индекс, полученный до перехода или перезагрузки — сначала посмотри состояние заново.
2. Если действие вернуло "Element index N not available", это не конец задачи:
   перечитай страницу и найди элемент заново.
3. Элементы с opacity:0 в списке не появятся. Если нужного чекбокса или тоггла в списке нет,
   кликай по видимой подписи или обёртке, а не ищи невидимый элемент.
4. После каждого действия проверяй, изменилось ли состояние страницы так, как ты ожидал.
"""


@dataclass(frozen=True)
class Profile:
    name: str
    lean: bool = True                    # выкинуть шумные действия
    coordinates: bool = False            # клики по координатам вне зависимости от списка апстрима
    vision: bool | str = "auto"
    flash: bool = False                  # без размышлений: быстрее и дешевле, точность ниже
    rules: str = EXTRACT_RULES
    max_failures: int = 5
    exclude: tuple[str, ...] = ()
    note: str = ""

    def build_tools(self):
        from browser_use import Tools

        excluded = list(self.exclude) + (NOISY_ACTIONS if self.lean else [])
        tools = Tools(exclude_actions=sorted(set(excluded))) if excluded else Tools()
        if self.coordinates:
            # Апстрим включает это только пяти избранным моделям (agent/service.py).
            # Мы включаем явно и любой модели — проверено doctor'ом, что API на месте.
            tools.set_coordinate_clicking(True)
        return tools

    def agent_kwargs(self) -> dict:
        kw = {
            "extend_system_message": self.rules,
            "max_failures": self.max_failures,
            "flash_mode": self.flash,
        }
        if self.vision != "auto":
            kw["use_vision"] = self.vision
        return kw


PROFILES: dict[str, Profile] = {p.name: p for p in [
    Profile("extract", note="только чтение: навигация, extract_structured_data, done"),
    Profile("extract-flash", flash=True,
            note="то же самое без размышлений — дешевле и быстрее, но глупее"),
    # evaluate выключен намеренно: с ним модель решает задачу скриптом, минуя интерфейс,
    # и профиль перестаёт мерить то, ради чего заведён. Замечено на первом же прогоне.
    Profile("act", lean=False, rules=ACT_RULES, exclude=UI_ONLY,
            note="манипуляции на странице по индексам элементов, без обхода через JS"),
    Profile("act-coords", lean=False, rules=ACT_RULES, coordinates=True, vision=True,
            exclude=UI_ONLY,
            note="клики по координатам принудительно, любой модели"),
    Profile("act-js", lean=False, rules=ACT_RULES,
            exclude=("write_file", "read_file", "replace_file", "save_as_pdf", "upload_file"),
            note="то же, но с evaluate: быстрее и надёжнее, но интерфейс не проверяется"),
    Profile("raw", lean=False, rules="", note="ванильный browser-use без наших правил — база для сравнения"),
]}
