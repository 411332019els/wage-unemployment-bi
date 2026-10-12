# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""把 data/ 的 CSV 轉成 docs/data.js，給 docs/index.html 用。

用 <script src="data.js"> 載入，資料掛在 window.BI_DATA；
不用 fetch()，所以直接雙擊 index.html（file://）也能讀到。
執行：uv run work/build_data.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "docs" / "data.js"

WAGE_TYPES = ["總薪資", "經常性薪資"]


def read_csv(name: str) -> list[dict[str, str]]:
    with open(DATA / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build() -> dict:
    wages = read_csv("wage_by_industry.csv")
    unemployment = read_csv("unemployment_by_age.csv")

    years = sorted({int(r["year"]) for r in wages})
    if years != sorted({int(r["year"]) for r in unemployment}):
        raise ValueError("薪資與失業率的年份不一致")
    index = {y: i for i, y in enumerate(years)}

    # 行業依對照表順序（主計總處行業分類順序），排名交給網頁算。
    industries = [r["industry"] for r in read_csv("industry_mapping.csv")]
    amount = {t: {ind: [None] * len(years) for ind in industries} for t in WAGE_TYPES}
    for r in wages:
        amount[r["wage_type"]][r["industry"]][index[int(r["year"])]] = int(r["amount_twd"])

    age_groups = list(dict.fromkeys(r["age_group"] for r in unemployment))
    rate = {a: [None] * len(years) for a in age_groups}
    for r in unemployment:
        rate[r["age_group"]][index[int(r["year"])]] = float(r["unemployment_rate_pct"])

    # 全體數字：薪資平均線（工業及服務業）、全體與 15-24 歲失業率。
    overall_wage = {t: [None] * len(years) for t in WAGE_TYPES}
    for r in read_csv("wage_overall.csv"):
        overall_wage[r["wage_type"]][index[int(r["year"])]] = int(r["amount_twd"])
    overall_rate = {"全體": [None] * len(years), "15-24": [None] * len(years)}
    for r in read_csv("unemployment_overall.csv"):
        overall_rate[r["group"]][index[int(r["year"])]] = float(r["unemployment_rate_pct"])

    blocks = (*amount.values(), rate, overall_wage, overall_rate)
    missing = [k for block in blocks for k, v in block.items() if None in v]
    if missing:
        raise ValueError(f"有缺值：{missing}")

    # 每個數列與 years 對齊：amount[薪資類型][行業][i] 是 years[i] 年的值。
    return {
        "years": years,
        "wage": {
            "unit": "新臺幣元",
            "types": WAGE_TYPES,
            "industries": industries,
            "amount": amount,
            "overall": overall_wage,  # 工業及服務業全體平均
        },
        "unemployment": {
            "unit": "%",
            "ageGroups": age_groups,
            "rate": rate,
            "overall": overall_rate,  # 全體、15-24 歲
        },
        "source": "行政院主計總處：各業受僱員工每人每月薪資（data.gov.tw 資料集 9634、9663）、失業率按年齡分（32743）",
    }


def main() -> None:
    payload = json.dumps(build(), ensure_ascii=False, separators=(",", ":"))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        "// 由 work/build_data.py 自動產生，請勿手動修改。\n"
        f"window.BI_DATA = {payload};\n",
        encoding="utf-8",
    )
    print(f"{OUT.relative_to(ROOT)}  {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
