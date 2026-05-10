# =============================================================================
# ETL CORE - drug_substitution_engine
# =============================================================================
# Файл: core/etl.py
# Дата: 2026-04-27 (extended for Phase A1)
# Опис: ETL утиліти для Phase A0 (discovery) та Phase A1 (data aggregation).
# =============================================================================

r"""
ETL утиліти для проекту drug_substitution_engine.

Адаптовано з canonical/project_core/utility_functions/etl_utils.py.
Прибрано всі `print()` (логування — на рівні pipeline), валідаційні функції
залишені для smoke-tests (не використовуються в production-pipeline).

Функції:
    Date parsing (Phase A0/A1):
        - parse_period_id, parse_period_id_series, align_to_monday

    Column transformations (Phase A1):
        - convert_numeric_columns(df, ['Q', 'V'])
        - rename_columns(df, COLUMN_RENAME_MAP)
        - add_date_column(df)

    Aggregation (Phase A1):
        - fill_gaps(df, group_cols, ...)         ← КРИТИЧНО для stockout detection!
        - aggregate_weekly(df, group_cols, ...)
        - calculate_market_totals(df_competitors)
        - calculate_notsold_percent(df_target)

Використання:
    from core.etl import (
        parse_period_id, convert_numeric_columns, rename_columns,
        add_date_column, fill_gaps, aggregate_weekly,
        calculate_market_totals, calculate_notsold_percent,
    )
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# =============================================================================
# DATE PARSING
# =============================================================================

def align_to_monday(date: datetime) -> datetime:
    """Вирівняти дату до понеділка того ж тижня."""
    return date - timedelta(days=date.weekday())


def parse_period_id(period_id: int) -> datetime:
    """
    Парсити PERIOD_ID (формат YYYYNNNNN) у datetime.

    Example:
        >>> parse_period_id(202400305)
        datetime(2024, 11, 1)
    """
    period_str    = str(int(period_id))
    year          = int(period_str[:4])
    week_day_code = int(period_str[4:])

    week        = week_day_code // 7
    day_of_week = week_day_code % 7

    first_day   = datetime(year, 1, 1)
    target_date = first_day + timedelta(weeks=week, days=day_of_week)
    return target_date


def parse_period_id_series(series: pd.Series) -> pd.Series:
    """Векторизована версія parse_period_id для pandas Series."""
    s             = series.astype(str)
    year          = s.str[:4].astype(int)
    week_day_code = s.str[4:].astype(int)

    week        = week_day_code // 7
    day_of_week = week_day_code % 7

    base_dates = pd.to_datetime(year.astype(str) + "-01-01")
    return base_dates + pd.to_timedelta(week * 7 + day_of_week, unit="D")


# =============================================================================
# COLUMN TRANSFORMATIONS
# =============================================================================

def convert_numeric_columns(
    df: pd.DataFrame,
    columns: List[str] = None,
) -> pd.DataFrame:
    """
    Конвертувати рядкові числові колонки (з комою як decimal separator) у float.

    Q, V у raw CSV у форматі "12,5" (string з комою). Конвертуємо в 12.5 float.

    Args:
        df: Вхідний DataFrame.
        columns: Список колонок (за замовчуванням ['Q', 'V']).

    Returns:
        Новий DataFrame з float колонками.
    """
    if columns is None:
        columns = ["Q", "V"]
    df = df.copy()
    for col in columns:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(",", ".").astype(float)
    return df


def rename_columns(df: pd.DataFrame, rename_map: Dict[str, str]) -> pd.DataFrame:
    """
    Перейменувати колонки за маппінгом (тільки існуючі).

    Args:
        df: Вхідний DataFrame.
        rename_map: {old: new}.

    Returns:
        Новий DataFrame з перейменованими колонками.
    """
    df = df.copy()
    existing = {k: v for k, v in rename_map.items() if k in df.columns}
    return df.rename(columns=existing)


def add_date_column(
    df: pd.DataFrame,
    period_col: str = "PERIOD_ID",
    date_col: str = "Date",
    align_monday: bool = True,
) -> pd.DataFrame:
    """
    Додати колонку Date на основі PERIOD_ID.

    Args:
        df: Вхідний DataFrame з period_col.
        period_col: Назва колонки PERIOD_ID.
        date_col: Назва нової колонки.
        align_monday: Вирівнювати по понеділках (для тижневої агрегації).

    Returns:
        DataFrame з новою колонкою.
    """
    df = df.copy()
    df[date_col] = parse_period_id_series(df[period_col])
    if align_monday:
        df[date_col] = df[date_col] - pd.to_timedelta(df[date_col].dt.weekday, unit="D")
    return df


# =============================================================================
# GAP FILLING — критично важливо для stockout detection!
# =============================================================================

def fill_gaps(
    df: pd.DataFrame,
    group_cols: List[str] = None,
    date_col: str = "Date",
    value_cols: List[str] = None,
    categorical_cols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Заповнити пропущені тижні нулями для кожної групи (PHARM_ID, DRUGS_ID).

    КРИТИЧНО: без цього кроку періоди stock-out (Q=0) будуть невидимі в даних.
    Raw CSV містить лише тижні з продажами; пропущені тижні треба додати з Q=0.

    Алгоритм (vectorized, batch-підхід):
        1. Агрегація дублікатів по (group_cols + date_col).
        2. Побудова повного date range (тижневі) для кожної групи.
        3. Left join skeleton зі справжніми даними.
        4. Заповнення NaN: числові → 0, категоріальні → ffill+bfill в межах групи.

    Args:
        df: Вхідний DataFrame.
        group_cols: Колонки групування (default: ['PHARM_ID', 'DRUGS_ID']).
        date_col: Колонка з датою (Monday-aligned).
        value_cols: Числові колонки для fillna(0) (default: ['Q', 'V']).
        categorical_cols: Колонки для ffill+bfill
                          (default: DRUGS_NAME, INN_NAME, INN_ID, NFC1_ID, NFC_ID).

    Returns:
        DataFrame з заповненими прогалинами (всі тижні присутні).
    """
    if group_cols is None:
        group_cols = ["PHARM_ID", "DRUGS_ID"]
    if value_cols is None:
        value_cols = ["Q", "V"]
    if categorical_cols is None:
        categorical_cols = ["DRUGS_NAME", "INN_NAME", "INN_ID", "NFC1_ID", "NFC_ID"]

    existing_value_cols = [c for c in value_cols if c in df.columns]
    existing_cat_cols   = [c for c in categorical_cols if c in df.columns]

    if df.empty:
        return df.copy()

    # Крок 1: Агрегація дублікатів
    agg_dict = {col: "sum" for col in existing_value_cols}
    agg_dict.update({col: "first" for col in existing_cat_cols})
    all_keys = group_cols + [date_col]
    df_agg = df.groupby(all_keys, sort=False).agg(agg_dict).reset_index()

    # Крок 2: Скелет повних date ranges per group
    date_ranges = df_agg.groupby(group_cols)[date_col].agg(["min", "max"]).reset_index()

    skeleton_chunks = []
    for _, row in date_ranges.iterrows():
        full_dates = pd.date_range(start=row["min"], end=row["max"], freq="7D")
        chunk = pd.DataFrame({date_col: full_dates})
        for col in group_cols:
            chunk[col] = row[col]
        skeleton_chunks.append(chunk)

    if not skeleton_chunks:
        return df.copy()

    skeleton = pd.concat(skeleton_chunks, ignore_index=True)

    # Крок 3: Left join
    result = skeleton.merge(df_agg, on=all_keys, how="left")

    # Крок 4: Fillna
    for col in existing_value_cols:
        result[col] = result[col].fillna(0)

    if existing_cat_cols:
        result[existing_cat_cols] = (
            result.groupby(group_cols)[existing_cat_cols]
            .transform(lambda x: x.ffill().bfill())
        )

    return result


# =============================================================================
# WEEKLY AGGREGATION
# =============================================================================

def aggregate_weekly(
    df: pd.DataFrame,
    group_cols: List[str],
    sum_cols: List[str] = None,
    first_cols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Агрегація даних по групам (тижнева — якщо в group_cols є Date).

    Args:
        df: Вхідний DataFrame.
        group_cols: Колонки групування (наприклад ['PHARM_ID', 'DRUGS_ID', 'Date']).
        sum_cols: Числові колонки для sum (default: ['Q', 'V']).
        first_cols: Категоріальні колонки для 'first'
                    (default: DRUGS_NAME, INN_NAME, INN_ID, NFC1_ID, NFC_ID).

    Returns:
        Агрегований DataFrame.
    """
    if sum_cols is None:
        sum_cols = ["Q", "V"]
    if first_cols is None:
        first_cols = ["DRUGS_NAME", "INN_NAME", "INN_ID", "NFC1_ID", "NFC_ID"]

    agg_dict: Dict[str, str] = {}
    for col in sum_cols:
        if col in df.columns:
            agg_dict[col] = "sum"
    for col in first_cols:
        if col in df.columns:
            agg_dict[col] = "first"

    return df.groupby(group_cols).agg(agg_dict).reset_index()


# =============================================================================
# MARKET TOTALS
# =============================================================================

def calculate_market_totals(
    df_competitors: pd.DataFrame,
    date_col: str = "Date",
    drug_col: str = "DRUGS_ID",
    quantity_col: str = "Q",
    value_col: str = "V",
) -> pd.DataFrame:
    """
    Розрахунок ринкових показників (сума по конкурентах) per Date×DRUGS_ID.

    Args:
        df_competitors: DataFrame з даними конкурентів (PHARM_ID != CLIENT_ID).
        date_col, drug_col, quantity_col, value_col: Назви колонок.

    Returns:
        DataFrame з колонками [date_col, drug_col, MARKET_TOTAL_DRUGS_PACK,
                                MARKET_TOTAL_DRUGS_REVENUE].
    """
    if df_competitors.empty:
        return pd.DataFrame({
            date_col: pd.Series(dtype="datetime64[ns]"),
            drug_col: pd.Series(dtype="int64"),
            "MARKET_TOTAL_DRUGS_PACK":    pd.Series(dtype="float64"),
            "MARKET_TOTAL_DRUGS_REVENUE": pd.Series(dtype="float64"),
        })

    market_totals = (
        df_competitors.groupby([date_col, drug_col])
        .agg({quantity_col: "sum", value_col: "sum"})
        .reset_index()
    )
    market_totals.columns = [
        date_col, drug_col,
        "MARKET_TOTAL_DRUGS_PACK",
        "MARKET_TOTAL_DRUGS_REVENUE",
    ]
    return market_totals


# =============================================================================
# NOTSOLD ANALYSIS
# =============================================================================

def calculate_notsold_percent(
    df_target: pd.DataFrame,
    group_cols: List[str] = None,
    quantity_col: str = "Q",
) -> pd.DataFrame:
    """
    Розрахунок NOTSOLD_PERCENT per group: (тижні з Q=0) / (всього тижнів).

    Передумова: GAP FILLING вже виконано (всі тижні присутні з Q=0 для пропусків).

    Args:
        df_target: DataFrame target аптеки після gap filling.
        group_cols: Колонки групування (default: ['PHARM_ID', 'DRUGS_ID']).
        quantity_col: Колонка з кількістю.

    Returns:
        DataFrame з колонками group_cols + ['NOTSOLD_PERCENT'].
    """
    if group_cols is None:
        group_cols = ["PHARM_ID", "DRUGS_ID"]

    if df_target.empty:
        return pd.DataFrame(columns=group_cols + ["NOTSOLD_PERCENT"])

    notsold_stats = (
        df_target.groupby(group_cols)[quantity_col]
        .agg(
            total_weeks="count",
            zero_weeks=lambda x: (x == 0).sum(),
        )
        .reset_index()
    )
    notsold_stats["NOTSOLD_PERCENT"] = (
        notsold_stats["zero_weeks"] / notsold_stats["total_weeks"]
    )
    return notsold_stats[group_cols + ["NOTSOLD_PERCENT"]]


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ETL CORE — drug_substitution_engine (Phase A0/A1)")
    print("=" * 60)

    # 1. Date parsing
    print("\n[1] parse_period_id():")
    for pid in [202300001, 202400305, 202600104]:
        d = parse_period_id(pid)
        print(f"  {pid} -> {d.strftime('%Y-%m-%d (%A)')}")

    # 2. Convert numerics
    print("\n[2] convert_numeric_columns():")
    df_t = pd.DataFrame({"Q": ["1,5", "2,0", "0,75"], "V": ["100,5", "200", "50,25"]})
    df_t2 = convert_numeric_columns(df_t)
    print(df_t2.to_string(index=False))

    # 3. Gap filling
    print("\n[3] fill_gaps() with synthetic gaps:")
    dates = [
        datetime(2024, 1, 1),   # Mon
        datetime(2024, 1, 8),   # Mon
        datetime(2024, 1, 22),  # Mon (2 weeks gap → потрібно заповнити нулями)
    ]
    df_g = pd.DataFrame({
        "PHARM_ID":   [1, 1, 1],
        "DRUGS_ID":   [100, 100, 100],
        "Date":       dates,
        "Q":          [10.0, 5.0, 7.0],
        "V":          [100.0, 50.0, 70.0],
        "DRUGS_NAME": ["A", "A", "A"],
    })
    df_filled = fill_gaps(df_g)
    print(df_filled[["Date", "Q", "V"]].to_string(index=False))
    print(f"  Original rows: {len(df_g)}, after gap fill: {len(df_filled)}")
    print(f"  Has zeros (Q=0)? {(df_filled['Q'] == 0).any()}")

    # 4. NOTSOLD percent
    print("\n[4] calculate_notsold_percent():")
    notsold = calculate_notsold_percent(df_filled)
    print(notsold.to_string(index=False))

    print("\nAll ETL functions OK.")
