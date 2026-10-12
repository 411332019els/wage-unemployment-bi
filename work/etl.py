# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2"]
# ///
"""把 raw/ 的主計總處 XML 原始檔轉成整齊的長表 CSV，輸出到 data/。

raw/ 只讀不寫。執行：uv run work/etl.py
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
DATA = ROOT / "data"

# 教育業在 2008 年以前為「-」（未納入統計），2009 起才有值。
# 從 2009 起算，才能讓每年行業數一致；兩份資料用同一段年份。
START_YEAR = 2009
ENCODING = "utf-8-sig"  # UTF-8 with BOM，Excel 開啟不亂碼

WAGE_FILES = {
    "總薪資": RAW / "mp05001.xml",
    "經常性薪資": RAW / "mp05002.xml",
}
UNEMPLOYMENT_FILE = RAW / "mp04031.xml"

# 原始欄位 → 統一的行業名稱（行業統計分類第 11 次修正後的名稱）。
# 主計總處已依第 11 次修正把整條時間數列回溯重編，所以檔內各年都用同一組欄位；
# 這張表主要是把 XML 標籤名（標點被換成底線、夾帶英文與單位）還原成正式名稱。
INDUSTRIES = [
    ("礦業及土石採取業_Mining_and_quarrying_金額_新臺幣元", "礦業及土石採取業", "Mining and quarrying"),
    ("製造業_Manufacturing_金額_新臺幣元", "製造業", "Manufacturing"),
    ("電力及燃氣供應業_Electricity_and_gas_supply_金額_新臺幣元", "電力及燃氣供應業", "Electricity and gas supply"),
    ("用水供應及污染整治業_Water_supply_and_remediation_activities_金額_新臺幣元", "用水供應及污染整治業", "Water supply and remediation activities"),
    ("營建工程業_Construction_金額_新臺幣元", "營建工程業", "Construction"),
    ("批發及零售業_Wholesale_and_retail_trade_金額_新臺幣元", "批發及零售業", "Wholesale and retail trade"),
    ("運輸及倉儲業_Transportation_and_storage_金額_新臺幣元", "運輸及倉儲業", "Transportation and storage"),
    ("住宿及餐飲業_Accommodation_and_food_service_activities_金額_新臺幣元", "住宿及餐飲業", "Accommodation and food service activities"),
    ("出版影音及資通訊業_Information_and_communication_金額_新臺幣元", "出版影音及資通訊業", "Information and communication"),
    ("金融及保險業_Financial_and_insurance_activities_金額_新臺幣元", "金融及保險業", "Financial and insurance activities"),
    ("不動產業_Real_estate_activities_金額_新臺幣元", "不動產業", "Real estate activities"),
    ("專業科學及技術服務業_Professional_scientific_and_technical_activities_金額_新臺幣元", "專業、科學及技術服務業", "Professional, scientific and technical activities"),
    ("支援服務業_Support_service_activities_金額_新臺幣元", "支援服務業", "Support service activities"),
    ("教育業_Education_金額_新臺幣元", "教育業", "Education"),
    ("醫療保健及社會工作服務業_Human_health_and_social_work_activities_金額_新臺幣元", "醫療保健及社會工作服務業", "Human health and social work activities"),
    ("藝術_娛樂及休閒服務業_Arts_entertainment_and_recreation_金額_新臺幣元", "藝術、娛樂及休閒服務業", "Arts, entertainment and recreation"),
    ("其他服務業_Other_service_activities_金額_新臺幣元", "其他服務業", "Other service activities"),
]
INDUSTRY_BY_TAG = {tag: zh for tag, zh, _ in INDUSTRIES}

# 合計／小計／性別欄，不是單一行業，要排除。
WAGE_EXCLUDED_TAGS = {
    "年月別_Year_and_month",
    "工業及服務業__Industry_and_services_金額_新臺幣元",
    "工業_Industrial_金額_新臺幣元",
    "服務業_Services_金額_新臺幣元",
    "男性_Male_金額_新臺幣元",
    "女性_Female_金額_新臺幣元",
}

# 每 5 歲一組用「小計」（男女合計）欄；65 歲以上沒有細分，用「合計」欄。
# 15-24、25-44、45-64 三個大組與全體、男、女欄都是合計，不取。
AGE_GROUPS = [
    ("年齡15-24歲_15-19歲_小計_15-24_years_15-19_years_Total_百分比", "15-19"),
    ("年齡15-24歲_20-24歲_小計_15-24_years_20-24_years_Total_百分比", "20-24"),
    ("年齡25-44歲_25-29歲_小計_25-44_years_25-29_years_Total_百分比", "25-29"),
    ("年齡25-44歲_30-34歲_小計_25-44_years_30-34_years_Total_百分比", "30-34"),
    ("年齡25-44歲_35-39歲_小計_25-44_years_35-39_years_Total_百分比", "35-39"),
    ("年齡25-44歲_40-44歲_小計_25-44_years_40-44_years_Total_百分比", "40-44"),
    ("年齡45-64歲_45-49歲_小計_45-64_years_45-49_years_Total_百分比", "45-49"),
    ("年齡45-64歲_50-54歲_小計_45-64_years_50-54_years_Total_百分比", "50-54"),
    ("年齡45-64歲_55-59歲_小計_45-64_years_55-59_years_Total_百分比", "55-59"),
    ("年齡45-64歲_60-64歲_小計_45-64_years_60-64_years_Total_百分比", "60-64"),
    ("年齡65歲以上_合計_65_years_and_above_Total_百分比", "65+"),
]

# 失業率檔的年列長這樣：「１１３年平均 Ave., 2024」（全形數字、前置空白）；月列是「１　月  Jan.」。
ROC_ANNUAL = re.compile(r"^(\d+)年平均\s*Ave\.,\s*(\d{4})$")


def records(path: Path) -> list[dict[str, str]]:
    """XML 每筆 record 轉成 {欄位: 去空白的文字}。XML 沒有 Excel 的合併儲存格，每列都是完整的。"""
    root = ET.parse(path).getroot()
    return [{c.tag: (c.text or "").strip() for c in rec} for rec in root]


def parse_number(text: str) -> float | None:
    """「-」或空字串代表無資料，回傳 None。"""
    text = unicodedata.normalize("NFKC", text).replace(",", "").strip()
    if text in ("", "-", "…", "..."):
        return None
    return float(text)


def build_wages() -> pd.DataFrame:
    rows = []
    for wage_type, path in WAGE_FILES.items():
        for rec in records(path):
            period = rec["年月別_Year_and_month"]
            # 年資料是 4 位數西元年；6 位數是月資料；帶 Ⓟ（初步）的是當年尚未結束的累計值，都不要。
            if not re.fullmatch(r"\d{4}", period):
                continue
            year = int(period)
            if year < START_YEAR:
                continue
            unknown = set(rec) - WAGE_EXCLUDED_TAGS - INDUSTRY_BY_TAG.keys()
            if unknown:
                raise ValueError(f"{path.name} {year} 出現未對照的欄位：{sorted(unknown)}")
            for tag, industry in INDUSTRY_BY_TAG.items():
                amount = parse_number(rec[tag])
                if amount is None:
                    raise ValueError(f"{path.name} {year} {industry} 無資料，請調整 START_YEAR")
                rows.append((year, industry, wage_type, int(amount)))
    df = pd.DataFrame(rows, columns=["year", "industry", "wage_type", "amount_twd"])
    return df.sort_values(["year", "wage_type", "amount_twd"], ascending=[True, True, False], ignore_index=True)


def build_unemployment() -> pd.DataFrame:
    rows = []
    for rec in records(UNEMPLOYMENT_FILE):
        label = unicodedata.normalize("NFKC", rec["年月別_Year_and_month"]).strip()
        m = ROC_ANNUAL.match(label)
        if not m:
            continue  # 月資料
        year = int(m.group(1)) + 1911  # 民國年轉西元年
        if year != int(m.group(2)):
            raise ValueError(f"民國年與標籤上的西元年不符：{label!r}")
        if year < START_YEAR:
            continue
        for tag, age_group in AGE_GROUPS:
            rate = parse_number(rec[tag])
            if rate is None:
                raise ValueError(f"{year} {age_group} 無資料，請調整 START_YEAR")
            rows.append((year, age_group, rate))
    return pd.DataFrame(rows, columns=["year", "age_group", "unemployment_rate_pct"])


def main() -> None:
    DATA.mkdir(exist_ok=True)

    wages = build_wages()
    wages.to_csv(DATA / "wage_by_industry.csv", index=False, encoding=ENCODING)

    unemployment = build_unemployment()
    unemployment.to_csv(DATA / "unemployment_by_age.csv", index=False, encoding=ENCODING)

    mapping = pd.DataFrame(INDUSTRIES, columns=["raw_column", "industry", "industry_en"])
    mapping.insert(0, "source_files", "mp05001.xml;mp05002.xml")
    mapping.to_csv(DATA / "industry_mapping.csv", index=False, encoding=ENCODING)

    print(f"wage_by_industry.csv     {len(wages):>5} 列  {wages.year.min()}–{wages.year.max()}  {wages.industry.nunique()} 個行業")
    print(f"unemployment_by_age.csv  {len(unemployment):>5} 列  {unemployment.year.min()}–{unemployment.year.max()}  {unemployment.age_group.nunique()} 個年齡組")
    print(f"industry_mapping.csv     {len(mapping):>5} 列")


if __name__ == "__main__":
    main()
