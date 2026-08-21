"""Демо кликанья: агент реально жмёт на элементы страницы.

TodoMVC — чисто клиентское приложение, никаких аккаунтов и серверного состояния.
Пишет GIF со скриншотами каждого шага, чтобы было видно, что именно он тыкал.
"""
import asyncio

from pydantic import BaseModel, Field
from browser_use import Agent, Browser, Tools

from extractor import make_llm, RULES, print_report, RunReport, NOISY_ACTIONS

URL = "https://demo.playwright.dev/todomvc"

TASK = f"""Открой {URL}.
1. Введи в поле ввода задачу "купить молоко" и нажми Enter.
2. Добавь так же вторую задачу "оплатить интернет".
3. Кликни по чекбоксу слева от "купить молоко", чтобы отметить её выполненной.
4. Кликни по фильтру "Active" внизу списка.
5. Верни, сколько задач осталось показано в списке после фильтрации и что написано
   в счётчике "items left".
"""


class Result(BaseModel):
    visible_tasks: list[str] = Field(description="Задачи, видимые в списке после фильтрации")
    items_left_text: str = Field(description="Текст счётчика внизу, например '1 item left'")


async def main():
    browser = Browser(headless=True)
    agent = Agent(
        task=TASK,
        llm=make_llm("gpt-5-mini"),
        browser=browser,
        output_model_schema=Result,
        extend_system_message=RULES + "\nКликай по элементам действием click. "
                                       "JavaScript для взаимодействия со страницей запрещён.",
        tools=Tools(exclude_actions=NOISY_ACTIONS),
        generate_gif="click_demo.gif",
        max_failures=5,
    )
    try:
        history = await agent.run(max_steps=15)
    finally:
        await browser.kill()

    rep = RunReport(model="gpt-5-mini")
    rep.steps = len(history.history)
    rep.ok = history.structured_output is not None
    if history.usage:
        u = history.usage
        rep.tokens, rep.tok_in = u.total_tokens, u.total_prompt_tokens
        rep.tok_cached, rep.tok_out = u.total_prompt_cached_tokens, u.total_completion_tokens
    rep.errors = [e for e in history.errors() if e]

    print("\n=== ЧТО ОН ДЕЛАЛ ===")
    for i, a in enumerate(history.model_actions(), 1):
        name = next(iter(a))
        params = {k: v for k, v in a[name].items() if k != "interacted_element"} if isinstance(a[name], dict) else a[name]
        print(f"{i:2d}. {name}: {str(params)[:110]}")

    print("\n=== РЕЗУЛЬТАТ ===")
    print(history.structured_output)
    print_report(rep)


if __name__ == "__main__":
    asyncio.run(main())
