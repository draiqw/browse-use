"""Прогон одной задачи browser-use на заданной модели с отчётом по шагам/токенам/цене.

  .venv/bin/python run_task.py --model claude-haiku-4-5-20251001
"""
import argparse
import asyncio
import os
import sys
import time

from dotenv import load_dotenv
from browser_use import Agent, Browser, ChatAnthropic, ChatOpenAI, ChatGoogle

load_dotenv()

DEFAULT_TASK = (
    "Открой https://news.ycombinator.com и верни заголовок и ссылку "
    "самого верхнего поста. Ничего не кликай, кроме навигации."
)

# см. agent/service.py:327 — координатный клик включается только для этих подстрок
COORD_PATTERNS = ("claude-sonnet-4", "claude-opus-4", "claude-fable-5", "gemini-3-pro", "browser-use/")


def make_llm(model: str):
    """Провайдер выбирается по имени модели; ключ берётся из .env."""
    m = model.lower()
    if m.startswith(("claude", "anthropic")):
        need, cls = "ANTHROPIC_API_KEY", ChatAnthropic
    elif m.startswith(("gpt", "o1", "o3", "o4")):
        need, cls = "OPENAI_API_KEY", ChatOpenAI
    elif m.startswith("gemini"):
        need, cls = "GOOGLE_API_KEY", ChatGoogle
    else:
        sys.exit(f"Не знаю провайдера для модели {model}")
    if not os.getenv(need):
        sys.exit(f"Нет {need} — положи его в ~/browseruse-lab/.env")
    return cls(model=model, temperature=0.0)


async def main(args):
    llm = make_llm(args.model)
    browser = Browser(headless=args.headless)
    agent = Agent(task=args.task, llm=llm, browser=browser)

    coord = any(p in args.model.lower() for p in COORD_PATTERNS)
    print(f"model={args.model}  координатный клик={'да' if coord else 'нет (только индексы DOM)'}")

    started = time.time()
    try:
        history = await agent.run(max_steps=args.max_steps)
    finally:
        await browser.kill()

    print("\n=== РЕЗУЛЬТАТ ===")
    print(history.final_result())
    print("\n=== МЕТРИКИ ===")
    print(f"шагов   : {len(history.history)}")
    print(f"успех   : {history.is_successful()}")
    print(f"ошибки  : {[e for e in history.errors() if e]}")
    print(f"время   : {time.time() - started:.1f}s")
    u = history.usage
    if u:
        print(f"токены  : {u.total_tokens} (in {u.total_prompt_tokens} / out {u.total_completion_tokens}"
              f" / cached {u.total_prompt_cached_tokens})")
        print(f"цена    : ${u.total_cost:.4f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="claude-haiku-4-5-20251001")
    p.add_argument("--task", default=DEFAULT_TASK)
    p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("--headless", action="store_true")
    asyncio.run(main(p.parse_args()))
