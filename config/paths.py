# =============================================================================
# PATHS CONFIGURATION - drug_substitution_engine
# =============================================================================
# Файл: config/paths.py
# Дата: 2026-04-27
# Опис: Централізована конфігурація шляхів обчислювального pipeline.
# =============================================================================

r"""
Конфігурація шляхів для проекту drug_substitution_engine.

Особливості:
    - Raw data — зовнішня read-only папка з транзакційними CSV (див. RAW_DATA_PATH).
    - Intermediate + results — всередині проекту (через HDD-стратегію без копіювання raw).
    - Імена raw файлів: {CLIENT_ID}.csv (без префіксу).
    - CLIENT_ID отримується з вмісту файлу (колонка), не з імені.

Використання:
    from config.paths import (
        RAW_DATA_PATH,
        INTERMEDIATE_PATH,
        FINAL_RESULTS_PATH,
        ensure_directories,
    )
"""

import os
from pathlib import Path
from typing import Dict, List
import pandas as pd


# =============================================================================
# PROJECT ROOTS
# =============================================================================

_CURRENT_FILE = Path(__file__).resolve()
CONFIG_PATH   = _CURRENT_FILE.parent          # drug_substitution_engine/config/
PROJECT_ROOT  = CONFIG_PATH.parent            # drug_substitution_engine/

# Шлях до raw CSV. Engine — dataset-agnostic, тому читаємо з env var із
# fallback на локальну папку `data/raw/` всередині проекту, щоб свіжий клон
# репо «просто запрацював», коли користувач кладе CSV туди.
# Override через:
#     PowerShell:  $env:DRUG_SUB_RAW_DATA = "D:\path\to\raw"
#     bash:        export DRUG_SUB_RAW_DATA=/path/to/raw
#     CMD:         set DRUG_SUB_RAW_DATA=D:\path\to\raw
# Формат CSV — див. docs/_data_format.md.
RAW_DATA_PATH = Path(os.environ.get(
    "DRUG_SUB_RAW_DATA",
    str(PROJECT_ROOT / "data" / "raw"),
))


# =============================================================================
# PROJECT-INTERNAL PATHS
# =============================================================================

DATA_PATH         = PROJECT_ROOT / "data"
INTERMEDIATE_PATH = DATA_PATH / "intermediate"
MASTER_PATH       = DATA_PATH / "master"       # accumulating master data: nfc1_config, (future) inn_registry, drugs_registry
RESULTS_PATH      = PROJECT_ROOT / "results"
LOGS_PATH         = PROJECT_ROOT / "logs"
REPORTS_PATH      = PROJECT_ROOT / "reports"   # business_report, validation_report, data_dictionary

# Phase A0 — discovery output
PREPROC_OUTPUT_PATH = INTERMEDIATE_PATH / "00_preproc"

# Phase A1-A5 — per-market intermediate
PER_MARKET_PATH = INTERMEDIATE_PATH / "01_per_market"

# Phase B — cross-market intermediate
CROSS_MARKET_PATH = INTERMEDIATE_PATH / "02_cross_market"

# Master data (accumulating registries)
NFC1_CONFIG_PATH = MASTER_PATH / "nfc1_config.json"

# Phase C — final outputs (для Power BI)
FINAL_RESULTS_PATH = RESULTS_PATH / "final"


# =============================================================================
# PHASE A0 (DISCOVERY) ARTIFACT FILES
# =============================================================================

PREPROC_FILES = {
    "markets_list":       PREPROC_OUTPUT_PATH / "markets_list.csv",
    "markets_statistics": PREPROC_OUTPUT_PATH / "markets_statistics.csv",
    "drugs_list":         PREPROC_OUTPUT_PATH / "drugs_list.csv",
}


# =============================================================================
# PER-MARKET PATHS (Phase A5)
# =============================================================================

def get_market_intermediate_dir(client_id: int) -> Path:
    """
    Папка для проміжних результатів одного ринку.

    Args:
        client_id: ID цільової аптеки.

    Returns:
        Path: data/intermediate/01_per_market/{client_id}/
    """
    return PER_MARKET_PATH / str(client_id)


def get_market_intermediate_files(client_id: int) -> Dict[str, Path]:
    """
    Шляхи до 2 intermediate CSV файлів одного ринку.

    Returns:
        {'sub_coef': Path, 'sub_drugs': Path}
    """
    market_dir = get_market_intermediate_dir(client_id)
    return {
        "sub_coef":  market_dir / "sub_coef.csv",
        "sub_drugs": market_dir / "sub_drugs.csv",
    }


# =============================================================================
# FINAL RESULTS PATHS (Phase C)
# =============================================================================

FINAL_FILES = {
    "drug_coefficients_csv":    FINAL_RESULTS_PATH / "drug_coefficients.csv",
    "drug_coefficients_xlsx":   FINAL_RESULTS_PATH / "drug_coefficients.xlsx",
    "substitute_shares_csv":    FINAL_RESULTS_PATH / "substitute_shares.csv",
    "substitute_shares_xlsx":   FINAL_RESULTS_PATH / "substitute_shares.xlsx",
    "validation_report":        FINAL_RESULTS_PATH / "validation_report.txt",
}


# =============================================================================
# FILE FORMAT CONSTANTS
# =============================================================================

RAW_FILE_PATTERN = "*.csv"     # будь-який CSV (без префіксу Rd2_)
CSV_SEPARATOR    = ";"
CSV_ENCODING_OUT = "utf-8-sig" # для записів (BOM для Excel-сумісності)


# =============================================================================
# DATA LOADING HELPERS
# =============================================================================

def load_markets_list() -> pd.DataFrame:
    """
    Завантажити список валідних ринків з discover_markets.py output.

    Returns:
        DataFrame з колонками: CLIENT_ID, FILE_NAME, FILE_PATH, FILE_SIZE_MB, STATUS, REASON

    Raises:
        FileNotFoundError: Якщо preprocessing ще не виконувався.
    """
    file_path = PREPROC_FILES["markets_list"]
    if not file_path.exists():
        raise FileNotFoundError(
            f"markets_list.csv не знайдено: {file_path}\n"
            f"Спочатку виконайте discovery:\n"
            f"  python -m pipeline.discover_markets"
        )
    return pd.read_csv(file_path, sep=CSV_SEPARATOR)


def load_ready_market_ids() -> List[int]:
    """
    Завантажити список CLIENT_ID тільки тих ринків, що мають STATUS='READY'.

    Returns:
        List[int] — готові до обробки CLIENT_ID.
    """
    df = load_markets_list()
    ready = df[df["STATUS"] == "READY"]
    return ready["CLIENT_ID"].astype(int).tolist()


# =============================================================================
# DIRECTORY MANAGEMENT
# =============================================================================

def ensure_directories() -> None:
    """
    Створити всі необхідні внутрішні папки проекту, якщо їх немає.

    Не створює RAW_DATA_PATH (зовнішня, read-only).
    """
    dirs = [
        DATA_PATH,
        INTERMEDIATE_PATH,
        MASTER_PATH,
        PREPROC_OUTPUT_PATH,
        PER_MARKET_PATH,
        CROSS_MARKET_PATH,
        RESULTS_PATH,
        FINAL_RESULTS_PATH,
        LOGS_PATH,
        REPORTS_PATH,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def validate_raw_data_path() -> bool:
    """
    Перевірити що зовнішня папка з raw даними існує і містить хоча б один CSV.

    Returns:
        True якщо все OK.

    Raises:
        FileNotFoundError: Якщо папка відсутня.
        ValueError: Якщо немає жодного CSV.
    """
    if not RAW_DATA_PATH.exists():
        raise FileNotFoundError(
            f"RAW_DATA_PATH не існує: {RAW_DATA_PATH}\n"
            f"Перевірте що датасет на місці."
        )
    csv_files = list(RAW_DATA_PATH.glob(RAW_FILE_PATTERN))
    if not csv_files:
        raise ValueError(
            f"У папці {RAW_DATA_PATH} немає жодного {RAW_FILE_PATTERN} файлу."
        )
    return True


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PATHS CONFIGURATION — drug_substitution_engine")
    print("=" * 60)
    print(f"\nPROJECT_ROOT:        {PROJECT_ROOT}")
    print(f"RAW_DATA_PATH:       {RAW_DATA_PATH}")
    print(f"INTERMEDIATE_PATH:   {INTERMEDIATE_PATH}")
    print(f"FINAL_RESULTS_PATH:  {FINAL_RESULTS_PATH}")
    print(f"\nValidating raw data path...")
    try:
        validate_raw_data_path()
        n_files = len(list(RAW_DATA_PATH.glob(RAW_FILE_PATTERN)))
        print(f"  OK: знайдено {n_files} CSV файлів у {RAW_DATA_PATH}")
    except (FileNotFoundError, ValueError) as e:
        print(f"  FAIL: {e}")
    print("\nEnsuring internal directories...")
    ensure_directories()
    print("  OK")
