# =============================================================================
# DiD CORE - drug_substitution_engine
# =============================================================================
# Файл: core/did.py
# Дата: 2026-04-27
# Опис: Difference-in-Differences алгоритми (Phase A3).
# =============================================================================

"""
DiD utilities + main calculation для Phase A3.

Адаптовано з canonical/project_core/utility_functions/did_utils.py та
canonical/exec_scripts/01_did_processing/02_03_did_analysis.py
з ОДНИМ виправленням:

    LOST_SALES розрахунок:
        Канонічний: comp_pre = max(0, market_total_pre - target_pre)
        Наш:       comp_pre = market_total_pre  (без подвійного віднімання)

    Деталі: див. _methods_issues.md ISSUE-013

Функції:
    - define_post_period(...)        — визначити POST-період
    - calculate_market_growth(...)   — MARKET_GROWTH
    - calculate_expected(...)        — EXPECTED = sales_pre × growth
    - calculate_lift(...)            — LIFT = max(0, actual - expected)
    - calculate_shares(...)          — SHARE_INTERNAL/SHARE_LOST
    - find_valid_substitutes(...)    — NFC + Phantom filter
    - calculate_did_for_event(...)   — головний DiD розрахунок per event

Використання:
    from core.did import (
        define_post_period, calculate_did_for_event, find_valid_substitutes,
    )
"""

from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.nfc import is_compatible


# =============================================================================
# POST-PERIOD DEFINITION
# =============================================================================

def define_post_period(
    df_drug: pd.DataFrame,
    stockout_end: pd.Timestamp,
    min_post_weeks: int = 4,
    max_gap_weeks: int = 2,
    date_col: str = "Date",
    quantity_col: str = "Q",
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp], int, str]:
    """
    Визначити POST-період для stock-out події.

    POST починається з першого тижня з продажами після stockout_end,
    триває рівно min_post_weeks тижнів.

    Args:
        df_drug:        Дані одного DRUGS_ID у TARGET аптеці.
        stockout_end:   Дата кінця stockout.
        min_post_weeks: Мінімум тижнів POST-періоду.
        max_gap_weeks:  Максимальний gap до відновлення продажів.

    Returns:
        Tuple (post_start, post_end, post_weeks, status):
            status: 'valid' / 'no_recovery' / 'gap_too_large' / 'insufficient_data'
    """
    df_after = df_drug[df_drug[date_col] > stockout_end].sort_values(date_col)

    if len(df_after) == 0:
        return None, None, 0, "no_recovery"

    df_with_sales = df_after[df_after[quantity_col] > 0]
    if len(df_with_sales) == 0:
        return None, None, 0, "no_recovery"

    first_sale_date = df_with_sales[date_col].min()
    gap_weeks = (first_sale_date - stockout_end).days // 7
    if gap_weeks > max_gap_weeks:
        return None, None, 0, "gap_too_large"

    post_start = first_sale_date
    df_post = df_after[df_after[date_col] >= post_start]
    if len(df_post) < min_post_weeks:
        return None, None, len(df_post), "insufficient_data"

    post_end = df_post[date_col].iloc[min_post_weeks - 1]
    return post_start, post_end, min_post_weeks, "valid"


# =============================================================================
# MARKET GROWTH / EXPECTED / LIFT / SHARES
# =============================================================================

def calculate_market_growth(
    market_pre: float,
    market_during: float,
    min_market_pre: float = 1.0,
) -> float:
    """
    MARKET_GROWTH = MARKET_DURING / MARKET_PRE.

    Якщо MARKET_PRE < min_market_pre — повертаємо 1.0 (нейтрально).
    """
    if market_pre < min_market_pre:
        return 1.0
    return max(0.0, market_during / market_pre)


def calculate_expected(sales_pre: float, market_growth: float) -> float:
    """EXPECTED = max(0, sales_pre × market_growth)."""
    return max(0.0, sales_pre * market_growth)


def calculate_lift(actual: float, expected: float) -> float:
    """LIFT = max(0, actual - expected)."""
    return max(0.0, actual - expected)


def calculate_shares(
    internal_lift: float,
    lost_sales: float,
    min_total: float = 0.001,
) -> Tuple[float, float]:
    """
    SHARE_INTERNAL = INTERNAL_LIFT / TOTAL_EFFECT
    SHARE_LOST     = LOST_SALES / TOTAL_EFFECT

    Якщо TOTAL_EFFECT < min_total → (NaN, NaN).
    """
    total = internal_lift + lost_sales
    if total < min_total:
        return np.nan, np.nan
    return internal_lift / total, lost_sales / total


# =============================================================================
# SUBSTITUTE IDENTIFICATION
# =============================================================================

def find_valid_substitutes(
    drug_index: Dict[int, pd.DataFrame],
    target_drug_id: int,
    target_nfc1: str,
    stockout_start: pd.Timestamp,
    stockout_end: pd.Timestamp,
) -> List[Dict[str, Any]]:
    """
    Знайти валідні substitutes для stock-out події.

    Фільтри:
        1. NFC Compatibility: clinical compatibility check
        2. Phantom Filter:    substitute повинен мати дані під час stock-out
                              (інакше LIFT=0 артефактом)

    Args:
        drug_index:     Pre-built {DRUGS_ID: DataFrame} для TARGET аптеки.
        target_drug_id: ID stockout drug (виключаємо з substitutes).
        target_nfc1:    NFC1 stockout drug.
        stockout_start: Початок stockout.
        stockout_end:   Кінець stockout.

    Returns:
        List[Dict] із полями:
            SUBSTITUTE_DRUGS_ID, SUBSTITUTE_DRUGS_NAME, SUBSTITUTE_NFC1_ID, SAME_NFC1
    """
    valid: List[Dict[str, Any]] = []

    for drug_id, df_sub in drug_index.items():
        if drug_id == target_drug_id:
            continue
        if df_sub.empty:
            continue

        sub_nfc1 = df_sub["NFC1_ID"].iloc[0]
        sub_name = df_sub["DRUGS_NAME"].iloc[0]

        # Filter 1: NFC compatibility
        if not is_compatible(target_nfc1, sub_nfc1):
            continue

        # Filter 2: Phantom — substitute мав хоч якісь дані під час stockout
        df_during = df_sub[
            (df_sub["Date"] >= stockout_start) & (df_sub["Date"] <= stockout_end)
        ]
        if len(df_during) == 0:
            continue

        valid.append({
            "SUBSTITUTE_DRUGS_ID":   int(drug_id),
            "SUBSTITUTE_DRUGS_NAME": sub_name,
            "SUBSTITUTE_NFC1_ID":    sub_nfc1,
            "SAME_NFC1":             bool(target_nfc1 == sub_nfc1),
        })

    return valid


# =============================================================================
# MAIN DiD CALCULATION (per event)
# =============================================================================

def calculate_did_for_event(
    df_inn: pd.DataFrame,
    drug_index: Dict[int, pd.DataFrame],
    target_drug_id: int,
    valid_substitutes: List[Dict[str, Any]],
    pre_start: pd.Timestamp,
    pre_end: pd.Timestamp,
    stockout_start: pd.Timestamp,
    stockout_end: pd.Timestamp,
    min_market_pre: float = 1.0,
    min_total_for_share: float = 0.001,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Розрахувати DiD метрики для однієї stock-out події.

    КРИТИЧНО: ЦЕ МАТЕМАТИЧНО ВИПРАВЛЕНА ВЕРСІЯ канонічного.
    Див. _methods_issues.md ISSUE-013 — у канонічному код віднімав target_pre
    від уже-конкуренти-only MARKET_TOTAL_DRUGS_PACK, що подвійно віднімало target.

    Algorithm:
        1. MARKET_GROWTH (INN-level): sum(MARKET_TOTAL для всієї INN PRE → DURING)
        2. Per substitute: sales_pre, sales_during → EXPECTED → LIFT
        3. INTERNAL_LIFT = sum(LIFT по substitutes)
        4. LOST_SALES (FIXED):
            comp_pre     = MARKET_TOTAL_DRUGS_PACK для target_drug у PRE (already competitors-only)
            comp_during  = MARKET_TOTAL_DRUGS_PACK для target_drug у DURING
            comp_expected = comp_pre × MARKET_GROWTH
            lost_sales    = max(0, comp_during - comp_expected)
        5. SHARE_INTERNAL = INTERNAL_LIFT / TOTAL_EFFECT

    Args:
        df_inn:            Дані всієї INN (target only — як після Phase A1).
        drug_index:        {DRUGS_ID: DataFrame} pre-built для TARGET у цій INN.
        target_drug_id:    ID stockout препарату.
        valid_substitutes: Результат find_valid_substitutes().
        pre_start, pre_end:        PRE-період.
        stockout_start, stockout_end: DURING-період.
        min_market_pre:    Поріг MARKET_PRE для безпечного MARKET_GROWTH.
        min_total_for_share: Поріг TOTAL_EFFECT для розрахунку SHARE.

    Returns:
        Tuple (event_metrics, substitute_pairs):
            event_metrics — Dict для did_events.parquet
            substitute_pairs — List[Dict] для substitute_pairs.parquet
                               (включно з LIFT для Phase A4 reuse)
    """
    # =========================================================================
    # 1. MARKET_GROWTH (INN-level)
    # =========================================================================
    df_market_pre = df_inn[
        (df_inn["Date"] >= pre_start) & (df_inn["Date"] <= pre_end)
    ]
    market_pre = float(df_market_pre["MARKET_TOTAL_DRUGS_PACK"].sum())

    df_market_during = df_inn[
        (df_inn["Date"] >= stockout_start) & (df_inn["Date"] <= stockout_end)
    ]
    market_during = float(df_market_during["MARKET_TOTAL_DRUGS_PACK"].sum())

    market_growth = calculate_market_growth(market_pre, market_during, min_market_pre)

    # =========================================================================
    # 2. Per substitute LIFT
    # =========================================================================
    substitute_pairs: List[Dict[str, Any]] = []
    internal_lift = 0.0
    substitutes_with_lift = 0

    for sub in valid_substitutes:
        sub_drug_id = sub["SUBSTITUTE_DRUGS_ID"]
        df_sub = drug_index.get(sub_drug_id)
        if df_sub is None or df_sub.empty:
            continue

        df_sub_pre = df_sub[(df_sub["Date"] >= pre_start) & (df_sub["Date"] <= pre_end)]
        sales_pre = float(df_sub_pre["Q"].sum())

        df_sub_during = df_sub[
            (df_sub["Date"] >= stockout_start) & (df_sub["Date"] <= stockout_end)
        ]
        sales_during = float(df_sub_during["Q"].sum())

        expected = calculate_expected(sales_pre, market_growth)
        lift = calculate_lift(sales_during, expected)

        internal_lift += lift
        if lift > 0:
            substitutes_with_lift += 1

        substitute_pairs.append({
            "SUBSTITUTE_DRUGS_ID":   sub["SUBSTITUTE_DRUGS_ID"],
            "SUBSTITUTE_DRUGS_NAME": sub["SUBSTITUTE_DRUGS_NAME"],
            "SUBSTITUTE_NFC1_ID":    sub["SUBSTITUTE_NFC1_ID"],
            "SAME_NFC1":             sub["SAME_NFC1"],
            "SALES_PRE":             round(sales_pre, 4),
            "SALES_DURING":          round(sales_during, 4),
            "EXPECTED":              round(expected, 4),
            "LIFT":                  round(lift, 4),
        })

    # =========================================================================
    # 3. LOST_SALES (FIXED — без подвійного віднімання target_pre)
    # =========================================================================
    df_target_drug = drug_index.get(target_drug_id)

    if df_target_drug is not None and not df_target_drug.empty:
        # PRE-період
        df_drug_pre = df_target_drug[
            (df_target_drug["Date"] >= pre_start) & (df_target_drug["Date"] <= pre_end)
        ]
        # FIX: MARKET_TOTAL_DRUGS_PACK вже competitors-only → використовуємо напряму
        comp_pre = float(df_drug_pre["MARKET_TOTAL_DRUGS_PACK"].sum())

        # DURING-період
        df_drug_during = df_target_drug[
            (df_target_drug["Date"] >= stockout_start) & (df_target_drug["Date"] <= stockout_end)
        ]
        comp_during = float(df_drug_during["MARKET_TOTAL_DRUGS_PACK"].sum())
    else:
        comp_pre = 0.0
        comp_during = 0.0

    comp_expected = calculate_expected(comp_pre, market_growth)
    lost_sales = calculate_lift(comp_during, comp_expected)

    # =========================================================================
    # 4. SHARES
    # =========================================================================
    total_effect = internal_lift + lost_sales
    share_internal, share_lost = calculate_shares(
        internal_lift, lost_sales, min_total_for_share
    )

    # =========================================================================
    # 5. Збір event metrics
    # =========================================================================
    event_metrics: Dict[str, Any] = {
        "MARKET_PRE":            round(market_pre, 2),
        "MARKET_DURING":         round(market_during, 2),
        "MARKET_GROWTH":         round(market_growth, 6),
        "INTERNAL_LIFT":         round(internal_lift, 4),
        "LOST_SALES":            round(lost_sales, 4),
        "TOTAL_EFFECT":          round(total_effect, 4),
        "SHARE_INTERNAL":        round(share_internal, 6) if not np.isnan(share_internal) else np.nan,
        "SHARE_LOST":            round(share_lost, 6) if not np.isnan(share_lost) else np.nan,
        "SUBSTITUTES_COUNT":     len(valid_substitutes),
        "SUBSTITUTES_WITH_LIFT": substitutes_with_lift,
    }

    return event_metrics, substitute_pairs


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("DiD CORE — drug_substitution_engine (Phase A3)")
    print("=" * 60)

    # Test calculate_market_growth
    print("\n[1] calculate_market_growth():")
    print(f"  market_pre=100, during=120 -> {calculate_market_growth(100, 120):.3f}")
    print(f"  market_pre=0.5, during=2   -> {calculate_market_growth(0.5, 2):.3f} (fallback to 1.0)")

    # Test calculate_lift
    print("\n[2] calculate_lift():")
    print(f"  actual=150, expected=100 -> {calculate_lift(150, 100):.1f}")
    print(f"  actual=80,  expected=100 -> {calculate_lift(80, 100):.1f} (clipped to 0)")

    # Test calculate_shares
    print("\n[3] calculate_shares():")
    sh_int, sh_lost = calculate_shares(70, 30)
    print(f"  internal=70, lost=30 -> SHARE_INTERNAL={sh_int:.3f}, SHARE_LOST={sh_lost:.3f}")
    sh_int, sh_lost = calculate_shares(0, 0)
    print(f"  internal=0, lost=0   -> SHARE_INTERNAL={sh_int}, SHARE_LOST={sh_lost} (NaN)")

    # Test define_post_period (synthetic)
    print("\n[4] define_post_period():")
    test_df = pd.DataFrame({
        "Date": pd.to_datetime([
            "2024-01-01", "2024-01-08", "2024-01-15",  # PRE / stockout
            "2024-01-22", "2024-01-29", "2024-02-05",  # POST candidate
            "2024-02-12", "2024-02-19", "2024-02-26",
        ]),
        "Q": [10, 0, 0,  5, 7, 6,  8, 9, 4],  # stockout 2 weeks, then sales
    })
    post_start, post_end, post_weeks, status = define_post_period(
        test_df, stockout_end=pd.Timestamp("2024-01-15"), min_post_weeks=4, max_gap_weeks=2
    )
    print(f"  POST: {post_start.date()} -> {post_end.date()} ({post_weeks} weeks, status={status})")

    print("\nAll DiD core OK.")
