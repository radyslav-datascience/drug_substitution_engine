# =============================================================================
# STOCKOUT DETECTION CORE - drug_substitution_engine
# =============================================================================
# Файл: core/stockout.py
# Дата: 2026-04-27
# Опис: Алгоритми виявлення та валідації stock-out подій (Phase A2).
# =============================================================================

"""
Stockout detection algorithms для Phase A2.

Скопійовано 1-в-1 з канонічного `02_02_stockout_detection.py`
без змін у формулах та логіці (методологія валідована).
Документовані слабкі місця методології — у `_methods_issues.md` (ISSUE-006...012).

Функції:
    - identify_stockout_periods(df_drug)  — vectorized: знайти Q=0 sequences
    - validate_stockout_event(df_drug, df_inn, ...) — 3-рівнева валідація:
        Level 1: Market Activity (INN-level)
        Level 2: PRE-period Sales (drug-level)
        Level 3: Competitors Availability (drug-level)

Використання:
    from core.stockout import identify_stockout_periods, validate_stockout_event
"""

from typing import Dict, List, Tuple

import pandas as pd

from config.stockout_params import MIN_STOCKOUT_WEEKS, MIN_PRE_PERIOD_WEEKS


# =============================================================================
# STOCKOUT IDENTIFICATION (vectorized)
# =============================================================================

def identify_stockout_periods(
    df_drug: pd.DataFrame,
    min_stockout_weeks: int = MIN_STOCKOUT_WEEKS,
) -> List[Dict]:
    """
    Ідентифікувати періоди stock-out для одного препарату (vectorized).

    Stock-out = тиждень без продажів (Q == 0).
    Період stock-out = послідовні тижні з Q=0.

    Алгоритм через diff() + cumsum() — швидко на великих DataFrame.

    Args:
        df_drug: Дані одного препарату (DRUGS_ID) з колонками 'Date', 'Q'.
        min_stockout_weeks: Мінімальна тривалість stock-out для реєстрації.

    Returns:
        List[Dict]: [{'start': Timestamp, 'end': Timestamp, 'weeks': int}, ...]
    """
    if len(df_drug) == 0:
        return []

    # Сортуємо по датах (потрібно для коректного diff/cumsum)
    df_sorted = df_drug[["Date", "Q"]].sort_values("Date").reset_index(drop=True)

    # Vectorized: визначаємо тижні без продажів
    is_zero = (df_sorted["Q"] == 0).astype(int)

    # Якщо взагалі немає нулів -> немає stockout
    if is_zero.sum() == 0:
        return []

    # Групуємо послідовні стани: diff() != 0 означає зміну стану (sale ↔ no-sale).
    # cumsum() дає унікальний ID кожній безперервній групі.
    state_change = is_zero.diff().fillna(is_zero.iloc[0]).ne(0).cumsum()

    df_sorted["_group"] = state_change
    df_sorted["_is_zero"] = is_zero

    # Беремо лише групи з Q=0
    zero_groups = df_sorted[df_sorted["_is_zero"] == 1].groupby("_group")

    stockout_periods: List[Dict] = []
    for _, group in zero_groups:
        weeks = len(group)
        if weeks >= min_stockout_weeks:
            stockout_periods.append({
                "start": group["Date"].iloc[0],
                "end":   group["Date"].iloc[-1],
                "weeks": weeks,
            })

    return stockout_periods


# =============================================================================
# 3-LEVEL VALIDATION
# =============================================================================

def validate_stockout_event(
    df_drug: pd.DataFrame,
    df_inn: pd.DataFrame,
    stockout_start: pd.Timestamp,
    stockout_end: pd.Timestamp,
    pre_start: pd.Timestamp,
    pre_end: pd.Timestamp,
    min_pre_weeks: int = MIN_PRE_PERIOD_WEEKS,
) -> Tuple[bool, str, Dict]:
    """
    3-рівнева валідація stock-out події.

    Перевірки (детальний опис у ALGORITHMS.md та _methods_issues.md):

        LEVEL 1 — Market Activity (INN group level):
            Чи активна INN група під час stockout?
            (консистентність із MARKET_GROWTH у Phase A3)

        LEVEL 2 — PRE-period Sales (drug level):
            Чи були продажі ЦЬОГО препарату до stockout?
            (необхідність baseline для DiD)

        LEVEL 3 — Competitors Availability (drug level):
            Чи продавали конкуренти ЦЕЙ препарат під час stockout?
            (для коректного SHARE_LOST)

    Args:
        df_drug:        Дані одного DRUGS_ID у TARGET аптеці (тижневі, з gap fill).
        df_inn:         Дані всієї INN групи (для Level 1).
        stockout_start: Початок stockout (Timestamp).
        stockout_end:   Кінець stockout (Timestamp).
        pre_start:      Початок PRE-періоду (Timestamp).
        pre_end:        Кінець PRE-періоду (Timestamp).
        min_pre_weeks:  Мінімум тижнів у PRE-періоді.

    Returns:
        Tuple[bool, str, Dict]:
            is_valid — True якщо подія пройшла всі 3 рівні
            reason   — 'valid' | 'no_market_activity' | 'no_pre_sales' | 'no_competitors'
            details  — словник із розрахованими метриками
                       (market_during_inn, pre_sales, pre_weeks, competitors_sales,
                        pre_avg_q при is_valid)
    """
    details: Dict[str, float] = {}

    # =====================================================
    # LEVEL 1 — Market Activity (INN-level)
    # =====================================================
    df_inn_during = df_inn[
        (df_inn["Date"] >= stockout_start) & (df_inn["Date"] <= stockout_end)
    ]
    market_during_inn = float(df_inn_during["MARKET_TOTAL_DRUGS_PACK"].sum())
    details["market_during_inn"] = market_during_inn

    if market_during_inn == 0:
        return False, "no_market_activity", details

    # =====================================================
    # LEVEL 2 — PRE-period Sales (drug-level)
    # =====================================================
    df_pre = df_drug[(df_drug["Date"] >= pre_start) & (df_drug["Date"] <= pre_end)]
    pre_sales = float(df_pre["Q"].sum())
    pre_weeks = int(len(df_pre))
    details["pre_sales"] = pre_sales
    details["pre_weeks"] = pre_weeks

    if pre_weeks < min_pre_weeks or pre_sales == 0:
        return False, "no_pre_sales", details

    # =====================================================
    # LEVEL 3 — Competitors Availability (drug-level)
    # =====================================================
    df_drug_during = df_drug[
        (df_drug["Date"] >= stockout_start) & (df_drug["Date"] <= stockout_end)
    ]
    competitors_sales = float(df_drug_during["MARKET_TOTAL_DRUGS_PACK"].sum())
    details["competitors_sales"] = competitors_sales

    if competitors_sales == 0:
        return False, "no_competitors", details

    # =====================================================
    # ВСЕ ПРОЙДЕНО
    # =====================================================
    details["pre_avg_q"] = pre_sales / pre_weeks if pre_weeks > 0 else 0.0
    return True, "valid", details


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    from datetime import datetime

    print("=" * 60)
    print("STOCKOUT CORE — drug_substitution_engine (Phase A2)")
    print("=" * 60)

    # Synthetic test
    print("\n[1] identify_stockout_periods():")
    test_data = pd.DataFrame({
        "Date": pd.to_datetime([
            "2024-01-01", "2024-01-08", "2024-01-15",  # sales
            "2024-01-22", "2024-01-29", "2024-02-05",  # stockout (3 weeks)
            "2024-02-12", "2024-02-19",                # sales
            "2024-02-26", "2024-03-04",                # stockout (2 weeks)
            "2024-03-11",                              # sales
        ]),
        "Q": [10, 5, 8,  0, 0, 0,  6, 7,  0, 0,  9],
    })
    periods = identify_stockout_periods(test_data, min_stockout_weeks=1)
    for i, p in enumerate(periods, 1):
        print(f"  Period {i}: {p['start'].date()} -> {p['end'].date()} ({p['weeks']} weeks)")

    print("\n  Edge cases:")
    print(f"  Empty df -> {len(identify_stockout_periods(pd.DataFrame({'Date':[], 'Q':[]})))} periods")
    print(f"  No zeros -> {len(identify_stockout_periods(pd.DataFrame({'Date':pd.to_datetime(['2024-01-01']), 'Q':[5]})))} periods")
    print(f"  min_stockout_weeks=2 (filters short stockouts):")
    periods2 = identify_stockout_periods(test_data, min_stockout_weeks=3)
    print(f"    Found {len(periods2)} periods (only 3-week stockout, 2-week filtered)")
    for p in periods2:
        print(f"      {p['start'].date()} -> {p['end'].date()} ({p['weeks']} weeks)")

    print("\nAll OK.")
