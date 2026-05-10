# =============================================================================
# PER-MARKET PROCESSING - drug_substitution_engine / Phase A1 + A2 + A3 + A4
# =============================================================================
# Файл: pipeline/per_market.py
# Дата: 2026-04-27 (extended for Phase A4)
# Опис: Phase A1 (data agg) + A2 (stockout) + A3 (DiD) + A4 (substitutes) per market.
# =============================================================================

"""
Per-market processing для Phase A1+A2+A3+A4.

Phase A1: {CLIENT_ID}.csv              -> aggregated.parquet
Phase A2: aggregated.parquet            -> stockout_events.parquet
Phase A3: aggregated + stockout_events  -> did_events.parquet + substitute_pairs.parquet
Phase A4: substitute_pairs + stockout   -> substitute_shares.parquet

Використання:
    python -m pipeline.per_market a1 --market-id 763807
    python -m pipeline.per_market a2 --market-id 763807
    python -m pipeline.per_market a3 --market-id 763807
    python -m pipeline.per_market a4 --market-id 763807
    python -m pipeline.per_market {a1|a2|a3|a4} --limit 3
"""

import argparse
import gc
import sys
import time
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Project root
SCRIPT_PATH  = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.paths import (
    CSV_SEPARATOR,
    PER_MARKET_PATH,
    get_market_intermediate_dir,
    load_markets_list,
    ensure_directories,
)
from config.column_mapping import (
    COLUMN_RENAME_MAP,
    NUMERIC_COLUMNS,
    CATEGORICAL_COLUMNS,
    USEFUL_COLUMNS,
)
from config.stockout_params import (
    MIN_NOTSOLD_PERCENT,
    MAX_NOTSOLD_PERCENT,
    MIN_STOCKOUT_WEEKS,
    MIN_PRE_PERIOD_WEEKS,
    MIN_POST_PERIOD_WEEKS,
    MAX_POST_GAP_WEEKS,
    MIN_MARKET_PRE,
    MIN_TOTAL_FOR_SHARE,
)
from core.etl import (
    convert_numeric_columns,
    rename_columns,
    add_date_column,
    fill_gaps,
    aggregate_weekly,
    calculate_market_totals,
    calculate_notsold_percent,
)
from core.stockout import (
    identify_stockout_periods,
    validate_stockout_event,
)
from core.did import (
    define_post_period,
    find_valid_substitutes,
    calculate_did_for_event,
)
from core.io_utils import phase_output_valid


# =============================================================================
# OUTPUT FILES
# =============================================================================

AGGREGATED_PARQUET        = "aggregated.parquet"
STOCKOUT_EVENTS_PARQUET   = "stockout_events.parquet"
DID_EVENTS_PARQUET        = "did_events.parquet"
SUBSTITUTE_PAIRS_PARQUET  = "substitute_pairs.parquet"
SUBSTITUTE_SHARES_PARQUET = "substitute_shares.parquet"
PARQUET_ENGINE            = "pyarrow"
PARQUET_COMPRESS          = "snappy"


def get_aggregated_parquet_path(client_id: int) -> Path:
    return get_market_intermediate_dir(client_id) / AGGREGATED_PARQUET


def get_stockout_parquet_path(client_id: int) -> Path:
    return get_market_intermediate_dir(client_id) / STOCKOUT_EVENTS_PARQUET


def get_did_events_path(client_id: int) -> Path:
    return get_market_intermediate_dir(client_id) / DID_EVENTS_PARQUET


def get_substitute_pairs_path(client_id: int) -> Path:
    return get_market_intermediate_dir(client_id) / SUBSTITUTE_PAIRS_PARQUET


def get_substitute_shares_path(client_id: int) -> Path:
    return get_market_intermediate_dir(client_id) / SUBSTITUTE_SHARES_PARQUET


# Колонки stockout_events.parquet (14 — без NFC_ID, MARKET_DURING_Q)
STOCKOUT_EVENTS_COLUMNS = [
    "EVENT_ID",
    "CLIENT_ID",
    "INN_ID", "INN_NAME",
    "DRUGS_ID", "DRUGS_NAME",
    "NFC1_ID",
    "STOCKOUT_START", "STOCKOUT_END", "STOCKOUT_WEEKS",
    "PRE_START", "PRE_END", "PRE_WEEKS", "PRE_AVG_Q",
]

# Колонки did_events.parquet (20)
DID_EVENTS_COLUMNS = [
    "EVENT_ID",
    "CLIENT_ID",
    "INN_ID",
    "DRUGS_ID", "DRUGS_NAME",
    "NFC1_ID",
    "POST_START", "POST_END", "POST_WEEKS", "POST_STATUS",
    "MARKET_PRE", "MARKET_DURING", "MARKET_GROWTH",
    "INTERNAL_LIFT", "LOST_SALES", "TOTAL_EFFECT",
    "SHARE_INTERNAL", "SHARE_LOST",
    "SUBSTITUTES_COUNT", "SUBSTITUTES_WITH_LIFT",
]

# Колонки substitute_pairs.parquet (14)
SUBSTITUTE_PAIRS_COLUMNS = [
    "EVENT_ID",
    "CLIENT_ID",
    "INN_ID",
    "TARGET_DRUGS_ID", "TARGET_DRUGS_NAME", "TARGET_NFC1_ID",
    "SUBSTITUTE_DRUGS_ID", "SUBSTITUTE_DRUGS_NAME", "SUBSTITUTE_NFC1_ID",
    "SAME_NFC1",
    "SALES_PRE", "SALES_DURING", "EXPECTED", "LIFT",
]

# Колонки substitute_shares.parquet (15)
SUBSTITUTE_SHARES_COLUMNS = [
    "CLIENT_ID",
    "INN_ID", "INN_NAME",
    "STOCKOUT_DRUG_ID", "STOCKOUT_DRUG_NAME", "STOCKOUT_NFC1_ID",
    "SUBSTITUTE_DRUG_ID", "SUBSTITUTE_DRUG_NAME", "SUBSTITUTE_NFC1_ID",
    "SAME_NFC1",
    "TOTAL_LIFT", "INTERNAL_LIFT", "SUBSTITUTE_SHARE",
    "EVENTS_COUNT", "SUBSTITUTE_RANK",
]


# =============================================================================
# PHASE A1: process_inn (per-INN processing within Phase A1)
# =============================================================================

def process_inn_a1(
    df_inn: pd.DataFrame,
    inn_id: int,
    client_id: int,
) -> Optional[pd.DataFrame]:
    """
    Phase A1: gap fill → aggregate → split → NOTSOLD filter → market_totals → merge.

    Args:
        df_inn:    DataFrame одного INN (target + competitors).
        inn_id:    ID INN групи.
        client_id: ID цільової аптеки.

    Returns:
        DataFrame з target rows + MARKET_TOTAL колонками, або None якщо немає valid drugs.
    """
    cat_cols = CATEGORICAL_COLUMNS + ["INN_ID"]
    df_filled = fill_gaps(
        df_inn,
        group_cols=["PHARM_ID", "DRUGS_ID"],
        date_col="Date",
        value_cols=["Q", "V"],
        categorical_cols=cat_cols,
    )

    df_agg = aggregate_weekly(
        df_filled,
        group_cols=["PHARM_ID", "DRUGS_ID", "Date"],
        sum_cols=["Q", "V"],
        first_cols=["DRUGS_NAME", "INN_NAME", "INN_ID", "NFC1_ID", "NFC_ID"],
    )

    df_target      = df_agg[df_agg["PHARM_ID"] == client_id].copy()
    df_competitors = df_agg[df_agg["PHARM_ID"] != client_id].copy()

    if df_target.empty:
        return None

    notsold = calculate_notsold_percent(
        df_target,
        group_cols=["PHARM_ID", "DRUGS_ID"],
        quantity_col="Q",
    )
    df_target = df_target.merge(
        notsold[["PHARM_ID", "DRUGS_ID", "NOTSOLD_PERCENT"]],
        on=["PHARM_ID", "DRUGS_ID"],
        how="left",
    )

    valid_drugs = notsold[
        (notsold["NOTSOLD_PERCENT"] >= MIN_NOTSOLD_PERCENT) &
        (notsold["NOTSOLD_PERCENT"] <= MAX_NOTSOLD_PERCENT)
    ]["DRUGS_ID"].unique()

    df_target      = df_target[df_target["DRUGS_ID"].isin(valid_drugs)].copy()
    df_competitors = df_competitors[df_competitors["DRUGS_ID"].isin(valid_drugs)].copy()

    if df_target.empty:
        return None

    market_totals = calculate_market_totals(
        df_competitors,
        date_col="Date", drug_col="DRUGS_ID",
        quantity_col="Q", value_col="V",
    )
    df_final = df_target.merge(
        market_totals,
        on=["Date", "DRUGS_ID"],
        how="left",
    )
    df_final["MARKET_TOTAL_DRUGS_PACK"]    = df_final["MARKET_TOTAL_DRUGS_PACK"].fillna(0)
    df_final["MARKET_TOTAL_DRUGS_REVENUE"] = df_final["MARKET_TOTAL_DRUGS_REVENUE"].fillna(0)

    return df_final


# =============================================================================
# PHASE A1: process_market (orchestrator)
# =============================================================================

def process_market_a1(
    client_id: int,
    file_path: Path,
) -> Dict[str, Any]:
    """
    Phase A1: Обробити один ринок (load → process all INN → save parquet).

    Returns:
        Dict із результатами та метриками.
    """
    t0 = time.time()
    result: Dict[str, Any] = {
        "phase":          "A1",
        "client_id":      client_id,
        "status":         "error",
        "elapsed_sec":    0.0,
        "raw_rows":       0,
        "output_rows":    0,
        "inn_processed":  0,
        "inn_skipped":    0,
        "drugs_count":    0,
        "output_path":    "",
        "output_size_mb": 0.0,
        "drugs_df":       pd.DataFrame(columns=["DRUGS_ID", "DRUGS_NAME"]),
        "error":          None,
    }

    try:
        # ISSUE-005 fix: читаємо тільки 11 потрібних колонок (без ATC) для економії I/O.
        df_raw = pd.read_csv(file_path, sep=CSV_SEPARATOR, usecols=USEFUL_COLUMNS)
        result["raw_rows"] = len(df_raw)

        if int(df_raw["CLIENT_ID"].iloc[0]) != client_id:
            result["error"] = (
                f"CLIENT_ID mismatch: expected {client_id}, "
                f"got {df_raw['CLIENT_ID'].iloc[0]}"
            )
            return result

        df = rename_columns(df_raw, COLUMN_RENAME_MAP)
        del df_raw
        df = convert_numeric_columns(df, NUMERIC_COLUMNS)
        df = add_date_column(df, period_col="PERIOD_ID", date_col="Date", align_monday=True)

        inn_ids = df["INN_ID"].unique()
        per_inn_dfs: List[pd.DataFrame] = []

        for inn_id in inn_ids:
            df_inn = df[df["INN_ID"] == inn_id]
            df_processed = process_inn_a1(df_inn, inn_id, client_id)
            if df_processed is None or df_processed.empty:
                result["inn_skipped"] += 1
            else:
                per_inn_dfs.append(df_processed)
                result["inn_processed"] += 1

        if not per_inn_dfs:
            result["status"] = "no_data"
            result["elapsed_sec"] = round(time.time() - t0, 2)
            return result

        df_market = pd.concat(per_inn_dfs, ignore_index=True)
        del per_inn_dfs, df
        gc.collect()

        drugs_df = (
            df_market[["DRUGS_ID", "DRUGS_NAME"]]
            .drop_duplicates(subset=["DRUGS_ID"])
            .sort_values("DRUGS_ID")
            .reset_index(drop=True)
        )
        result["drugs_df"]    = drugs_df
        result["drugs_count"] = len(drugs_df)
        result["output_rows"] = len(df_market)

        out_dir = get_market_intermediate_dir(client_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / AGGREGATED_PARQUET
        df_market.to_parquet(out_path, engine=PARQUET_ENGINE, compression=PARQUET_COMPRESS, index=False)

        result["output_path"]    = str(out_path)
        result["output_size_mb"] = round(out_path.stat().st_size / (1024 * 1024), 2)
        result["status"]         = "success"

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()

    result["elapsed_sec"] = round(time.time() - t0, 2)
    return result


# =============================================================================
# PHASE A2: process_market_stockout (orchestrator)
# =============================================================================

def process_market_stockout(
    client_id: int,
) -> Dict[str, Any]:
    """
    Phase A2: Виявлення stock-out подій для одного ринку.

    Вхід:  data/intermediate/01_per_market/{CLIENT_ID}/aggregated.parquet
    Вихід: data/intermediate/01_per_market/{CLIENT_ID}/stockout_events.parquet

    Алгоритм:
        1. Читаємо aggregated.parquet
        2. Group by INN_ID → для кожного INN:
           - Group by DRUGS_ID → для кожного drug:
             - identify_stockout_periods()
             - Для кожного period: визначити PRE-period, validate (3-level)
             - Якщо valid → додати до events
        3. Save stockout_events.parquet

    Args:
        client_id: ID цільової аптеки.

    Returns:
        Dict із результатами та метриками валідації:
            client_id, status, elapsed_sec, raw_events, valid_events,
            validation_stats {valid, no_market_activity, no_pre_sales, no_competitors},
            inn_processed, drugs_with_events, output_path, output_size_mb, error
    """
    t0 = time.time()
    result: Dict[str, Any] = {
        "phase":             "A2",
        "client_id":         client_id,
        "status":            "error",
        "elapsed_sec":       0.0,
        "raw_events":        0,
        "valid_events":      0,
        "validation_stats":  {
            "valid": 0,
            "no_market_activity": 0,
            "no_pre_sales": 0,
            "no_competitors": 0,
        },
        "inn_processed":     0,
        "drugs_with_events": 0,
        "output_path":       "",
        "output_size_mb":    0.0,
        "error":             None,
    }

    try:
        in_path = get_aggregated_parquet_path(client_id)
        if not in_path.exists():
            result["error"] = (
                f"aggregated.parquet not found at {in_path}\n"
                f"Run Phase A1 first: python -m pipeline.per_market a1 --market-id {client_id}"
            )
            return result

        df = pd.read_parquet(in_path, engine=PARQUET_ENGINE)
        if df.empty:
            result["status"] = "no_data"
            result["error"]  = "aggregated.parquet is empty (no valid drugs from Phase A1)"
            result["elapsed_sec"] = round(time.time() - t0, 2)
            return result

        # Подія-counter (per market)
        all_events: List[Dict[str, Any]] = []
        event_counter = 1

        # Loop по INN
        for inn_id_val, df_inn in df.groupby("INN_ID"):
            inn_id   = int(inn_id_val)  # INN_ID dtype=float64 quirk → cast (ISSUE-002)
            inn_name = df_inn["INN_NAME"].iloc[0] if "INN_NAME" in df_inn.columns else ""
            result["inn_processed"] += 1

            drugs_with_events_in_inn = set()

            # Loop по drugs у цій INN
            for drug_id, df_drug in df_inn.groupby("DRUGS_ID"):
                if df_drug.empty:
                    continue

                drug_name = df_drug["DRUGS_NAME"].iloc[0]
                nfc1_id   = df_drug["NFC1_ID"].iloc[0] if "NFC1_ID" in df_drug.columns else ""

                stockout_periods = identify_stockout_periods(df_drug, MIN_STOCKOUT_WEEKS)

                for period in stockout_periods:
                    result["raw_events"] += 1

                    # Визначення PRE-періоду:
                    #   pre_end   = stockout_start - 7 days  (1 тиждень gap)
                    #   pre_start = pre_end - (MIN_PRE_PERIOD_WEEKS - 1) тижнів
                    pre_end   = period["start"] - timedelta(days=7)
                    pre_start = pre_end - timedelta(weeks=MIN_PRE_PERIOD_WEEKS - 1)

                    is_valid, reason, details = validate_stockout_event(
                        df_drug=df_drug,
                        df_inn=df_inn,
                        stockout_start=period["start"],
                        stockout_end=period["end"],
                        pre_start=pre_start,
                        pre_end=pre_end,
                        min_pre_weeks=MIN_PRE_PERIOD_WEEKS,
                    )

                    result["validation_stats"][reason] += 1

                    if is_valid:
                        result["valid_events"] += 1
                        drugs_with_events_in_inn.add(int(drug_id))

                        all_events.append({
                            "EVENT_ID":       f"{client_id}_{inn_id}_{event_counter:04d}",
                            "CLIENT_ID":      client_id,
                            "INN_ID":         inn_id,
                            "INN_NAME":       inn_name,
                            "DRUGS_ID":       int(drug_id),
                            "DRUGS_NAME":     drug_name,
                            "NFC1_ID":        nfc1_id,
                            "STOCKOUT_START": period["start"],     # datetime64[ns]
                            "STOCKOUT_END":   period["end"],
                            "STOCKOUT_WEEKS": int(period["weeks"]),
                            "PRE_START":      pre_start,
                            "PRE_END":        pre_end,
                            "PRE_WEEKS":      int(details["pre_weeks"]),
                            "PRE_AVG_Q":      round(float(details["pre_avg_q"]), 4),
                        })
                        event_counter += 1

            result["drugs_with_events"] += len(drugs_with_events_in_inn)

        # Зберігаємо stockout_events.parquet (навіть якщо empty — для resume signal)
        if all_events:
            df_events = pd.DataFrame(all_events, columns=STOCKOUT_EVENTS_COLUMNS)
        else:
            # Empty DataFrame з правильною схемою
            df_events = pd.DataFrame(columns=STOCKOUT_EVENTS_COLUMNS)

        out_dir  = get_market_intermediate_dir(client_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / STOCKOUT_EVENTS_PARQUET
        df_events.to_parquet(out_path, engine=PARQUET_ENGINE, compression=PARQUET_COMPRESS, index=False)

        result["output_path"]    = str(out_path)
        result["output_size_mb"] = round(out_path.stat().st_size / (1024 * 1024), 2)
        result["status"]         = "success" if all_events else "no_data"

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()

    result["elapsed_sec"] = round(time.time() - t0, 2)
    return result


# =============================================================================
# PHASE A3: process_market_did (orchestrator)
# =============================================================================

def process_market_did(client_id: int) -> Dict[str, Any]:
    """
    Phase A3: DiD аналіз для одного ринку.

    Вхід:
        data/intermediate/01_per_market/{CLIENT_ID}/aggregated.parquet
        data/intermediate/01_per_market/{CLIENT_ID}/stockout_events.parquet

    Вихід:
        did_events.parquet         — event-level DiD metrics
        substitute_pairs.parquet   — per-substitute LIFT (для Phase A4)

    Алгоритм:
        1. Читання обох parquet.
        2. Group events by INN_ID; для кожного INN:
           - Build drug_index for fast lookup
           - For each event:
             a. POST-period: define_post_period(); reject 'no_post_period' якщо invalid
             b. find_valid_substitutes() — NFC + Phantom filter
             c. calculate_did_for_event() — основна DiD logic (з ISSUE-013 FIX)
             d. Reject 'no_effect' якщо TOTAL_EFFECT < MIN_TOTAL_FOR_SHARE
             e. Append to results
        3. Save 2 parquet.

    Returns:
        Dict із результатами та метриками валідації.
    """
    t0 = time.time()
    result: Dict[str, Any] = {
        "phase":              "A3",
        "client_id":          client_id,
        "status":             "error",
        "elapsed_sec":        0.0,
        "events_input":       0,
        "valid_events":       0,
        "validation_stats":   {
            "valid": 0,
            "no_post_period": 0,
            "no_substitutes": 0,
            "no_effect": 0,
        },
        "substitute_pairs_count": 0,
        "did_output_path":         "",
        "did_output_size_mb":      0.0,
        "subs_output_path":        "",
        "subs_output_size_mb":     0.0,
        "error":              None,
    }

    try:
        agg_path = get_aggregated_parquet_path(client_id)
        evt_path = get_stockout_parquet_path(client_id)

        if not agg_path.exists():
            result["error"] = (
                f"aggregated.parquet not found: {agg_path}\n"
                f"Run Phase A1 first: python -m pipeline.per_market a1 --market-id {client_id}"
            )
            return result
        if not evt_path.exists():
            result["error"] = (
                f"stockout_events.parquet not found: {evt_path}\n"
                f"Run Phase A2 first: python -m pipeline.per_market a2 --market-id {client_id}"
            )
            return result

        df_agg    = pd.read_parquet(agg_path,    engine=PARQUET_ENGINE)
        df_events = pd.read_parquet(evt_path,    engine=PARQUET_ENGINE)
        result["events_input"] = len(df_events)

        if df_events.empty:
            result["status"] = "no_data"
            result["error"]  = "stockout_events.parquet is empty"
            result["elapsed_sec"] = round(time.time() - t0, 2)
            return result

        # INN-grouped data: для швидкого доступу до df_inn у Level 1 (MARKET_GROWTH)
        # та drug_index (per-drug DataFrames для пошуку substitutes/lookup)
        inn_data: Dict[int, pd.DataFrame] = {
            int(inn_id): grp for inn_id, grp in df_agg.groupby("INN_ID")
        }

        all_did_events: List[Dict[str, Any]] = []
        all_sub_pairs:  List[Dict[str, Any]] = []

        # Group events by INN for batch processing
        for inn_id, inn_events in df_events.groupby("INN_ID"):
            inn_id = int(inn_id)
            df_inn = inn_data.get(inn_id)
            if df_inn is None or df_inn.empty:
                # Не повинно бути — кожен event має INN_ID, що був у aggregated
                result["validation_stats"]["no_post_period"] += len(inn_events)
                continue

            # Pre-index drugs for this INN
            drug_index: Dict[int, pd.DataFrame] = {
                int(did): grp for did, grp in df_inn.groupby("DRUGS_ID")
            }

            # Process each event
            for _, event in inn_events.iterrows():
                event_id      = event["EVENT_ID"]
                target_drug_id = int(event["DRUGS_ID"])
                target_nfc1   = event["NFC1_ID"]
                pre_start     = pd.Timestamp(event["PRE_START"])
                pre_end       = pd.Timestamp(event["PRE_END"])
                stockout_start = pd.Timestamp(event["STOCKOUT_START"])
                stockout_end   = pd.Timestamp(event["STOCKOUT_END"])

                # === Step 1: POST-period ===
                df_target_drug = drug_index.get(target_drug_id)
                if df_target_drug is None or df_target_drug.empty:
                    result["validation_stats"]["no_post_period"] += 1
                    continue

                post_start, post_end, post_weeks, post_status = define_post_period(
                    df_drug=df_target_drug,
                    stockout_end=stockout_end,
                    min_post_weeks=MIN_POST_PERIOD_WEEKS,
                    max_gap_weeks=MAX_POST_GAP_WEEKS,
                )
                if post_status != "valid":
                    result["validation_stats"]["no_post_period"] += 1
                    continue

                # === Step 2: Find valid substitutes (NFC + Phantom) ===
                valid_subs = find_valid_substitutes(
                    drug_index=drug_index,
                    target_drug_id=target_drug_id,
                    target_nfc1=target_nfc1,
                    stockout_start=stockout_start,
                    stockout_end=stockout_end,
                )
                if not valid_subs:
                    result["validation_stats"]["no_substitutes"] += 1
                    # WARN: Слідуємо канонічному: продовжуємо, навіть якщо substitutes=0.
                    # INTERNAL_LIFT буде 0, але LOST_SALES може бути > 0.

                # === Step 3: Main DiD calculation (ISSUE-013 FIX inside) ===
                event_metrics, sub_pairs = calculate_did_for_event(
                    df_inn=df_inn,
                    drug_index=drug_index,
                    target_drug_id=target_drug_id,
                    valid_substitutes=valid_subs,
                    pre_start=pre_start,
                    pre_end=pre_end,
                    stockout_start=stockout_start,
                    stockout_end=stockout_end,
                    min_market_pre=MIN_MARKET_PRE,
                    min_total_for_share=MIN_TOTAL_FOR_SHARE,
                )

                # === Step 4: Effect threshold ===
                if event_metrics["TOTAL_EFFECT"] < MIN_TOTAL_FOR_SHARE:
                    result["validation_stats"]["no_effect"] += 1
                    continue

                result["validation_stats"]["valid"] += 1

                # Build event row
                event_row = {
                    "EVENT_ID":     event_id,
                    "CLIENT_ID":    client_id,
                    "INN_ID":       inn_id,
                    "DRUGS_ID":     target_drug_id,
                    "DRUGS_NAME":   event["DRUGS_NAME"],
                    "NFC1_ID":      target_nfc1,
                    "POST_START":   post_start,
                    "POST_END":     post_end,
                    "POST_WEEKS":   int(post_weeks),
                    "POST_STATUS":  post_status,
                    **event_metrics,
                }
                all_did_events.append(event_row)

                # Build substitute pair rows (з link на event)
                for sp in sub_pairs:
                    pair_row = {
                        "EVENT_ID":          event_id,
                        "CLIENT_ID":         client_id,
                        "INN_ID":            inn_id,
                        "TARGET_DRUGS_ID":   target_drug_id,
                        "TARGET_DRUGS_NAME": event["DRUGS_NAME"],
                        "TARGET_NFC1_ID":    target_nfc1,
                        **sp,
                    }
                    all_sub_pairs.append(pair_row)

        result["valid_events"]            = len(all_did_events)
        result["substitute_pairs_count"]  = len(all_sub_pairs)

        # === Save outputs ===
        out_dir = get_market_intermediate_dir(client_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        # did_events.parquet
        if all_did_events:
            df_did = pd.DataFrame(all_did_events, columns=DID_EVENTS_COLUMNS)
        else:
            df_did = pd.DataFrame(columns=DID_EVENTS_COLUMNS)

        did_path = out_dir / DID_EVENTS_PARQUET
        df_did.to_parquet(did_path, engine=PARQUET_ENGINE,
                          compression=PARQUET_COMPRESS, index=False)
        result["did_output_path"]    = str(did_path)
        result["did_output_size_mb"] = round(did_path.stat().st_size / (1024 * 1024), 2)

        # substitute_pairs.parquet
        if all_sub_pairs:
            df_subs = pd.DataFrame(all_sub_pairs, columns=SUBSTITUTE_PAIRS_COLUMNS)
        else:
            df_subs = pd.DataFrame(columns=SUBSTITUTE_PAIRS_COLUMNS)

        subs_path = out_dir / SUBSTITUTE_PAIRS_PARQUET
        df_subs.to_parquet(subs_path, engine=PARQUET_ENGINE,
                           compression=PARQUET_COMPRESS, index=False)
        result["subs_output_path"]    = str(subs_path)
        result["subs_output_size_mb"] = round(subs_path.stat().st_size / (1024 * 1024), 2)

        result["status"] = "success" if all_did_events else "no_data"

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()

    result["elapsed_sec"] = round(time.time() - t0, 2)
    return result


# =============================================================================
# PHASE A4: process_market_substitutes (orchestrator)
# =============================================================================

def process_market_substitutes(client_id: int) -> Dict[str, Any]:
    """
    Phase A4: Substitute Analysis для одного ринку.

    Завдяки оптимізації з Phase A3 (LIFT уже у substitute_pairs.parquet),
    цей крок просто агрегує — без re-computation з raw даних.

    Вхід:
        substitute_pairs.parquet  — Phase A3 output (per substitute pair з LIFT)
        stockout_events.parquet   — Phase A2 output (для INN_NAME lookup)

    Вихід:
        substitute_shares.parquet — TOTAL_LIFT + SUBSTITUTE_SHARE per pair (per market)

    Алгоритм:
        1. Read inputs.
        2. Lookup INN_NAME з stockout_events.
        3. Aggregate per (STOCKOUT_DRUG, SUBSTITUTE_DRUG): TOTAL_LIFT + EVENTS_COUNT.
        4. Zero-LIFT filter: TOTAL_LIFT > 0.
        5. Recompute INTERNAL_LIFT per stockout_drug (sum of surviving substitutes' LIFT).
        6. SUBSTITUTE_SHARE = TOTAL_LIFT / INTERNAL_LIFT (decimal 0-1).
        7. SUBSTITUTE_RANK per stockout_drug.
        8. Save parquet.

    Returns:
        Dict із результатами та метриками.
    """
    t0 = time.time()
    result: Dict[str, Any] = {
        "phase":              "A4",
        "client_id":          client_id,
        "status":             "error",
        "elapsed_sec":        0.0,
        "input_pairs":        0,
        "after_aggregation":  0,
        "after_zero_filter":  0,
        "filtered_zero_lift": 0,
        "stockout_drugs":     0,
        "unique_substitutes": 0,
        "share_sum_invariant_pass": True,
        "max_share_sum_diff": 0.0,
        "output_path":        "",
        "output_size_mb":     0.0,
        "error":              None,
    }

    try:
        pairs_path  = get_substitute_pairs_path(client_id)
        events_path = get_stockout_parquet_path(client_id)

        if not pairs_path.exists():
            result["error"] = (
                f"substitute_pairs.parquet not found: {pairs_path}\n"
                f"Run Phase A3 first: python -m pipeline.per_market a3 --market-id {client_id}"
            )
            return result
        if not events_path.exists():
            result["error"] = (
                f"stockout_events.parquet not found: {events_path}\n"
                f"Run Phase A2 first: python -m pipeline.per_market a2 --market-id {client_id}"
            )
            return result

        df_pairs  = pd.read_parquet(pairs_path,  engine=PARQUET_ENGINE)
        df_events = pd.read_parquet(events_path, engine=PARQUET_ENGINE)
        result["input_pairs"] = len(df_pairs)

        if df_pairs.empty:
            result["status"] = "no_data"
            result["error"]  = "substitute_pairs.parquet is empty (no events with valid substitutes)"
            result["elapsed_sec"] = round(time.time() - t0, 2)
            return result

        # 1. INN_NAME lookup map
        inn_name_map = (
            df_events[["INN_ID", "INN_NAME"]]
            .drop_duplicates()
            .set_index("INN_ID")["INN_NAME"]
        )
        df_pairs = df_pairs.copy()
        df_pairs["INN_NAME"] = df_pairs["INN_ID"].map(inn_name_map).fillna("")

        # 2. Aggregate: sum LIFT per (stockout_drug, substitute_drug) + count events
        group_keys = [
            "CLIENT_ID", "INN_ID", "INN_NAME",
            "TARGET_DRUGS_ID", "TARGET_DRUGS_NAME", "TARGET_NFC1_ID",
            "SUBSTITUTE_DRUGS_ID", "SUBSTITUTE_DRUGS_NAME", "SUBSTITUTE_NFC1_ID",
            "SAME_NFC1",
        ]
        df_agg = df_pairs.groupby(group_keys, dropna=False, as_index=False).agg(
            TOTAL_LIFT=("LIFT", "sum"),
            EVENTS_COUNT=("EVENT_ID", "count"),
        )
        result["after_aggregation"] = len(df_agg)

        # 3. Rename для clarity (TARGET_* → STOCKOUT_*, SUBSTITUTE_DRUGS_* → SUBSTITUTE_DRUG_*)
        df_agg = df_agg.rename(columns={
            "TARGET_DRUGS_ID":      "STOCKOUT_DRUG_ID",
            "TARGET_DRUGS_NAME":    "STOCKOUT_DRUG_NAME",
            "TARGET_NFC1_ID":       "STOCKOUT_NFC1_ID",
            "SUBSTITUTE_DRUGS_ID":  "SUBSTITUTE_DRUG_ID",
            "SUBSTITUTE_DRUGS_NAME":"SUBSTITUTE_DRUG_NAME",
        })

        # 4. Zero-LIFT filter
        before = len(df_agg)
        df_agg = df_agg[df_agg["TOTAL_LIFT"] > 0].copy()
        result["after_zero_filter"]  = len(df_agg)
        result["filtered_zero_lift"] = before - len(df_agg)

        if df_agg.empty:
            # Все відфільтровано — зберігаємо порожній parquet з правильною схемою
            df_out = pd.DataFrame(columns=SUBSTITUTE_SHARES_COLUMNS)
            out_dir = get_market_intermediate_dir(client_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / SUBSTITUTE_SHARES_PARQUET
            df_out.to_parquet(out_path, engine=PARQUET_ENGINE,
                              compression=PARQUET_COMPRESS, index=False)
            result["output_path"]    = str(out_path)
            result["output_size_mb"] = round(out_path.stat().st_size / (1024 * 1024), 2)
            result["status"]         = "no_data"
            result["error"]          = "all pairs had TOTAL_LIFT == 0 (zero-LIFT filter)"
            result["elapsed_sec"]    = round(time.time() - t0, 2)
            return result

        # 5. INTERNAL_LIFT per stockout drug (sum after zero-filter)
        internal_lift = (
            df_agg.groupby("STOCKOUT_DRUG_ID")["TOTAL_LIFT"]
                  .sum()
                  .rename("INTERNAL_LIFT")
                  .reset_index()
        )
        df_agg = df_agg.merge(internal_lift, on="STOCKOUT_DRUG_ID", how="left")

        # 6. SUBSTITUTE_SHARE — decimal (0-1)
        df_agg["SUBSTITUTE_SHARE"] = df_agg["TOTAL_LIFT"] / df_agg["INTERNAL_LIFT"]

        # 7. SUBSTITUTE_RANK (1 = highest share within stockout drug)
        df_agg = df_agg.sort_values(
            ["STOCKOUT_DRUG_ID", "SUBSTITUTE_SHARE"],
            ascending=[True, False],
        )
        df_agg["SUBSTITUTE_RANK"] = (
            df_agg.groupby("STOCKOUT_DRUG_ID")["SUBSTITUTE_SHARE"]
                  .rank(method="first", ascending=False)
                  .astype(int)
        )

        # 8. Округлення для компактності parquet
        df_agg["TOTAL_LIFT"]       = df_agg["TOTAL_LIFT"].round(4)
        df_agg["INTERNAL_LIFT"]    = df_agg["INTERNAL_LIFT"].round(4)
        df_agg["SUBSTITUTE_SHARE"] = df_agg["SUBSTITUTE_SHARE"].round(6)

        # 9. Метрики + інваріант перевірка
        result["stockout_drugs"]     = int(df_agg["STOCKOUT_DRUG_ID"].nunique())
        result["unique_substitutes"] = int(df_agg["SUBSTITUTE_DRUG_ID"].nunique())

        share_sums = df_agg.groupby("STOCKOUT_DRUG_ID")["SUBSTITUTE_SHARE"].sum()
        share_sum_diffs = (share_sums - 1.0).abs()
        result["max_share_sum_diff"] = float(share_sum_diffs.max())
        result["share_sum_invariant_pass"] = bool(share_sum_diffs.max() < 0.001)

        # 10. Reorder columns
        df_agg = df_agg[SUBSTITUTE_SHARES_COLUMNS]

        # 11. Save
        out_dir = get_market_intermediate_dir(client_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / SUBSTITUTE_SHARES_PARQUET
        df_agg.to_parquet(out_path, engine=PARQUET_ENGINE,
                          compression=PARQUET_COMPRESS, index=False)

        result["output_path"]    = str(out_path)
        result["output_size_mb"] = round(out_path.stat().st_size / (1024 * 1024), 2)
        result["status"]         = "success"

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()

    result["elapsed_sec"] = round(time.time() - t0, 2)
    return result


# =============================================================================
# FULL MARKET PIPELINE: A1 → A2 → A3 → A4 (single-worker entry point)
# =============================================================================

def process_market_full(
    client_id: int,
    file_path: Path,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Виконати A1 → A2 → A3 → A4 для одного ринку послідовно у одному worker.

    Призначена для виклику з ProcessPoolExecutor у `pipeline/runner.py`.
    Підтримує **resume**: якщо output фази вже існує — фаза пропускається
    (якщо `force=False`).

    Args:
        client_id: ID цільової аптеки.
        file_path: Шлях до raw CSV.
        force:    Якщо True — ігнорувати існуючі output, перерахувати все.

    Returns:
        Dict з зведеними метриками:
            client_id           — int
            overall_status      — 'success' | 'no_data' | 'error' | 'partial'
            overall_elapsed_sec — float (повний час A1+A2+A3+A4 + skip checks)
            phases              — Dict[str, Dict] (a1, a2, a3, a4 — кожен має status, elapsed_sec, ...)
            failed_at           — Optional[str] (фаза, де сталася помилка)
            error               — Optional[str]
    """
    import os as _os
    import sys as _sys

    overall_t0 = time.time()
    summary: Dict[str, Any] = {
        "client_id":           client_id,
        "overall_status":      "success",
        "overall_elapsed_sec": 0.0,
        "phases":              {},
        "failed_at":           None,
        "error":               None,
    }

    # Suppress per-phase stdout (worker context — TUI/tqdm shows progress).
    _orig_stdout = _sys.stdout
    _sys.stdout = open(_os.devnull, "w")

    try:
        # === Phase A1: Aggregation ===
        # Corruption-aware skip: phase_output_valid() видаляє corrupt parquet.
        if not force and phase_output_valid(get_aggregated_parquet_path(client_id)):
            summary["phases"]["a1"] = {
                "status": "skipped",
                "elapsed_sec": 0.0,
                "reason": "aggregated.parquet exists and valid",
            }
        else:
            r = process_market_a1(client_id, file_path)
            r.pop("drugs_df", None)
            r.pop("traceback", None)
            summary["phases"]["a1"] = r
            if r["status"] == "error":
                summary["overall_status"] = "error"
                summary["failed_at"]      = "A1"
                summary["error"]          = r.get("error")
                return summary
            if r["status"] == "no_data":
                summary["overall_status"] = "no_data"
                summary["failed_at"]      = "A1"
                return summary

        # === Phase A2: Stockout detection ===
        if not force and phase_output_valid(get_stockout_parquet_path(client_id)):
            summary["phases"]["a2"] = {
                "status": "skipped",
                "elapsed_sec": 0.0,
                "reason": "stockout_events.parquet exists and valid",
            }
        else:
            r = process_market_stockout(client_id)
            r.pop("traceback", None)
            summary["phases"]["a2"] = r
            if r["status"] == "error":
                summary["overall_status"] = "error"
                summary["failed_at"]      = "A2"
                summary["error"]          = r.get("error")
                return summary
            if r["status"] == "no_data":
                summary["overall_status"] = "no_data"
                summary["failed_at"]      = "A2"
                return summary

        # === Phase A3: DiD analysis ===
        # Skip лише якщо ОБА parquet валідні
        if (not force
            and phase_output_valid(get_did_events_path(client_id))
            and phase_output_valid(get_substitute_pairs_path(client_id))):
            summary["phases"]["a3"] = {
                "status": "skipped",
                "elapsed_sec": 0.0,
                "reason": "did_events.parquet + substitute_pairs.parquet exist and valid",
            }
        else:
            r = process_market_did(client_id)
            r.pop("traceback", None)
            summary["phases"]["a3"] = r
            if r["status"] == "error":
                summary["overall_status"] = "error"
                summary["failed_at"]      = "A3"
                summary["error"]          = r.get("error")
                return summary
            if r["status"] == "no_data":
                summary["overall_status"] = "no_data"
                summary["failed_at"]      = "A3"
                return summary

        # === Phase A4: Substitute analysis ===
        if not force and phase_output_valid(get_substitute_shares_path(client_id)):
            summary["phases"]["a4"] = {
                "status": "skipped",
                "elapsed_sec": 0.0,
                "reason": "substitute_shares.parquet exists and valid",
            }
        else:
            r = process_market_substitutes(client_id)
            r.pop("traceback", None)
            summary["phases"]["a4"] = r
            if r["status"] == "error":
                summary["overall_status"] = "error"
                summary["failed_at"]      = "A4"
                summary["error"]          = r.get("error")
                return summary
            if r["status"] == "no_data":
                summary["overall_status"] = "no_data"
                summary["failed_at"]      = "A4"
                return summary

    except Exception as e:
        summary["overall_status"] = "error"
        summary["error"]          = f"{type(e).__name__}: {e}"
        summary["traceback"]      = traceback.format_exc()

    finally:
        try:
            _sys.stdout.close()
        except Exception:
            pass
        _sys.stdout = _orig_stdout

    summary["overall_elapsed_sec"] = round(time.time() - overall_t0, 2)
    return summary


# =============================================================================
# DISPLAY
# =============================================================================

def print_phase_result(result: Dict[str, Any]) -> None:
    """Гарний вивід результату обробки одного ринку (A1 або A2)."""
    console = Console()

    phase     = result.get("phase", "?")
    client_id = result["client_id"]
    status    = result["status"]
    color     = {"success": "green", "no_data": "yellow", "error": "red"}.get(status, "white")
    status_str = f"[{color}]{status.upper()}[/{color}]"

    title = f"Phase {phase}: Market {client_id} — {status_str}"
    console.print(Panel.fit(title, border_style=color))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Metric", style="cyan")
    table.add_column("Value",  justify="right")

    if phase == "A1":
        table.add_row("Raw rows",       f"{result['raw_rows']:,}")
        table.add_row("Output rows",    f"{result['output_rows']:,}")
        table.add_row("INN processed",  f"{result['inn_processed']}")
        table.add_row("INN skipped",    f"{result['inn_skipped']} (no valid drugs after NOTSOLD filter)")
        table.add_row("Drugs",          f"{result['drugs_count']}")
    elif phase == "A2":
        vs = result["validation_stats"]
        table.add_row("INN processed",   f"{result['inn_processed']}")
        table.add_row("Raw events",      f"{result['raw_events']:,}")
        table.add_row("[green]Valid events[/green]", f"{result['valid_events']:,}")
        if result["raw_events"] > 0:
            rate = result["valid_events"] / result["raw_events"] * 100
            table.add_row("Validation rate", f"{rate:.1f}%")
        table.add_row("[red]REJECT no_market_activity[/red]", f"{vs['no_market_activity']:,}")
        table.add_row("[red]REJECT no_pre_sales[/red]",        f"{vs['no_pre_sales']:,}")
        table.add_row("[red]REJECT no_competitors[/red]",      f"{vs['no_competitors']:,}")
        table.add_row("Drugs with events", f"{result['drugs_with_events']}")
    elif phase == "A3":
        vs = result["validation_stats"]
        table.add_row("Events input",    f"{result['events_input']:,}")
        table.add_row("[green]Valid DiD events[/green]", f"{result['valid_events']:,}")
        if result["events_input"] > 0:
            rate = result["valid_events"] / result["events_input"] * 100
            table.add_row("Validation rate", f"{rate:.1f}%")
        table.add_row("[red]REJECT no_post_period[/red]", f"{vs['no_post_period']:,}")
        table.add_row("[yellow]Info no_substitutes[/yellow]", f"{vs['no_substitutes']:,} (still processed)")
        table.add_row("[red]REJECT no_effect[/red]",      f"{vs['no_effect']:,}")
        table.add_row("Substitute pairs", f"{result['substitute_pairs_count']:,}")
    elif phase == "A4":
        table.add_row("Input pairs",         f"{result['input_pairs']:,}")
        table.add_row("After aggregation",   f"{result['after_aggregation']:,}")
        table.add_row("[red]Filtered (zero-LIFT)[/red]", f"{result['filtered_zero_lift']:,}")
        table.add_row("[green]Final pairs[/green]",       f"{result['after_zero_filter']:,}")
        table.add_row("Stockout drugs",      f"{result['stockout_drugs']}")
        table.add_row("Unique substitutes",  f"{result['unique_substitutes']}")
        invariant_color = "green" if result['share_sum_invariant_pass'] else "red"
        invariant_str = "PASSED" if result['share_sum_invariant_pass'] else "FAILED"
        table.add_row(f"[{invariant_color}]SHARE_SUM invariant[/{invariant_color}]",
                      f"{invariant_str} (max diff: {result['max_share_sum_diff']:.6f})")

    # Output sizes (varies per phase)
    if phase == "A3":
        table.add_row("did_events size",      f"{result['did_output_size_mb']:.2f} MB")
        table.add_row("substitute_pairs size",f"{result['subs_output_size_mb']:.2f} MB")
    else:
        table.add_row("Output size",   f"{result['output_size_mb']:.2f} MB")
    table.add_row("Elapsed",       f"{result['elapsed_sec']:.2f} s")

    if phase == "A3":
        if result.get("did_output_path"):
            table.add_row("did_events", str(result["did_output_path"]))
        if result.get("subs_output_path"):
            table.add_row("substitute_pairs", str(result["subs_output_path"]))
    else:
        if result.get("output_path"):
            table.add_row("Output", str(result["output_path"]))

    if result.get("error"):
        table.add_row("[red]Error[/red]", result["error"])
    console.print(table)


# =============================================================================
# CLI HELPERS
# =============================================================================

def _resolve_market_file(client_id: int) -> Path:
    """Знайти FILE_PATH для CLIENT_ID з markets_list.csv."""
    df = load_markets_list()
    row = df[df["CLIENT_ID"] == client_id]
    if row.empty:
        raise ValueError(f"Market {client_id} not in markets_list.csv (run discover_markets first)")
    return Path(row.iloc[0]["FILE_PATH"])


def _ready_markets(limit: Optional[int] = None) -> pd.DataFrame:
    """READY ринки з markets_list.csv (відсортовані за CLIENT_ID, опційно перші N)."""
    df = load_markets_list()
    df_ready = df[df["STATUS"] == "READY"].sort_values("CLIENT_ID")
    if limit is not None:
        df_ready = df_ready.head(limit)
    return df_ready.reset_index(drop=True)


def _print_summary(phase: str, results: List[Dict[str, Any]]) -> int:
    """Підсумок sequential-запуску, повертає exit code."""
    console = Console()
    success = sum(1 for r in results if r["status"] == "success")
    no_data = sum(1 for r in results if r["status"] == "no_data")
    errors  = sum(1 for r in results if r["status"] == "error")
    total_elapsed = sum(r["elapsed_sec"] for r in results)

    summary = Table(title=f"Phase {phase} sequential summary", show_header=True, header_style="bold")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value",  justify="right")
    summary.add_row("Markets attempted",                 f"{len(results)}")
    summary.add_row("[green]Success[/green]",            f"{success}")
    summary.add_row("[yellow]No data[/yellow]",          f"{no_data}")
    summary.add_row("[red]Errors[/red]",                 f"{errors}")
    summary.add_row("Total elapsed",                     f"{total_elapsed:.2f} s")
    if results:
        summary.add_row("Avg per market",                f"{total_elapsed/len(results):.2f} s")
    console.print(summary)
    return 0 if errors == 0 else 1


# =============================================================================
# CLI: PHASE A1 / A2 SUBCOMMANDS
# =============================================================================

def cmd_a1(market_id: Optional[int], limit: Optional[int]) -> int:
    ensure_directories()
    if market_id is not None:
        file_path = _resolve_market_file(market_id)
        result = process_market_a1(market_id, file_path)
        print_phase_result(result)
        if result.get("traceback"):
            rprint(f"\n[dim]{result['traceback']}[/dim]")
        return 0 if result["status"] in ("success", "no_data") else 1

    # --limit
    df_ready = _ready_markets(limit)
    rprint(f"\n[bold cyan]Phase A1: processing {len(df_ready)} READY markets sequentially[/bold cyan]\n")
    results = []
    for _, row in df_ready.iterrows():
        cid       = int(row["CLIENT_ID"])
        file_path = Path(row["FILE_PATH"])
        r = process_market_a1(cid, file_path)
        print_phase_result(r)
        results.append(r)
    return _print_summary("A1", results)


def cmd_a2(market_id: Optional[int], limit: Optional[int]) -> int:
    ensure_directories()
    if market_id is not None:
        result = process_market_stockout(market_id)
        print_phase_result(result)
        if result.get("traceback"):
            rprint(f"\n[dim]{result['traceback']}[/dim]")
        return 0 if result["status"] in ("success", "no_data") else 1

    # --limit
    df_ready = _ready_markets(limit)
    rprint(f"\n[bold cyan]Phase A2: processing {len(df_ready)} READY markets sequentially[/bold cyan]\n")
    results = []
    for _, row in df_ready.iterrows():
        cid = int(row["CLIENT_ID"])
        r = process_market_stockout(cid)
        print_phase_result(r)
        results.append(r)
    return _print_summary("A2", results)


def cmd_a3(market_id: Optional[int], limit: Optional[int]) -> int:
    ensure_directories()
    if market_id is not None:
        result = process_market_did(market_id)
        print_phase_result(result)
        if result.get("traceback"):
            rprint(f"\n[dim]{result['traceback']}[/dim]")
        return 0 if result["status"] in ("success", "no_data") else 1

    # --limit
    df_ready = _ready_markets(limit)
    rprint(f"\n[bold cyan]Phase A3: processing {len(df_ready)} READY markets sequentially[/bold cyan]\n")
    results = []
    for _, row in df_ready.iterrows():
        cid = int(row["CLIENT_ID"])
        r = process_market_did(cid)
        print_phase_result(r)
        results.append(r)
    return _print_summary("A3", results)


def cmd_a4(market_id: Optional[int], limit: Optional[int]) -> int:
    ensure_directories()
    if market_id is not None:
        result = process_market_substitutes(market_id)
        print_phase_result(result)
        if result.get("traceback"):
            rprint(f"\n[dim]{result['traceback']}[/dim]")
        return 0 if result["status"] in ("success", "no_data") else 1

    # --limit
    df_ready = _ready_markets(limit)
    rprint(f"\n[bold cyan]Phase A4: processing {len(df_ready)} READY markets sequentially[/bold cyan]\n")
    results = []
    for _, row in df_ready.iterrows():
        cid = int(row["CLIENT_ID"])
        r = process_market_substitutes(cid)
        print_phase_result(r)
        results.append(r)
    return _print_summary("A4", results)


# =============================================================================
# MAIN
# =============================================================================

def _add_market_args(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--market-id", "-m", type=int, help="Single CLIENT_ID")
    g.add_argument("--limit", "-n", type=int, help="First N READY markets (sequential)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Per-market processing (Phase A1 + A2 + A3 + A4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  python -m pipeline.per_market a1 --market-id 763807\n"
               "  python -m pipeline.per_market a2 --market-id 763807\n"
               "  python -m pipeline.per_market a3 --market-id 763807\n"
               "  python -m pipeline.per_market a4 --market-id 763807\n"
               "  python -m pipeline.per_market {a1|a2|a3|a4} --limit 3\n",
    )
    sub = parser.add_subparsers(dest="phase", required=True, metavar="{a1,a2,a3,a4}")

    p_a1 = sub.add_parser("a1", help="Phase A1: Data aggregation")
    _add_market_args(p_a1)

    p_a2 = sub.add_parser("a2", help="Phase A2: Stockout detection")
    _add_market_args(p_a2)

    p_a3 = sub.add_parser("a3", help="Phase A3: DiD analysis (NFC filter + Phantom + LIFT)")
    _add_market_args(p_a3)

    p_a4 = sub.add_parser("a4", help="Phase A4: Substitute analysis (aggregate + Zero-LIFT filter + SHARE)")
    _add_market_args(p_a4)

    args = parser.parse_args()

    try:
        if args.phase == "a1":
            return cmd_a1(args.market_id, args.limit)
        if args.phase == "a2":
            return cmd_a2(args.market_id, args.limit)
        if args.phase == "a3":
            return cmd_a3(args.market_id, args.limit)
        if args.phase == "a4":
            return cmd_a4(args.market_id, args.limit)
        parser.print_help()
        return 1
    except FileNotFoundError as e:
        rprint(f"[red]ERROR:[/red] {e}")
        return 1
    except Exception as e:
        rprint(f"[red]UNEXPECTED ERROR:[/red] {type(e).__name__}: {e}")
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
