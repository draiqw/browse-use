"""Типизированное извлечение данных со страницы через browser-use.

Контракт: на выходе либо провалидированный объект схемы, либо исключение.
Никаких "я не смог, но вот текстом" — это и убивало прошлый прогон.
"""
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Type, TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel
from browser_use import Agent, Browser, ChatAnthropic, ChatOpenAI, ChatGoogle, Tools

load_dotenv()

T = TypeVar("T", bound=BaseModel)

COORD_PATTERNS = ("claude-sonnet-4", "claude-opus-4", "claude-fable-5", "gemini-3-pro", "browser-use/")

# Правила, компенсирующие слабость мелких моделей: они ошибаются в селекторах
# и не восстанавливаются после ошибки инструмента.
# Агент по своей инициативе лез писать файлы и жать на кнопки — это лишние шаги и деньги.
# Для чистого извлечения оставляем только то, что нужно: навигация, чтение, скролл, done.
NOISY_ACTIONS = [
    "write_file", "read_file", "replace_file", "save_as_pdf", "upload_file",
    "screenshot", "evaluate", "close", "search",
]

RULES = """
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


def make_llm(model: str, max_output_tokens: int = 32000):
    """Дефолт browser-use — 4096 токенов на ответ; длинная таблица в него не влезает
    и структурированный вывод обрезается на середине. Поэтому поднимаем явно."""
    m = model.lower()
    if m.startswith(("claude", "anthropic")):
        need, cls, kw = "ANTHROPIC_API_KEY", ChatAnthropic, {"max_tokens": max_output_tokens}
    elif m.startswith(("gpt", "o1", "o3", "o4")):
        need, cls, kw = "OPENAI_API_KEY", ChatOpenAI, {"max_completion_tokens": max_output_tokens}
    elif m.startswith("gemini"):
        need, cls, kw = "GOOGLE_API_KEY", ChatGoogle, {}
    else:
        sys.exit(f"Не знаю провайдера для модели {model}")
    if not os.getenv(need):
        sys.exit(f"Нет {need} — положи его в ~/browseruse-lab/.env")
    return cls(model=model, temperature=0.0, **kw)


# --- цена: счётчик browser-use знает не все модели, считаем сами по реестру LiteLLM ---
_PRICES: dict | None = None


def _prices() -> dict:
    global _PRICES
    if _PRICES is None:
        import json
        import ssl
        import urllib.request

        import certifi
        url = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
        try:
            ctx = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(url, timeout=30, context=ctx) as r:
                _PRICES = json.load(r)
        except Exception:
            _PRICES = {}
    return _PRICES


def cost_of(model: str, fresh_in: int, cached_in: int, out: int) -> float | None:
    p = _prices().get(model) or _prices().get(model.rsplit("-", 1)[0])
    if not p:
        return None
    return (fresh_in * (p.get("input_cost_per_token") or 0)
            + cached_in * (p.get("cache_read_input_token_cost") or p.get("input_cost_per_token") or 0)
            + out * (p.get("output_cost_per_token") or 0))


@dataclass
class RunReport:
    model: str
    ok: bool = False
    attempts: int = 0
    steps: int = 0
    seconds: float = 0.0
    tokens: int = 0
    tok_in: int = 0
    tok_cached: int = 0
    tok_out: int = 0
    cost: float = 0.0
    errors: list = field(default_factory=list)
    data: BaseModel | None = None


async def extract(
    task: str,
    schema: Type[T],
    model: str = "gpt-5-mini",
    max_steps: int = 20,
    attempts: int = 2,
    headless: bool = True,
    lean: bool = True,
) -> RunReport:
    rep = RunReport(model=model)
    started = time.time()

    for attempt in range(1, attempts + 1):
        rep.attempts = attempt
        browser = Browser(headless=headless)
        agent = Agent(
            task=task,
            llm=make_llm(model),
            browser=browser,
            output_model_schema=schema,
            extend_system_message=RULES,
            tools=Tools(exclude_actions=NOISY_ACTIONS) if lean else None,
            max_failures=5,
        )
        try:
            history = await agent.run(max_steps=max_steps)
            rep.steps += len(history.history)
            rep.errors += [e for e in history.errors() if e]
            if history.usage:
                u = history.usage
                rep.tokens += u.total_tokens
                rep.tok_in += u.total_prompt_tokens
                rep.tok_cached += u.total_prompt_cached_tokens
                rep.tok_out += u.total_completion_tokens
                rep.cost += u.total_cost
            data = history.structured_output
            if data is not None:
                rep.ok = True
                rep.data = data
                break
        except Exception as exc:  # noqa: BLE001
            rep.errors.append(f"attempt {attempt}: {exc!r}")
        finally:
            await browser.kill()

    rep.seconds = time.time() - started
    return rep


def print_report(rep: RunReport, extra: str = ""):
    print("\n=== ОТЧЁТ ===")
    print(f"модель  : {rep.model}")
    print(f"успех   : {rep.ok}  (попыток: {rep.attempts})")
    print(f"шагов   : {rep.steps}   время: {rep.seconds:.1f}s")
    print(f"токены  : {rep.tokens} (in {rep.tok_in} / cached {rep.tok_cached} / out {rep.tok_out})")
    real = cost_of(rep.model, rep.tok_in - rep.tok_cached, rep.tok_cached, rep.tok_out)
    print(f"цена    : ${real:.4f}" if real is not None else f"цена    : ${rep.cost:.4f} (по счётчику)")
    if rep.errors:
        print(f"ошибки  : {rep.errors[:5]}")
    if extra:
        print(extra)
