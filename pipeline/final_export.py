# =============================================================================
# FINAL EXPORT - drug_substitution_engine / Phase C
# =============================================================================
# Файл: pipeline/final_export.py
# Дата: 2026-04-27
# Опис: Phase C — формування 2 CSV + 2 XLSX для Power BI.
# =============================================================================

"""
Phase C: Final Export — production-ready 4 файли для Power BI.

Steps:
    C0. Filter drugs by MARKET_COUNT >= min_market_count (default 20).
    C1. Build drug_coefficients.csv/.xlsx.
    C2. Build substitute_shares.csv/.xlsx (LIFT-weighted cross-market aggregation).
    C3. Save validation_report.txt.

Вхід:
    data/intermediate/02_cross_market/drug_statistics.parquet  (Phase B)
    data/intermediate/01_per_market/{ID}/substitute_shares.parquet  (Phase A4, всі ринки)

Вихід:
    results/final/drug_coefficients.csv   (mandatory: DRUGS_ID, DRUG_CLASS, COEF_1, UNIQUENESS_COEF)
    results/final/drug_coefficients.xlsx  (же ж самі дані)
    results/final/substitute_shares.csv   (mandatory: DRUGS_ID, SUBSTITUTE_DRUG_ID, SUBSTITUTE_SHARE)
    results/final/substitute_shares.xlsx  (те ж саме)
    reports/validation_report.txt         (інваріанти)

CLI:
    python -m pipeline.final_export                       # default min_market_count=20
    python -m pipeline.final_export --min-market-count 3  # smoke-test (мала вибірка)
"""

import argparse
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
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
    PER_MARKET_PATH,
    CROSS_MARKET_PATH,
    FINAL_RESULTS_PATH,
    REPORTS_PATH,
    CSV_SEPARATOR,
    CSV_ENCODING_OUT,
    ensure_directories,
)


# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_MIN_MARKET_COUNT = 20  # Sequential Analyzer Study 02 criterion

PARQUET_ENGINE = "pyarrow"

DRUG_STATS_PARQUET    = "drug_statistics.parquet"
PER_MARKET_SUBS_FILE  = "substitute_shares.parquet"

# Output filenames
OUT_DRUG_COEF_CSV  = "drug_coefficients.csv"
OUT_DRUG_COEF_XLSX = "drug_coefficients.xlsx"
OUT_SUB_SHARES_CSV  = "substitute_shares.csv"
OUT_SUB_SHARES_XLSX = "substitute_shares.xlsx"
OUT_VALIDATION_TXT  = "validation_report.txt"

# Tolerance для інваріанту SUM(SHARE per drug) = 1.0
SHARE_SUM_EPSILON = 0.01

# Column order: drug_coefficients (4 mandatory + 3 декомпозиційні + 5 optional + 1 reliability)
DRUG_COEF_COLUMNS = [
    "DRUGS_ID",
    "DRUG_CLASS",
    "COEF_1",
    "UNIQUENESS_COEF",
    "COVERAGE_PCT",
    "CONDITIONAL_RETENTION",
    "MARKETS_WITH_SUB",
    "DRUGS_NAME",
    "INN_ID",
    "INN_NAME",
    "NFC1_ID",
    "MARKET_COUNT",
    "RELIABILITY_SCORE",   # композитний показник надійності COEF_1 (0..1)
]

# Tolerance для декомпозиційного інваріанту: COEF_1 = COVERAGE_PCT × CONDITIONAL_RETENTION
DECOMPOSE_EPSILON = 0.001

# Column order: substitute_shares (3 mandatory + 5 optional)
SUB_SHARES_COLUMNS = [
    "DRUGS_ID",
    "SUBSTITUTE_DRUG_ID",
    "SUBSTITUTE_SHARE",
    "DRUGS_NAME",
    "SUBSTITUTE_DRUG_NAME",
    "SAME_NFC1",
    "SUBSTITUTE_RANK",
    "MARKETS_COUNT",
]


# =============================================================================
# DATA LOADING
# =============================================================================

def load_drug_statistics() -> pd.DataFrame:
    """Завантажити drug_statistics.parquet (Phase B output)."""
    p = CROSS_MARKET_PATH / DRUG_STATS_PARQUET
    if not p.exists():
        raise FileNotFoundError(
            f"drug_statistics.parquet не знайдено: {p}\n"
            f"Спочатку виконайте Phase B: python -m pipeline.cross_market"
        )
    return pd.read_parquet(p, engine=PARQUET_ENGINE)


def load_all_substitute_shares() -> pd.DataFrame:
    """Конкатенувати substitute_shares.parquet з усіх ринків (Phase A4)."""
    if not PER_MARKET_PATH.exists():
        raise FileNotFoundError(f"PER_MARKET_PATH не існує: {PER_MARKET_PATH}")

    market_dirs = sorted(PER_MARKET_PATH.iterdir())
    frames = []
    for d in market_dirs:
        if not d.is_dir():
            continue
        f = d / PER_MARKET_SUBS_FILE
        if not f.exists():
            continue
        try:
            df = pd.read_parquet(f, engine=PARQUET_ENGINE)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            rprint(f"[yellow]WARN:[/yellow] failed to read {f.name} from {d.name}: {e}")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# =============================================================================
# C1: BUILD drug_coefficients
# =============================================================================

def build_drug_coefficients(df_accepted: pd.DataFrame) -> pd.DataFrame:
    """
    Сформувати drug_coefficients DataFrame з 12 колонок (4 mandatory + 3
    декомпозиційні + 5 optional).

    COEF_1 ← MEAN_SHARE_INTERNAL з Phase B (mean SHARE_INTERNAL по ринках,
    після IQR-фільтра Тукі 1.5×). Декомпозиційні колонки:
        COVERAGE_PCT          — частка ринків з SHARE > 0
        CONDITIONAL_RETENTION — mean(SHARE | SHARE > 0)
        MARKETS_WITH_SUB      — кількість ринків з SHARE > 0

    Інваріант: COEF_1 = COVERAGE_PCT × CONDITIONAL_RETENTION.

    Args:
        df_accepted: DataFrame з drug_statistics.parquet, відфільтрований по
                     MARKET_COUNT_TOTAL >= min_market_count.

    Returns:
        DataFrame готовий до експорту.
    """
    df = df_accepted.copy()

    # Перейменування для фінального формату
    df = df.rename(columns={
        "MEAN_SHARE_INTERNAL": "COEF_1",
        "MARKET_COUNT_TOTAL":  "MARKET_COUNT",
    })

    # UNIQUENESS_COEF = 1 - COEF_1
    df["UNIQUENESS_COEF"] = (1.0 - df["COEF_1"]).round(6)

    # Reorder columns
    df_out = df[DRUG_COEF_COLUMNS].copy()

    # Sort: COEF_1 DESC
    df_out = df_out.sort_values("COEF_1", ascending=False).reset_index(drop=True)
    return df_out


# =============================================================================
# C2: BUILD substitute_shares (LIFT-weighted cross-market)
# =============================================================================

def build_substitute_shares(
    df_subs_market: pd.DataFrame,
    accepted_drug_ids: set,
) -> pd.DataFrame:
    """
    LIFT-зважена крос-ринкова агрегація substitute pairs.

    Алгоритм (відповідає канонічному Phase 3 Step 2):
        1. Filter to accepted drugs (passed MIN_MARKET_COUNT)
        2. Per pair (STOCKOUT_DRUG, SUBSTITUTE_DRUG) cross-market:
           AGG_TOTAL_LIFT = SUM(TOTAL_LIFT) across markets
        3. Per stockout_drug cross-market (DEDUP per market):
           AGG_INTERNAL_LIFT = SUM(unique INTERNAL_LIFT per market per drug)
        4. SUBSTITUTE_SHARE = AGG_TOTAL_LIFT / AGG_INTERNAL_LIFT (decimal 0-1)
        5. SUBSTITUTE_RANK per stockout drug

    Інваріант: SUM(SUBSTITUTE_SHARE per stockout_drug) ≈ 1.0

    Args:
        df_subs_market:    Concat substitute_shares.parquet з усіх ринків.
        accepted_drug_ids: set DRUGS_ID що пройшли MIN_MARKET_COUNT фільтр.

    Returns:
        DataFrame з 8 колонками (3 mandatory + 5 optional).
    """
    # 1. Filter to accepted stockout drugs
    df = df_subs_market[df_subs_market["STOCKOUT_DRUG_ID"].isin(accepted_drug_ids)].copy()

    if df.empty:
        return pd.DataFrame(columns=SUB_SHARES_COLUMNS)

    # 2. Per pair cross-market aggregation
    pair_agg = df.groupby(
        ["STOCKOUT_DRUG_ID", "SUBSTITUTE_DRUG_ID"], as_index=False
    ).agg(
        AGG_TOTAL_LIFT=("TOTAL_LIFT", "sum"),
        MARKETS_COUNT=("CLIENT_ID", "nunique"),
        DRUGS_NAME=("STOCKOUT_DRUG_NAME", "first"),
        SUBSTITUTE_DRUG_NAME=("SUBSTITUTE_DRUG_NAME", "first"),
        SAME_NFC1=("SAME_NFC1", "first"),
    )

    # 3. AGG_INTERNAL_LIFT per stockout drug — DEDUP per (CLIENT_ID, STOCKOUT_DRUG_ID)
    # INTERNAL_LIFT — drug-level metric, повторюється для всіх substitute pairs
    # одного drug в одному ринку. Дедублікуємо перед підсумовуванням.
    df_internal = (
        df[["CLIENT_ID", "STOCKOUT_DRUG_ID", "INTERNAL_LIFT"]]
        .drop_duplicates(subset=["CLIENT_ID", "STOCKOUT_DRUG_ID"])
    )
    internal_cross = (
        df_internal.groupby("STOCKOUT_DRUG_ID")["INTERNAL_LIFT"]
                   .sum()
                   .rename("AGG_INTERNAL_LIFT")
                   .reset_index()
    )

    # 4. Merge & compute SUBSTITUTE_SHARE
    pair_agg = pair_agg.merge(internal_cross, on="STOCKOUT_DRUG_ID", how="left")
    pair_agg["SUBSTITUTE_SHARE"] = (
        pair_agg["AGG_TOTAL_LIFT"] / pair_agg["AGG_INTERNAL_LIFT"]
    ).round(6)

    # 4b. Видалення «фантомних» substitutes (SHARE = 0 після нормалізації)
    # Пари, які мали LIFT > 0 хоч у одному ринку, але після cross-market
    # агрегації та округлення отримали SHARE = 0.0, формально не є substitutes
    # для бізнес-споживача. Intermediate `substitute_pairs.parquet` (Phase A3)
    # зберігає повну видимість — ці пари там лишаються; фільтр діє лише на
    # фінальний експорт. Pattern: "broad model, narrow export" (ISSUE-016).
    n_before_phantom_filter = len(pair_agg)
    pair_agg = pair_agg[pair_agg["SUBSTITUTE_SHARE"] > 0].copy()
    n_phantom_removed = n_before_phantom_filter - len(pair_agg)
    if n_phantom_removed > 0:
        rprint(f"[dim]  Phantom substitutes removed (SHARE=0 after agg): {n_phantom_removed}[/dim]")

    # 5. SUBSTITUTE_RANK (1 = найвища SHARE per stockout drug)
    pair_agg = pair_agg.sort_values(
        ["STOCKOUT_DRUG_ID", "SUBSTITUTE_SHARE"],
        ascending=[True, False],
    )
    pair_agg["SUBSTITUTE_RANK"] = (
        pair_agg.groupby("STOCKOUT_DRUG_ID")["SUBSTITUTE_SHARE"]
                .rank(method="first", ascending=False)
                .astype(int)
    )

    # 6. Rename and reorder for output
    pair_agg = pair_agg.rename(columns={"STOCKOUT_DRUG_ID": "DRUGS_ID"})
    df_out = pair_agg[SUB_SHARES_COLUMNS].copy()

    # Final sort: DRUGS_ID, SUBSTITUTE_RANK
    df_out = df_out.sort_values(
        ["DRUGS_ID", "SUBSTITUTE_RANK"],
        ascending=[True, True],
    ).reset_index(drop=True)

    return df_out


# =============================================================================
# SAVE FILES
# =============================================================================

def save_csv(df: pd.DataFrame, path: Path) -> None:
    """Зберегти DataFrame як CSV з sep=';' та utf-8-sig."""
    df.to_csv(path, sep=CSV_SEPARATOR, encoding=CSV_ENCODING_OUT, index=False)


def save_xlsx(df: pd.DataFrame, path: Path, sheet_name: str = "Sheet1") -> None:
    """Зберегти DataFrame як XLSX без кольорового маркування."""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)


# =============================================================================
# C3: VALIDATION
# =============================================================================

def validate_outputs(
    df_drug_coef: pd.DataFrame,
    df_sub_shares: pd.DataFrame,
    min_market_count: int,
) -> Dict[str, Any]:
    """
    Перевірити інваріанти фінальних файлів.

    Returns:
        Dict із результатами перевірок:
            {check_name: bool, max_diff (для деяких), invalid_drugs (для деяких)}
    """
    validation: Dict[str, Any] = {
        "checks": {},
        "all_pass": True,
        "details": {},
    }

    def check(name: str, condition: bool, detail: str = ""):
        validation["checks"][name] = bool(condition)
        if not condition:
            validation["all_pass"] = False
        if detail:
            validation["details"][name] = detail

    # === drug_coefficients ===
    if len(df_drug_coef) > 0:
        check("DC_NO_NAN_COEF_1",
              not df_drug_coef["COEF_1"].isna().any(),
              f"NaN count: {df_drug_coef['COEF_1'].isna().sum()}")

        in_range = ((df_drug_coef["COEF_1"] >= 0) & (df_drug_coef["COEF_1"] <= 1)).all()
        check("DC_COEF_1_IN_0_1",
              bool(in_range),
              f"min={df_drug_coef['COEF_1'].min():.4f}, max={df_drug_coef['COEF_1'].max():.4f}")

        unq_diff = (df_drug_coef["UNIQUENESS_COEF"]
                    - (1.0 - df_drug_coef["COEF_1"])).abs().max()
        check("DC_UNIQUENESS_COEF_FORMULA",
              unq_diff < 1e-5,
              f"max |UNIQ - (1-COEF_1)| = {unq_diff:.7f}")

        check("DC_DRUG_CLASS_VALUES",
              set(df_drug_coef["DRUG_CLASS"].unique()) <= {"UNIMODAL", "MULTIMODAL"},
              f"unique: {df_drug_coef['DRUG_CLASS'].unique().tolist()}")

        check("DC_MARKET_COUNT_GE_MIN",
              (df_drug_coef["MARKET_COUNT"] >= min_market_count).all(),
              f"min in df = {df_drug_coef['MARKET_COUNT'].min()}, threshold = {min_market_count}")

        check("DC_DRUGS_ID_UNIQUE",
              df_drug_coef["DRUGS_ID"].is_unique,
              f"duplicates: {df_drug_coef['DRUGS_ID'].duplicated().sum()}")

        # === Декомпозиційні метрики (нові) ===
        cov_in_range = ((df_drug_coef["COVERAGE_PCT"] >= 0) &
                        (df_drug_coef["COVERAGE_PCT"] <= 1)).all()
        check("DC_COVERAGE_IN_0_1",
              bool(cov_in_range),
              f"min={df_drug_coef['COVERAGE_PCT'].min():.4f}, "
              f"max={df_drug_coef['COVERAGE_PCT'].max():.4f}")

        cr_in_range = ((df_drug_coef["CONDITIONAL_RETENTION"] >= 0) &
                       (df_drug_coef["CONDITIONAL_RETENTION"] <= 1)).all()
        check("DC_CONDITIONAL_IN_0_1",
              bool(cr_in_range),
              f"min={df_drug_coef['CONDITIONAL_RETENTION'].min():.4f}, "
              f"max={df_drug_coef['CONDITIONAL_RETENTION'].max():.4f}")

        # COEF_1 = COVERAGE_PCT × CONDITIONAL_RETENTION (decomposition)
        decompose_diff = (df_drug_coef["COEF_1"]
                          - df_drug_coef["COVERAGE_PCT"]
                          * df_drug_coef["CONDITIONAL_RETENTION"]).abs().max()
        check("DC_DECOMPOSE_FORMULA",
              decompose_diff < DECOMPOSE_EPSILON,
              f"max |COEF_1 - COVERAGE * CONDITIONAL| = {decompose_diff:.7f}")

        # RELIABILITY_SCORE діапазон [0, 1]
        rel_in_range = ((df_drug_coef["RELIABILITY_SCORE"] >= 0) &
                        (df_drug_coef["RELIABILITY_SCORE"] <= 1)).all()
        check("DC_RELIABILITY_IN_0_1",
              bool(rel_in_range),
              f"min={df_drug_coef['RELIABILITY_SCORE'].min():.4f}, "
              f"max={df_drug_coef['RELIABILITY_SCORE'].max():.4f}")
    else:
        check("DC_EMPTY_BUT_PROCESSED", True, "drug_coefficients is empty (no drugs passed threshold)")

    # === substitute_shares ===
    if len(df_sub_shares) > 0:
        check("SS_NO_NAN_SHARE",
              not df_sub_shares["SUBSTITUTE_SHARE"].isna().any(),
              f"NaN count: {df_sub_shares['SUBSTITUTE_SHARE'].isna().sum()}")

        in_range = ((df_sub_shares["SUBSTITUTE_SHARE"] >= 0) &
                    (df_sub_shares["SUBSTITUTE_SHARE"] <= 1)).all()
        check("SS_SHARE_IN_0_1",
              bool(in_range),
              f"min={df_sub_shares['SUBSTITUTE_SHARE'].min():.4f}, "
              f"max={df_sub_shares['SUBSTITUTE_SHARE'].max():.4f}")

        # Sum invariant
        sums = df_sub_shares.groupby("DRUGS_ID")["SUBSTITUTE_SHARE"].sum()
        diffs = (sums - 1.0).abs()
        max_diff = float(diffs.max())
        bad_drugs = int((diffs > SHARE_SUM_EPSILON).sum())
        check("SS_SUM_INVARIANT",
              max_diff < SHARE_SUM_EPSILON,
              f"max |sum-1.0| = {max_diff:.6f}, drugs with diff > {SHARE_SUM_EPSILON}: {bad_drugs}")

        # FK check: усі DRUGS_ID у sub_shares мають бути у drug_coef
        if len(df_drug_coef) > 0:
            accepted_ids = set(df_drug_coef["DRUGS_ID"])
            sub_drug_ids = set(df_sub_shares["DRUGS_ID"])
            orphans = sub_drug_ids - accepted_ids
            check("SS_DRUGS_ID_IN_DC",
                  len(orphans) == 0,
                  f"orphan DRUGS_IDs: {len(orphans)} (sample: {list(orphans)[:5]})")

        # No duplicates per (DRUGS_ID, SUBSTITUTE_DRUG_ID)
        dup = df_sub_shares.duplicated(subset=["DRUGS_ID", "SUBSTITUTE_DRUG_ID"]).sum()
        check("SS_NO_DUP_PAIRS",
              dup == 0,
              f"duplicates: {dup}")

        # Rank starts from 1 within each drug
        ranks_per_drug = df_sub_shares.groupby("DRUGS_ID")["SUBSTITUTE_RANK"].min()
        rank_starts_at_1 = (ranks_per_drug == 1).all()
        check("SS_RANK_STARTS_AT_1",
              bool(rank_starts_at_1),
              f"drugs without rank=1: {(ranks_per_drug != 1).sum()}")
    else:
        check("SS_EMPTY_BUT_PROCESSED", True, "substitute_shares is empty (no accepted drugs had pairs)")

    return validation


def write_validation_report(
    validation: Dict[str, Any],
    df_drug_coef: pd.DataFrame,
    df_sub_shares: pd.DataFrame,
    min_market_count: int,
    elapsed_sec: float,
    out_path: Path,
) -> None:
    """Записати validation_report.txt."""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write("VALIDATION REPORT — Phase C: Final Export\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")

        f.write(f"Filter:                MARKET_COUNT >= {min_market_count}\n")
        f.write(f"drug_coefficients rows: {len(df_drug_coef)}\n")
        f.write(f"substitute_shares rows: {len(df_sub_shares)}\n")
        f.write(f"Phase C elapsed:       {elapsed_sec:.2f} s\n\n")

        f.write("Validation checks:\n")
        for i, (name, passed) in enumerate(validation["checks"].items(), 1):
            status = "PASSED" if passed else "FAILED"
            detail = validation["details"].get(name, "")
            line = f"  [{i:>2}] {status}: {name}"
            if detail:
                line += f" — {detail}"
            f.write(line + "\n")

        f.write(f"\nOverall: {'ALL PASSED' if validation['all_pass'] else 'SOME FAILED'}\n")


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

def run_final_export(min_market_count: int = DEFAULT_MIN_MARKET_COUNT) -> Dict[str, Any]:
    """
    Phase C: формування 4 фінальних файлів для Power BI.

    Args:
        min_market_count: Поріг для фільтра DRUGS_ID (default 20).

    Returns:
        Dict із метриками + шляхами output файлів.
    """
    t0 = time.time()
    result: Dict[str, Any] = {
        "phase":               "C",
        "status":              "error",
        "elapsed_sec":         0.0,
        "min_market_count":    min_market_count,
        "drugs_input":         0,
        "drugs_accepted":      0,
        "drugs_rejected":      0,
        "subs_pairs_total":    0,
        "outputs":             {},
        "validation":          {},
        "all_pass":            False,
        "error":               None,
    }

    try:
        ensure_directories()
        FINAL_RESULTS_PATH.mkdir(parents=True, exist_ok=True)

        # 1. Load inputs
        df_drugs = load_drug_statistics()
        result["drugs_input"] = len(df_drugs)

        df_subs_market = load_all_substitute_shares()

        # 2. C0: Filter drugs
        df_accepted = df_drugs[
            df_drugs["MARKET_COUNT_TOTAL"] >= min_market_count
        ].copy()
        result["drugs_accepted"] = len(df_accepted)
        result["drugs_rejected"] = result["drugs_input"] - result["drugs_accepted"]
        accepted_ids = set(df_accepted["DRUGS_ID"].astype(int))

        # 3. C1: Build drug_coefficients
        df_drug_coef = build_drug_coefficients(df_accepted)

        # 4. C2: Build substitute_shares
        df_sub_shares = build_substitute_shares(df_subs_market, accepted_ids)
        result["subs_pairs_total"] = len(df_sub_shares)

        # 5. Save 4 files
        out_drug_coef_csv  = FINAL_RESULTS_PATH / OUT_DRUG_COEF_CSV
        out_drug_coef_xlsx = FINAL_RESULTS_PATH / OUT_DRUG_COEF_XLSX
        out_sub_csv        = FINAL_RESULTS_PATH / OUT_SUB_SHARES_CSV
        out_sub_xlsx       = FINAL_RESULTS_PATH / OUT_SUB_SHARES_XLSX

        save_csv(df_drug_coef, out_drug_coef_csv)
        save_xlsx(df_drug_coef, out_drug_coef_xlsx, sheet_name="Drug Coefficients")
        save_csv(df_sub_shares, out_sub_csv)
        save_xlsx(df_sub_shares, out_sub_xlsx, sheet_name="Substitute Shares")

        result["outputs"] = {
            "drug_coefficients_csv":  {
                "path": str(out_drug_coef_csv),
                "size_kb": round(out_drug_coef_csv.stat().st_size / 1024, 2),
                "rows": len(df_drug_coef),
            },
            "drug_coefficients_xlsx": {
                "path": str(out_drug_coef_xlsx),
                "size_kb": round(out_drug_coef_xlsx.stat().st_size / 1024, 2),
                "rows": len(df_drug_coef),
            },
            "substitute_shares_csv":  {
                "path": str(out_sub_csv),
                "size_kb": round(out_sub_csv.stat().st_size / 1024, 2),
                "rows": len(df_sub_shares),
            },
            "substitute_shares_xlsx": {
                "path": str(out_sub_xlsx),
                "size_kb": round(out_sub_xlsx.stat().st_size / 1024, 2),
                "rows": len(df_sub_shares),
            },
        }

        # 6. Validation
        validation = validate_outputs(df_drug_coef, df_sub_shares, min_market_count)
        result["validation"] = validation
        result["all_pass"] = validation["all_pass"]

        elapsed = time.time() - t0
        REPORTS_PATH.mkdir(parents=True, exist_ok=True)
        out_validation = REPORTS_PATH / OUT_VALIDATION_TXT
        write_validation_report(
            validation, df_drug_coef, df_sub_shares,
            min_market_count, elapsed, out_validation,
        )
        result["outputs"]["validation_report"] = {
            "path": str(out_validation),
            "size_kb": round(out_validation.stat().st_size / 1024, 2),
        }

        result["status"] = "success"

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()

    result["elapsed_sec"] = round(time.time() - t0, 2)
    return result


# =============================================================================
# DISPLAY
# =============================================================================

def print_final_export_result(result: Dict[str, Any]) -> None:
    """Гарний вивід результату Phase C."""
    console = Console()

    status = result["status"]
    color = {"success": "green", "error": "red"}.get(status, "white")
    title = f"Phase C (Final Export) — [{color}]{status.upper()}[/{color}]"
    console.print(Panel.fit(title, border_style=color))

    if status == "error":
        if result.get("error"):
            rprint(f"[red]Error:[/red] {result['error']}")
        if result.get("traceback"):
            rprint(f"\n[dim]{result['traceback']}[/dim]")
        return

    # Summary table
    summary = Table(show_header=True, header_style="bold")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", justify="right")
    summary.add_row("MIN_MARKET_COUNT filter",      f">= {result['min_market_count']}")
    summary.add_row("Drugs input (Phase B)",        f"{result['drugs_input']:,}")
    summary.add_row("[green]Drugs accepted[/green]",f"{result['drugs_accepted']:,}")
    summary.add_row("[yellow]Drugs rejected[/yellow]", f"{result['drugs_rejected']:,}")
    summary.add_row("Substitute pairs",             f"{result['subs_pairs_total']:,}")
    summary.add_row("Elapsed",                      f"{result['elapsed_sec']:.2f} s")
    invariant_color = "green" if result['all_pass'] else "red"
    invariant_str = "ALL PASSED" if result['all_pass'] else "SOME FAILED"
    summary.add_row(f"[{invariant_color}]Validation[/{invariant_color}]", invariant_str)
    console.print(summary)

    # Outputs table
    out_table = Table(title="Output files", show_header=True, header_style="bold")
    out_table.add_column("File", style="cyan")
    out_table.add_column("Rows", justify="right")
    out_table.add_column("Size KB", justify="right")
    for key, info in result["outputs"].items():
        out_table.add_row(
            Path(info["path"]).name,
            f"{info.get('rows', '-')}" if isinstance(info.get('rows'), int) else "-",
            f"{info['size_kb']:.2f}",
        )
    console.print(out_table)

    # Validation details
    val = result.get("validation", {})
    if val.get("checks"):
        check_table = Table(title="Validation checks", show_header=True, header_style="bold")
        check_table.add_column("#", style="dim")
        check_table.add_column("Check", style="cyan")
        check_table.add_column("Status", justify="center")
        check_table.add_column("Detail", style="dim")
        for i, (name, passed) in enumerate(val["checks"].items(), 1):
            stat = "[green]PASSED[/green]" if passed else "[red]FAILED[/red]"
            detail = val["details"].get(name, "")
            check_table.add_row(str(i), name, stat, detail)
        console.print(check_table)


# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase C — Final Export (4 файли для Power BI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  python -m pipeline.final_export                       # default min=20\n"
               "  python -m pipeline.final_export --min-market-count 3  # smoke-test\n",
    )
    parser.add_argument(
        "--min-market-count", "-m",
        type=int, default=DEFAULT_MIN_MARKET_COUNT,
        help=f"Поріг MARKET_COUNT для фільтра (default {DEFAULT_MIN_MARKET_COUNT}, "
             f"Sequential Analyzer Study 02)",
    )

    args = parser.parse_args()

    try:
        result = run_final_export(min_market_count=args.min_market_count)
        print_final_export_result(result)
        return 0 if result["status"] == "success" and result["all_pass"] else 1
    except FileNotFoundError as e:
        rprint(f"[red]ERROR:[/red] {e}")
        return 1
    except KeyboardInterrupt:
        rprint("\n[yellow]Interrupted.[/yellow]")
        return 130
    except Exception as e:
        rprint(f"[red]UNEXPECTED ERROR:[/red] {type(e).__name__}: {e}")
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
