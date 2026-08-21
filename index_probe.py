"""Стабильны ли индексы browser-use при перерисовке страницы?

Механика (исходники 0.13.8):
  dom/serializer/serializer.py:645   index = CDP backendNodeId (синтетический только при коллизии)
  browser/session.py:2437            click(index) ищет узел ТОЛЬКО в _cached_selector_map
  browser/watchdogs/dom_watchdog.py:671  карта перестраивается на каждом шаге агента

Состояние страницы готовим через localStorage — нас интересует не ввод, а поведение индексов.
"""
import asyncio
import json

from browser_use import Browser
from browser_use.browser.events import ClickElementEvent

URL = "https://demo.playwright.dev/todomvc"
TODOS = [{"id": "a", "title": "купить молоко", "completed": False},
         {"id": "b", "title": "оплатить интернет", "completed": False}]


async def js(browser, code):
    s = await browser.get_or_create_cdp_session()
    r = await s.cdp_client.send.Runtime.evaluate(
        params={"expression": code, "returnByValue": True, "awaitPromise": True},
        session_id=s.session_id)
    return r.get("result", {}).get("value")


async def snapshot(browser, label):
    await browser.get_browser_state_summary()
    smap = await browser.get_selector_map()
    print(f"\n--- {label} ---")
    rows = {}
    for idx, node in sorted(smap.items()):
        a = node.attributes or {}
        tag = (node.tag_name or "").lower()
        cls = a.get("class", "")
        txt = (node.get_meaningful_text_for_llm() or "").strip()[:28]
        if tag == "input" and "toggle" in cls:
            kind = f"ЧЕКБОКС «{txt}»"
        elif tag == "a" and txt in ("All", "Active", "Completed"):
            kind = f"фильтр {txt}"
        elif tag == "label":
            kind = f"текст «{txt}»"
        else:
            continue
        rows[idx] = (node.backend_node_id, kind)
        print(f"  index={idx:<5} backendNodeId={node.backend_node_id:<5} {kind}")
    return rows


async def main():
    browser = Browser(headless=True)
    await browser.start()
    try:
        await browser.navigate_to(URL)
        await js(browser, f"localStorage.setItem('react-todos', {json.dumps(json.dumps(TODOS))})")
        await js(browser, "location.reload()")  # повторный navigate_to на тот же URL не перезагружает
        await asyncio.sleep(2)

        before = await snapshot(browser, "ДО клика")
        boxes = [i for i, (_, k) in before.items() if k.startswith("ЧЕКБОКС")]
        if not boxes:
            print("чекбоксы не появились — localStorage-ключ не тот")
            return
        target = boxes[0]
        print(f"\n>>> кликаем index={target} (backendNodeId={before[target][0]}, {before[target][1]})")
        node = await browser.get_dom_element_by_index(target)
        ev = browser.event_bus.dispatch(ClickElementEvent(node=node))
        await ev
        await asyncio.sleep(1.5)
        print("состояние после клика:", await js(browser, "localStorage.getItem('react-todos')"))

        after = await snapshot(browser, "ПОСЛЕ клика")

        print("\n=== ОТВЕТ НА ВОПРОС ===")
        if target not in after:
            print(f"index={target} ИСЧЕЗ из карты: узел пересоздан при перерисовке.")
        elif after[target][0] != before[target][0]:
            print(f"index={target} теперь указывает на ДРУГОЙ узел "
                  f"(backendNodeId {before[target][0]} → {after[target][0]}).")
        else:
            print(f"index={target} указывает на ТОТ ЖЕ узел (backendNodeId {before[target][0]}). "
                  f"Индекс пережил перерисовку.")
        moved = {i for i in before.keys() & after.keys() if before[i][1] != after[i][1]}
        print(f"индексов, сменивших смысл: {len(moved)} {sorted(moved)}")
        print(f"было индексов: {sorted(before)}")
        print(f"стало индексов: {sorted(after)}")
    finally:
        await browser.kill()


if __name__ == "__main__":
    asyncio.run(main())
