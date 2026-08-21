"""Что именно агент нажал: для каждого click печатаем реальный элемент из истории."""
import asyncio

from pydantic import BaseModel, Field
from browser_use import Agent, Browser, Tools

from extractor import make_llm, RULES, NOISY_ACTIONS

URL = "https://demo.playwright.dev/todomvc"
TASK = f"""Открой {URL}.
1. Введи задачу "купить молоко" и нажми Enter.
2. Введи задачу "оплатить интернет" и нажми Enter.
3. Кликни по чекбоксу слева от "купить молоко", чтобы отметить её выполненной.
4. Кликни по фильтру "Active" внизу списка.
5. Верни видимые задачи и текст счётчика "items left".
"""


class Result(BaseModel):
    visible_tasks: list[str] = Field(description="Задачи, видимые после фильтрации")
    items_left_text: str = Field(description="Текст счётчика, например '1 item left'")


async def main():
    browser = Browser(headless=True)
    agent = Agent(task=TASK, llm=make_llm("gpt-5-mini"), browser=browser,
                  output_model_schema=Result, max_failures=5,
                  extend_system_message=RULES + "\nКликай действием click. JavaScript запрещён.",
                  tools=Tools(exclude_actions=NOISY_ACTIONS))
    try:
        history = await agent.run(max_steps=15)
    finally:
        await browser.kill()

    print("\n=== ПО ЧЕМУ ОН ЖАЛ НА САМОМ ДЕЛЕ ===")
    for a, el in zip(history.model_actions(), history.model_actions_filtered(include=["click"]) or [None] * 99):
        pass
    for i, a in enumerate(history.model_actions(), 1):
        name = next(iter(a))
        if name not in ("click", "input", "send_keys"):
            continue
        params = a[name]
        el = params.get("interacted_element") if isinstance(params, dict) else None
        idx = params.get("index") if isinstance(params, dict) else None
        if el is None:
            print(f"{i:2d}. {name}(index={idx}) -> элемент не записан")
            continue
        attrs = getattr(el, "attributes", {}) or {}
        print(f"{i:2d}. {name}(index={idx}) -> <{getattr(el, 'tag_name', '?')} "
              f"class='{attrs.get('class','')}' aria-label='{attrs.get('aria-label','')}'> "
              f"текст='{(getattr(el, 'node_value', '') or '')[:25]}'")

    print("\n=== РЕЗУЛЬТАТ ===")
    print(history.structured_output)


if __name__ == "__main__":
    asyncio.run(main())
