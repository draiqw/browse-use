"""Первый прогон Agent + Claude. Требует ANTHROPIC_API_KEY в .env"""
import asyncio
import os
import sys

from dotenv import load_dotenv
from browser_use import Agent, Browser, ChatAnthropic

load_dotenv()

if not os.getenv("ANTHROPIC_API_KEY"):
    sys.exit("Нет ANTHROPIC_API_KEY — положи его в ~/browseruse-lab/.env")

TASK = (
    "Открой https://news.ycombinator.com и верни заголовок и ссылку "
    "самого верхнего поста. Ничего не кликай кроме навигации."
)


async def main():
    llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0.0)
    browser = Browser(headless=False)
    agent = Agent(task=TASK, llm=llm, browser=browser)
    history = await agent.run(max_steps=12)
    print("\n=== РЕЗУЛЬТАТ ===")
    print(history.final_result())
    await browser.kill()


if __name__ == "__main__":
    asyncio.run(main())
