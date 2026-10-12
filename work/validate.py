# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2"]
# ///
"""核對 data/ 的 CSV 與 raw/ 原始檔是否一致，並做範圍與完整性檢查。

執行：uv run work/validate.py [亂數種子]
任一檢查失敗時以非 0 結束。
"""

from __future__ import annotations

import random
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
DATA = ROOT / "data"
WAGE_FILES = {"總薪資": "mp05001.xml", "經常性薪資": "mp05002.xml"}
UNEMPLOYMENT_FILE = "mp04031.xml"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {message}")
    if not ok:
        failures.append(message)


def raw_records(name: str) -> list[dict[str, str]]:
    root = ET.parse(RAW / name).getroot()
    return [
        {c.tag: unicodedata.normalize("NFKC", c.text or "").strip() for c in rec}
        for rec in root
    ]


def raw_wage(wage_type: str, year: int, raw_column: str) -> str:
    for rec in raw_records(WAGE_FILES[wage_type]):
        if rec["年月別_Year_and_month"] == str(year):
            return rec[raw_column]
    raise KeyError(f"{WAGE_FILES[wage_type]} 找不到 {year} 年")


def raw_unemployment(year: int, age_group: str) -> tuple[str, str]:
    # 直接從原始標籤找欄位，不沿用 etl.py 的對照，避免同一個錯誤兩邊都對。
    needle = "年齡65歲以上_合計_" if age_group == "65+" else f"_{age_group}歲_小計_"
    for rec in raw_records(UNEMPLOYMENT_FILE):
        if rec["年月別_Year_and_month"].endswith(f"Ave., {year}"):
            tags = [t for t in rec if needle in t]
            assert len(tags) == 1, f"{age_group} 對到 {len(tags)} 個欄位"
            return tags[0], rec[tags[0]]
    raise KeyError(f"{UNEMPLOYMENT_FILE} 找不到 {year} 年平均")


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else random.randrange(10_000)
    rng = random.Random(seed)

    wages = pd.read_csv(DATA / "wage_by_industry.csv", encoding="utf-8-sig")
    unemployment = pd.read_csv(DATA / "unemployment_by_age.csv", encoding="utf-8-sig")
    mapping = pd.read_csv(DATA / "industry_mapping.csv", encoding="utf-8-sig")
    raw_column = dict(zip(mapping.industry, mapping.raw_column))

    print(f"1. 隨機抽 5 個數字與原始檔核對（種子 {seed}，用相同種子可重現）")
    pool = [("wage", i) for i in wages.index] + [("unemp", i) for i in unemployment.index]
    for kind, i in rng.sample(pool, 5):
        if kind == "wage":
            row = wages.loc[i]
            raw = raw_wage(row.wage_type, row.year, raw_column[row.industry])
            ok = float(raw) == float(row.amount_twd)
            check(ok, f"{WAGE_FILES[row.wage_type]} {row.year} {row.industry} {row.wage_type}: CSV {row.amount_twd} / 原始 {raw}")
        else:
            row = unemployment.loc[i]
            tag, raw = raw_unemployment(row.year, row.age_group)
            ok = float(raw) == float(row.unemployment_rate_pct)
            check(ok, f"{UNEMPLOYMENT_FILE} {row.year} {row.age_group} 歲: CSV {row.unemployment_rate_pct} / 原始 {raw}（{tag}）")

    print("2. 數值範圍")
    rate = unemployment.unemployment_rate_pct
    check(rate.between(0, 30).all(), f"失業率都在 0～30 之間（實際 {rate.min()}～{rate.max()}）")
    check((wages.amount_twd > 0).all(), f"薪資都大於 0（最小 {wages.amount_twd.min()}）")

    print("3. 完整性")
    counts = wages.groupby(["year", "wage_type"]).industry.nunique()
    check(counts.nunique() == 1, f"每年每種薪資的行業數一致（{sorted(map(int, counts.unique()))}）")
    age_counts = unemployment.groupby("year").age_group.nunique()
    check(age_counts.nunique() == 1, f"每年年齡組數一致（{sorted(map(int, age_counts.unique()))}）")
    check(wages.notna().all().all() and unemployment.notna().all().all(), "沒有空值")
    check(not wages.duplicated(["year", "industry", "wage_type"]).any(), "薪資表沒有重複列")
    check(not unemployment.duplicated(["year", "age_group"]).any(), "失業率表沒有重複列")
    wy, uy = sorted(wages.year.unique()), sorted(unemployment.year.unique())
    check(wy == uy == list(range(wy[0], wy[-1] + 1)), f"兩表年份相同且連續（{wy[0]}–{wy[-1]}，{len(wy)} 年）")
    check(set(wages.industry) == set(mapping.industry), "薪資表行業與對照表一致")

    print()
    if failures:
        print(f"共 {len(failures)} 項失敗")
        sys.exit(1)
    print("全部通過")


if __name__ == "__main__":
    main()
