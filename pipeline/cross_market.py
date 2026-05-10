# =============================================================================
# CROSS-MARKET AGGREGATION - drug_substitution_engine / Phase B
# =============================================================================
# Файл: pipeline/cross_market.py
# Дата: 2026-04-27
# Опис: Phase B — крос-ринкова агрегація did_events → drug_statistics.parquet.
# =============================================================================

"""
Phase B: Cross-Market Aggregation.

Збирає did_events.parquet з усіх ринків (`data/intermediate/01_per_market/*/`),
для кожного препарату обчислює (на рівні ринків, після IQR-фільтра):
    - MARKET_COUNT_TOTAL / MARKET_COUNT_CLEAN
    - MEAN_SHARE_INTERNAL       — середнє SHARE_INTERNAL по ринках (= COEF_1)
    - COVERAGE_PCT              — частка ринків з SHARE_INTERNAL > 0
    - CONDITIONAL_RETENTION     — середнє SHARE_INTERNAL серед ринків де SHARE > 0
    - MARKETS_WITH_SUB          — кількість ринків з SHARE_INTERNAL > 0
    - DRUG_CLASS / DIP_PVALUE   — UNIMODAL / MULTIMODAL (Hartigan dip test)

Декомпозиційний інваріант: MEAN_SHARE_INTERNAL = COVERAGE_PCT × CONDITIONAL_RETENTION.

Призначений до запуску ПІСЛЯ повного Phase A pipeline runner-а.
Працює також на partial datasets (для smoke-test).

Вхід:
    data/intermediate/01_per_market/{CLIENT_ID}/did_events.parquet
    data/intermediate/01_per_market/{CLIENT_ID}/stockout_events.parquet (для INN_NAME)

Вихід:
    data/intermediate/02_cross_market/drug_statistics.parquet

CLI:
    python -m pipeline.cross_market
    python -m pipeline.cross_market --markets-pattern "29578 30654 74521 75129"  # filter
"""

import argparse
import sys
import time
import traceback
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
    ensure_directories,
)


# =============================================================================
# CONSTANTS
# =============================================================================

# IQR multiplier (стандартний Tukey)
IQR_MULTIPLIER: float = 1.5

# Hartigan dip test alpha (поріг значущості)
DIP_TEST_ALPHA: float = 0.05

# Мінімум значень SHARE для застосування dip test
# Менше → класифікуємо як UNIMODAL за замовчуванням
MIN_N_FOR_DIPTEST: int = 4

# Reliability score parameters (canonical-style + composite extension)
# VARIATION_COEFFICIENT thresholds для RELIABILITY_LABEL
RELIABILITY_HIGH_THRESHOLD:   float = 0.15   # CV < 0.15 → HIGH
RELIABILITY_MEDIUM_THRESHOLD: float = 0.30   # CV < 0.30 → MEDIUM, інакше → LOW

# Sample-size factor для RELIABILITY_SCORE: log10(MC)/log10(SAMPLE_SATURATION) — 1.0 при 150+ ринків
SAMPLE_SATURATION_MARKETS: int = 150

# Modality penalty для MULTIMODAL (одне число COEF_1 менш репрезентативне для бімодальних)
MULTIMODAL_PENALTY: float = 0.85

# Output filename
DRUG_STATISTICS_PARQUET = "drug_statistics.parquet"
PARQUET_ENGINE          = "pyarrow"
PARQUET_COMPRESS        = "snappy"

# Per-market parquet filenames (consume from Phase A)
DID_EVENTS_FILE       = "did_events.parquet"
STOCKOUT_EVENTS_FILE  = "stockout_events.parquet"

# Output column order
DRUG_STATISTICS_COLUMNS = [
    "DRUGS_ID", "DRUGS_NAME",
    "INN_ID", "INN_NAME",
    "NFC1_ID",
    "MARKET_COUNT_TOTAL",
    "MARKET_COUNT_CLEAN",
    "MEAN_SHARE_INTERNAL",
    "COVERAGE_PCT",
    "CONDITIONAL_RETENTION",
    "MARKETS_WITH_SUB",
    "DRUG_CLASS",
    "DIP_PVALUE",
    "STD_SHARE_INTERNAL",   # розкид SHARE_INTERNAL по ринках (після IQR)
    "VARIATION_COEF",       # CV = STD/MEAN (нормалізований розкид)
    "RELIABILITY_LABEL",    # HIGH / MEDIUM / LOW / SINGLE_MARKET (canonical-style)
    "RELIABILITY_SCORE",    # composite 0..1 (stability × sample × modality)
]


# =============================================================================
# DATA LOADING
# =============================================================================

def find_market_dirs(per_market_path: Path = PER_MARKET_PATH) -> List[Path]:
    """
    Знайти всі підпапки `01_per_market/{CLIENT_ID}/` що містять did_events.parquet.

    Returns:
        List of Path objects (по одному на ринок).
    """
    if not per_market_path.exists():
        return []
    market_dirs = []
    for child in per_market_path.iterdir():
        if child.is_dir() and (child / DID_EVENTS_FILE).exists():
            market_dirs.append(child)
    return sorted(market_dirs)


def load_did_events_all(market_dirs: List[Path]) -> pd.DataFrame:
    """
    Конкатенувати did_events.parquet з усіх ринків.

    Returns:
        Один DataFrame з колонкою CLIENT_ID для розрізнення ринків.
    """
    if not market_dirs:
        return pd.DataFrame()

    frames = []
    for d in market_dirs:
        f = d / DID_EVENTS_FILE
        try:
            df = pd.read_parquet(f, engine=PARQUET_ENGINE)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            rprint(f"[yellow]WARN:[/yellow] failed to read {f.name} from {d.name}: {e}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def build_inn_name_lookup(market_dirs: List[Path]) -> Dict[int, str]:
    """
    Зібрати INN_ID → INN_NAME mapping з усіх stockout_events.parquet.

    INN_NAME не зберігається в did_events.parquet, тому беремо з stockout_events.
    """
    lookup: Dict[int, str] = {}
    for d in market_dirs:
        f = d / STOCKOUT_EVENTS_FILE
        if not f.exists():
            continue
        try:
            df = pd.read_parquet(f, engine=PARQUET_ENGINE, columns=["INN_ID", "INN_NAME"])
            for inn_id, inn_name in df.drop_duplicates().itertuples(index=False, name=None):
                if pd.notna(inn_name) and int(inn_id) not in lookup:
                    lookup[int(inn_id)] = str(inn_name)
        except Exception as e:
            rprint(f"[yellow]WARN:[/yellow] failed to read INN_NAME from {d.name}: {e}")
    return lookup


# =============================================================================
# AGGREGATION
# =============================================================================

def aggregate_per_market_drug(df_did: pd.DataFrame) -> pd.DataFrame:
    """
    Per-market drug aggregation: (CLIENT_ID, DRUGS_ID) → drug-level metrics.

    Метод: ratio of sums (стійкіше за mean of events).
        SHARE_INTERNAL_drug = SUM(INTERNAL_LIFT) / SUM(TOTAL_EFFECT)

    Returns:
        DataFrame з рядком на пару (CLIENT_ID, DRUGS_ID).
    """
    grouped = df_did.groupby(["CLIENT_ID", "DRUGS_ID"], sort=False).agg(
        INTERNAL_LIFT=("INTERNAL_LIFT", "sum"),
        LOST_SALES=("LOST_SALES", "sum"),
        TOTAL_EFFECT=("TOTAL_EFFECT", "sum"),
        EVENTS_COUNT=("EVENT_ID", "count"),
        DRUGS_NAME=("DRUGS_NAME", "first"),
        INN_ID=("INN_ID", "first"),
        NFC1_ID=("NFC1_ID", "first"),
    ).reset_index()

    # SHARE_INTERNAL — drug-level per market (ratio of sums)
    # Захист від ділення на нуль: TOTAL_EFFECT > 0 завжди для valid did_events
    # (бо у Phase A3 ми відсікли події з TOTAL_EFFECT < MIN_TOTAL_FOR_SHARE).
    grouped["SHARE_INTERNAL"] = grouped["INTERNAL_LIFT"] / grouped["TOTAL_EFFECT"]
    grouped = grouped.dropna(subset=["SHARE_INTERNAL"])
    return grouped


def iqr_outlier_filter(values: np.ndarray, k: float = IQR_MULTIPLIER) -> np.ndarray:
    """
    IQR outlier filter: повертає лише значення в межах [Q1 - k*IQR, Q3 + k*IQR].

    Args:
        values: Масив значень.
        k:      IQR multiplier (за замовчуванням 1.5).

    Returns:
        Очищений масив (клон, без outliers).
    """
    if len(values) == 0:
        return values
    q1, q3 = np.percentile(values, [25, 75])
    iqr = q3 - q1
    lower = q1 - k * iqr
    upper = q3 + k * iqr
    mask = (values >= lower) & (values <= upper)
    return values[mask]


def classify_modality(
    clean_values: np.ndarray,
    alpha: float = DIP_TEST_ALPHA,
    min_n: int = MIN_N_FOR_DIPTEST,
) -> tuple:
    """
    Класифікувати розподіл як UNIMODAL чи MULTIMODAL через Hartigan dip test.

    H0: розподіл унімодальний.
    Якщо p-value < alpha → відхиляємо H0 → MULTIMODAL.

    Якщо менше `min_n` спостережень — за замовчуванням UNIMODAL (тест ненадійний).

    Args:
        clean_values: Масив значень (після IQR фільтра).
        alpha:        Поріг значущості (default 0.05).
        min_n:        Мінімум значень для тесту (default 4).

    Returns:
        (drug_class: str, p_value: float)
    """
    n = len(clean_values)
    if n < min_n:
        return "UNIMODAL", 1.0

    # diptest — already in venv (requirements.txt)
    from diptest import diptest as _diptest
    try:
        dip, p_value = _diptest(clean_values)
    except Exception:
        # На випадок якщо diptest падає на edge cases (наприклад усі однакові значення)
        return "UNIMODAL", 1.0

    drug_class = "MULTIMODAL" if p_value < alpha else "UNIMODAL"
    return drug_class, float(p_value)


# =============================================================================
# RELIABILITY METRICS
# =============================================================================

def calculate_reliability(
    clean_shares: np.ndarray,
    mean_share: float,
    drug_class: str,
) -> Dict[str, Any]:
    """
    Розрахувати показники надійності COEF_1 для одного препарату.

    Повертає 4 поля:
        STD_SHARE_INTERNAL   — std розкид SHARE_INTERNAL по ринках (після IQR)
        VARIATION_COEF       — CV = STD/MEAN (з guard rails для MEAN ≈ 0)
        RELIABILITY_LABEL    — HIGH / MEDIUM / LOW / SINGLE_MARKET
        RELIABILITY_SCORE    — composite 0..1 для відбору top-N надійних

    Формула RELIABILITY_SCORE:
        stability        = clip(1 - CV, 0, 1)               (якщо MEAN > 0)
                         = 1.0 при MEAN=0 та STD=0           (стабільно нуль)
                         = 0.0 при STD > MEAN                (більший розкид за середнє)
        sample_factor    = min(1, log10(MC_CLEAN) / log10(SAMPLE_SATURATION_MARKETS))
        modality_penalty = MULTIMODAL_PENALTY якщо MULTIMODAL, інакше 1.0
        SCORE            = stability × sample_factor × modality_penalty

    Edge cases:
        MARKET_COUNT_CLEAN < 2 → SCORE=0.0, LABEL='SINGLE_MARKET'
    """
    n = len(clean_shares)
    std = float(np.std(clean_shares, ddof=1)) if n >= 2 else 0.0

    # CV з guard rails
    if mean_share > 0:
        cv = std / mean_share
    elif std == 0:
        cv = 0.0   # стабільно нуль — нульова варіація
    else:
        cv = float("inf")  # mean=0 але std>0 не виникає для SHARE ∈ [0,1], але safe-guard

    # RELIABILITY_LABEL (canonical-style)
    if n < 2:
        label = "SINGLE_MARKET"
    elif cv < RELIABILITY_HIGH_THRESHOLD:
        label = "HIGH"
    elif cv < RELIABILITY_MEDIUM_THRESHOLD:
        label = "MEDIUM"
    else:
        label = "LOW"

    # RELIABILITY_SCORE (composite)
    if n < 2:
        score = 0.0
    else:
        # Stability factor
        if mean_share > 0:
            stability = max(0.0, min(1.0, 1.0 - cv))
        elif std == 0:
            stability = 1.0   # стабільно нуль = надійно (хоча малокорисно для бізнесу)
        else:
            stability = 0.0

        # Sample-size factor (log scale, saturates at SAMPLE_SATURATION_MARKETS)
        sample_factor = min(1.0, float(np.log10(max(n, 1)) / np.log10(SAMPLE_SATURATION_MARKETS)))

        # Modality penalty
        modality_penalty = MULTIMODAL_PENALTY if drug_class == "MULTIMODAL" else 1.0

        score = stability * sample_factor * modality_penalty

    return {
        "STD_SHARE_INTERNAL": round(std, 6),
        "VARIATION_COEF":     round(cv, 6) if np.isfinite(cv) else 999.0,
        "RELIABILITY_LABEL":  label,
        "RELIABILITY_SCORE":  round(float(score), 6),
    }


def aggregate_cross_market(
    per_market_drug: pd.DataFrame,
    inn_name_lookup: Dict[int, str],
) -> pd.DataFrame:
    """
    Для кожного DRUGS_ID агрегуємо SHARE_INTERNAL across markets:
        - IQR filter (Tukey 1.5×) на SHARE_INTERNAL по ринках
        - mean → MEAN_SHARE_INTERNAL                  (= COEF_1 у Phase C)
        - частка ринків з SHARE > 0 → COVERAGE_PCT
        - mean(SHARE | SHARE > 0) → CONDITIONAL_RETENTION
        - count(SHARE > 0) → MARKETS_WITH_SUB
        - dip test на clean_shares → DRUG_CLASS / DIP_PVALUE

    Декомпозиція (математичний інваріант):
        MEAN_SHARE_INTERNAL = COVERAGE_PCT × CONDITIONAL_RETENTION

    Returns:
        DataFrame з 13 колонками згідно DRUG_STATISTICS_COLUMNS.
    """
    rows = []
    for drug_id, group in per_market_drug.groupby("DRUGS_ID", sort=True):
        shares = group["SHARE_INTERNAL"].dropna().to_numpy()
        if len(shares) == 0:
            continue

        clean_shares = iqr_outlier_filter(shares, k=IQR_MULTIPLIER)
        # Якщо IQR прибрав ВСЕ (рідкісно — наприклад n=1 і IQR=0) — використовуємо raw
        if len(clean_shares) == 0:
            clean_shares = shares

        drug_class, dip_p = classify_modality(clean_shares,
                                               alpha=DIP_TEST_ALPHA,
                                               min_n=MIN_N_FOR_DIPTEST)

        # Нові метрики (на рівні ринків, після IQR)
        mean_share        = float(np.mean(clean_shares))
        nonzero           = clean_shares[clean_shares > 0]
        markets_with_sub  = int(len(nonzero))
        coverage_pct      = float(markets_with_sub / len(clean_shares))
        cond_retention    = float(np.mean(nonzero)) if markets_with_sub > 0 else 0.0

        # Reliability (3 діагностичні поля + 1 composite score)
        rel = calculate_reliability(clean_shares, mean_share, drug_class)

        inn_id = int(group["INN_ID"].iloc[0])
        rows.append({
            "DRUGS_ID":              int(drug_id),
            "DRUGS_NAME":            str(group["DRUGS_NAME"].iloc[0]),
            "INN_ID":                inn_id,
            "INN_NAME":              inn_name_lookup.get(inn_id, ""),
            "NFC1_ID":               str(group["NFC1_ID"].iloc[0]),
            "MARKET_COUNT_TOTAL":    int(len(shares)),
            "MARKET_COUNT_CLEAN":    int(len(clean_shares)),
            "MEAN_SHARE_INTERNAL":   round(mean_share, 6),
            "COVERAGE_PCT":          round(coverage_pct, 6),
            "CONDITIONAL_RETENTION": round(cond_retention, 6),
            "MARKETS_WITH_SUB":      markets_with_sub,
            "DRUG_CLASS":            drug_class,
            "DIP_PVALUE":            round(dip_p, 6),
            "STD_SHARE_INTERNAL":    rel["STD_SHARE_INTERNAL"],
            "VARIATION_COEF":        rel["VARIATION_COEF"],
            "RELIABILITY_LABEL":     rel["RELIABILITY_LABEL"],
            "RELIABILITY_SCORE":     rel["RELIABILITY_SCORE"],
        })

    df_stats = pd.DataFrame(rows, columns=DRUG_STATISTICS_COLUMNS)
    df_stats = df_stats.sort_values("MEAN_SHARE_INTERNAL", ascending=False).reset_index(drop=True)
    return df_stats


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

def run_cross_market(
    market_filter: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Виконати Phase B на всіх (або вказаних) ринках.

    Args:
        market_filter: Якщо задано — обробити лише ринки з цими CLIENT_ID.

    Returns:
        Dict із метриками + шлях до output.
    """
    t0 = time.time()
    result: Dict[str, Any] = {
        "phase":                  "B",
        "status":                 "error",
        "elapsed_sec":            0.0,
        "markets_found":          0,
        "events_total":           0,
        "per_market_drug_pairs":  0,
        "drugs_total":            0,
        "drugs_unimodal":         0,
        "drugs_multimodal":       0,
        "drugs_with_outliers":    0,
        "output_path":            "",
        "output_size_mb":         0.0,
        "error":                  None,
    }

    try:
        ensure_directories()
        market_dirs = find_market_dirs()

        if market_filter is not None:
            filter_set = {int(c) for c in market_filter}
            market_dirs = [d for d in market_dirs if int(d.name) in filter_set]

        result["markets_found"] = len(market_dirs)
        if not market_dirs:
            result["status"] = "no_data"
            result["error"]  = "No markets with did_events.parquet found"
            result["elapsed_sec"] = round(time.time() - t0, 2)
            return result

        # 1. Load did_events from all markets
        df_did = load_did_events_all(market_dirs)
        result["events_total"] = len(df_did)

        if df_did.empty:
            result["status"] = "no_data"
            result["error"]  = "All did_events.parquet are empty"
            result["elapsed_sec"] = round(time.time() - t0, 2)
            return result

        # 2. INN_NAME lookup
        inn_name_lookup = build_inn_name_lookup(market_dirs)

        # 3. Per-market drug aggregation
        per_market_drug = aggregate_per_market_drug(df_did)
        result["per_market_drug_pairs"] = len(per_market_drug)

        # 4. Cross-market aggregation per drug
        df_stats = aggregate_cross_market(per_market_drug, inn_name_lookup)

        result["drugs_total"]       = len(df_stats)
        result["drugs_unimodal"]    = int((df_stats["DRUG_CLASS"] == "UNIMODAL").sum())
        result["drugs_multimodal"]  = int((df_stats["DRUG_CLASS"] == "MULTIMODAL").sum())
        result["drugs_with_outliers"] = int((df_stats["MARKET_COUNT_CLEAN"] < df_stats["MARKET_COUNT_TOTAL"]).sum())

        # 5. Save parquet
        out_path = CROSS_MARKET_PATH / DRUG_STATISTICS_PARQUET
        df_stats.to_parquet(out_path, engine=PARQUET_ENGINE,
                            compression=PARQUET_COMPRESS, index=False)
        result["output_path"]    = str(out_path)
        result["output_size_mb"] = round(out_path.stat().st_size / (1024 * 1024), 4)
        result["status"]         = "success"

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()

    result["elapsed_sec"] = round(time.time() - t0, 2)
    return result


# =============================================================================
# DISPLAY
# =============================================================================

def print_cross_market_result(result: Dict[str, Any]) -> None:
    """Гарний вивід результату."""
    console = Console()

    status = result["status"]
    color = {"success": "green", "no_data": "yellow", "error": "red"}.get(status, "white")
    title = f"Phase B (Cross-Market Aggregation) — [{color}]{status.upper()}[/{color}]"
    console.print(Panel.fit(title, border_style=color))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Markets found",           f"{result['markets_found']}")
    table.add_row("DiD events total",        f"{result['events_total']:,}")
    table.add_row("Per-market drug pairs",   f"{result['per_market_drug_pairs']:,}")
    table.add_row("[green]Unique drugs[/green]",         f"{result['drugs_total']:,}")
    table.add_row("[blue]UNIMODAL[/blue]",               f"{result['drugs_unimodal']}")
    table.add_row("[magenta]MULTIMODAL[/magenta]",       f"{result['drugs_multimodal']}")
    table.add_row("Drugs with IQR-filtered outliers",     f"{result['drugs_with_outliers']}")
    table.add_row("Output size",             f"{result['output_size_mb']:.4f} MB")
    table.add_row("Elapsed",                 f"{result['elapsed_sec']:.2f} s")
    if result.get("output_path"):
        table.add_row("Output", str(result["output_path"]))
    if result.get("error"):
        table.add_row("[red]Error[/red]", result["error"])
    console.print(table)


# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase B — Cross-Market Aggregation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  python -m pipeline.cross_market\n"
               "  python -m pipeline.cross_market --markets 29578 30654 74521 75129\n",
    )
    parser.add_argument(
        "--markets", "-m",
        nargs="+", type=int, default=None, metavar="ID",
        help="Лише вказані CLIENT_ID (default: усі ринки з did_events.parquet)",
    )

    args = parser.parse_args()

    try:
        result = run_cross_market(market_filter=args.markets)
        print_cross_market_result(result)
        if result.get("traceback"):
            rprint(f"\n[dim]{result['traceback']}[/dim]")
        return 0 if result["status"] in ("success", "no_data") else 1
    except KeyboardInterrupt:
        rprint("\n[yellow]Interrupted.[/yellow]")
        return 130
    except Exception as e:
        rprint(f"[red]UNEXPECTED ERROR:[/red] {type(e).__name__}: {e}")
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
