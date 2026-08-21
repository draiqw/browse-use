"""Проверка браузерного слоя browser-use без LLM: старт, навигация, чтение состояния."""
import asyncio
from browser_use import Browser


async def main():
    browser = Browser(headless=True)
    await browser.start()
    try:
        await browser.navigate_to("https://example.com")
        print("url  :", await browser.get_current_page_url())
        print("title:", await browser.get_current_page_title())
        text = await browser.get_state_as_text()
        print("state:", len(text), "chars")
        print(text[:300])
    finally:
        await browser.kill()


if __name__ == "__main__":
    asyncio.run(main())
