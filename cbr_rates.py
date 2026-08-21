"""Полигон: курсы ЦБ РФ. Браузерное извлечение сверяется с официальным XML.

Это макет банковского коннектора: тот же контракт (типизированная схема),
те же инварианты и та же независимая сверка с эталоном.
"""
import argparse
import asyncio
import sys
import ssl
import urllib.request
import xml.etree.ElementTree as ET

import certifi

from pydantic import BaseModel, Field

from extractor import extract, print_report

URL = "https://www.cbr.ru/currency_base/daily/"
XML = "https://www.cbr.ru/scripts/XML_daily.asp"


class Rate(BaseModel):
    char_code: str = Field(description="Буквенный код валюты, например USD")
    nominal: int = Field(description="Единиц иностранной валюты")
    name: str = Field(description="Название валюты")
    value: float = Field(description="Курс в рублях за указанный номинал")


class Rates(BaseModel):
    date: str = Field(description="Дата курсов в формате ДД.ММ.ГГГГ")
    rates: list[Rate]


TASK = (
    f"Открой {URL}. На странице таблица курсов валют ЦБ РФ со столбцами "
    "«Цифр. код», «Букв. код», «Единиц», «Валюта», «Курс». "
    "Извлеки ВСЕ строки таблицы без исключения и дату, на которую установлены курсы. "
    "В поле value записывай курс как число с точкой (запятую в исходнике замени на точку)."
)


def ground_truth() -> tuple[str, dict[str, tuple[int, float]]]:
    """Эталон из официального XML ЦБ."""
    ctx = ssl.create_default_context(cafile=certifi.where())  # у uv-питона нет системного CA-бандла
    with urllib.request.urlopen(XML, timeout=30, context=ctx) as r:
        root = ET.fromstring(r.read().decode("windows-1251"))
    date = root.attrib["Date"]
    out = {}
    for v in root.findall("Valute"):
        out[v.find("CharCode").text] = (
            int(v.find("Nominal").text),
            float(v.find("Value").text.replace(",", ".")),
        )
    return date, out


def check(data: Rates) -> list[str]:
    """Инварианты + сверка с эталоном. Возвращает список нарушений."""
    problems = []
    gt_date, gt = ground_truth()

    # --- инварианты, не требующие эталона ---
    if not data.rates:
        problems.append("пустой список курсов")
    codes = [r.char_code.upper() for r in data.rates]
    dups = {c for c in codes if codes.count(c) > 1}
    if dups:
        problems.append(f"дубли кодов: {sorted(dups)}")
    bad = [r.char_code for r in data.rates if r.value <= 0 or r.nominal <= 0]
    if bad:
        problems.append(f"неположительные значения: {bad}")

    # --- сверка с официальным XML ---
    if data.date != gt_date:
        problems.append(f"дата {data.date} != эталон {gt_date}")
    missing = sorted(set(gt) - set(codes))
    if missing:
        problems.append(f"потеряно валют: {len(missing)} → {missing[:10]}")
    extra = sorted(set(codes) - set(gt))
    if extra:
        problems.append(f"лишние коды: {extra[:10]}")

    wrong = []
    for r in data.rates:
        c = r.char_code.upper()
        if c not in gt:
            continue
        gn, gv = gt[c]
        if r.nominal != gn:
            wrong.append(f"{c}: номинал {r.nominal} != {gn}")
        elif abs(r.value - gv) > 0.0001:
            wrong.append(f"{c}: курс {r.value} != {gv}")
    if wrong:
        problems.append(f"расхождений в значениях: {len(wrong)} → {wrong[:5]}")

    return problems


async def one_run(args, idx: int):
    rep = await extract(TASK, Rates, model=args.model, max_steps=args.max_steps,
                        attempts=args.attempts, headless=True)
    problems = ["агент не вернул данные"] if not rep.ok else check(rep.data)  # type: ignore[arg-type]
    extra = ""
    if rep.ok:
        data: Rates = rep.data  # type: ignore[assignment]
        _, gt = ground_truth()
        extra = f"строк извлечено: {len(data.rates)} из {len(gt)} эталонных\nдата: {data.date}\n"
        extra += "ПРОВЕРКА: ПРОЙДЕНА" if not problems else "ПРОВЕРКА: ПРОВАЛЕНА\n  - " + "\n  - ".join(problems)
        if args.out:
            path = args.out if args.runs == 1 else f"{args.out.rsplit('.', 1)[0]}.{idx}.json"
            with open(path, "w", encoding="utf-8") as f:
                f.write(data.model_dump_json(indent=2))
            extra += f"\nсохранено: {path}"
    print_report(rep, extra)
    return rep, problems


async def main(args):
    results = []
    for i in range(1, args.runs + 1):
        if args.runs > 1:
            print(f"\n########## ПРОГОН {i}/{args.runs} ##########")
        results.append(await one_run(args, i))

    if args.runs > 1:
        good = sum(1 for _, pr in results if not pr)
        print("\n########## ИТОГ ##########")
        print(f"успешных прогонов: {good}/{args.runs}")
        for i, (rep, pr) in enumerate(results, 1):
            mark = "OK  " if not pr else "FAIL"
            print(f"  {i}. {mark} шагов={rep.steps} {rep.seconds:.0f}s "
                  f"токенов={rep.tokens} {'; '.join(pr)[:90]}")
    sys.exit(0 if all(not pr for _, pr in results) else 1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="gpt-5-mini")
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--attempts", type=int, default=2)
    p.add_argument("--runs", type=int, default=1, help="сколько раз подряд прогнать — проверка стабильности")
    p.add_argument("--out", default="", help="сохранить результат в JSON")
    asyncio.run(main(p.parse_args()))
