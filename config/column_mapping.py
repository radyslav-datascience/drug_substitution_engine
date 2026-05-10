# =============================================================================
# COLUMN MAPPING - drug_substitution_engine
# =============================================================================
# Файл: config/column_mapping.py
# Дата: 2026-04-27
# Опис: Маппінг та стандартизація колонок CSV файлів
# =============================================================================

"""
Конфігурація маппінгу колонок (адаптована з канонічного проекту).

Структура raw CSV (з DATA_SETS/pd_ds_4_pres/{CLIENT_ID}.csv):
    13 обов'язкових колонок, separator ';'

Логіка:
    - RAW_REQUIRED_COLUMNS — для валідації при discovery (fail-fast)
    - COLUMN_RENAME_MAP — для переходу до канонічних назв у Phase A1
    - STANDARD_COLUMNS — після перейменування (для downstream обробки)

Використання:
    from config.column_mapping import (
        RAW_REQUIRED_COLUMNS,
        COLUMN_RENAME_MAP,
        validate_raw_columns,
    )
"""

from typing import Dict, List, Set


# =============================================================================
# RAW COLUMNS (як у CSV файлах DATA_SETS)
# =============================================================================

# 13 обов'язкових колонок — мають бути присутні у кожному raw CSV
RAW_REQUIRED_COLUMNS: List[str] = [
    "ORG_ID",                # ID аптеки-продавця
    "CLIENT_ID",             # ID цільової аптеки (= market identifier, константа per file)
    "DRUGS_ID",              # Morion ID препарату
    "PERIOD_ID",             # Дата у форматі YYYYNNNNN
    "Q",                     # Кількість упаковок (string з комою)
    "V",                     # Виручка (string з комою)
    "INN",                   # Назва INN групи
    "INN_ID",                # ID INN групи
    "Full medication name",  # Повна назва препарату
    "NFC Code (1)",          # Широка категорія форми випуску (NFC1)
    "NFC Code (2)",          # Специфічна форма випуску (NFC2)
    "ATC Code (4)",          # ATC класифікація рівень 4
    "ATC Code (5)",          # ATC класифікація рівень 5
]


# =============================================================================
# COLUMN RENAMING (Phase A1 — після discovery)
# =============================================================================

COLUMN_RENAME_MAP: Dict[str, str] = {
    "ORG_ID":               "PHARM_ID",     # ID аптеки-продавця
    "INN":                  "INN_NAME",
    "Full medication name": "DRUGS_NAME",
    "NFC Code (1)":         "NFC1_ID",
    "NFC Code (2)":         "NFC_ID",
}


# =============================================================================
# STANDARD COLUMNS (після перейменування)
# =============================================================================

STANDARD_COLUMNS: List[str] = [
    "CLIENT_ID",
    "PHARM_ID",     # ← ORG_ID
    "PERIOD_ID",
    "DRUGS_ID",
    "INN_ID",
    "INN_NAME",     # ← INN
    "Q",
    "V",
    "DRUGS_NAME",   # ← Full medication name
    "NFC1_ID",      # ← NFC Code (1)
    "NFC_ID",       # ← NFC Code (2)
]

# Для discovery (drugs_list) — лише ці 2 колонки потрібні
DRUGS_LIST_COLUMNS: List[str] = ["DRUGS_ID", "Full medication name"]

# Колонки що ми реально використовуємо в Phase A (без ATC, які не задіяні).
# Передаємо як `usecols` у pd.read_csv для економії I/O на HDD (~10-15%).
# ISSUE-005 fix у `_methods_issues.md`.
USEFUL_COLUMNS: List[str] = [
    c for c in RAW_REQUIRED_COLUMNS if not c.startswith("ATC Code")
]
# = ['ORG_ID', 'CLIENT_ID', 'DRUGS_ID', 'PERIOD_ID', 'Q', 'V', 'INN', 'INN_ID',
#    'Full medication name', 'NFC Code (1)', 'NFC Code (2)']


# =============================================================================
# DATA TYPES
# =============================================================================

COLUMN_DTYPES: Dict[str, str] = {
    "CLIENT_ID":  "int64",
    "PHARM_ID":   "int64",
    "PERIOD_ID":  "int64",
    "DRUGS_ID":   "int64",
    "INN_ID":     "int64",
    "Q":          "float64",
    "V":          "float64",
    "INN_NAME":   "string",
    "DRUGS_NAME": "string",
    "NFC1_ID":    "string",
    "NFC_ID":     "string",
}

NUMERIC_COLUMNS: List[str] = ["Q", "V"]
ID_COLUMNS:      List[str] = ["CLIENT_ID", "PHARM_ID", "DRUGS_ID", "INN_ID"]

CATEGORICAL_COLUMNS: List[str] = [
    "DRUGS_NAME", "INN_NAME", "NFC1_ID", "NFC_ID",
]


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_raw_columns(columns: List[str]) -> List[str]:
    """
    Перевірити що в raw CSV є всі потрібні колонки.

    Args:
        columns: Список колонок з df.

    Returns:
        Список відсутніх колонок (порожній якщо все OK).
    """
    cols_set: Set[str] = set(columns)
    return [c for c in RAW_REQUIRED_COLUMNS if c not in cols_set]


def validate_standard_columns(columns: List[str]) -> List[str]:
    """
    Перевірити що після перейменування є всі стандартні колонки.

    Args:
        columns: Список колонок з df.

    Returns:
        Список відсутніх колонок.
    """
    cols_set: Set[str] = set(columns)
    return [c for c in STANDARD_COLUMNS if c not in cols_set]


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("COLUMN MAPPING — drug_substitution_engine")
    print("=" * 60)

    print(f"\nRAW_REQUIRED_COLUMNS ({len(RAW_REQUIRED_COLUMNS)}):")
    for c in RAW_REQUIRED_COLUMNS:
        print(f"  - {c}")

    print(f"\nCOLUMN_RENAME_MAP ({len(COLUMN_RENAME_MAP)}):")
    for old, new in COLUMN_RENAME_MAP.items():
        print(f"  {old!r:32} -> {new}")

    print(f"\nSTANDARD_COLUMNS ({len(STANDARD_COLUMNS)}):")
    for c in STANDARD_COLUMNS:
        print(f"  - {c}")

    # Тест валідації
    print("\nValidation tests:")
    test_ok = ["ORG_ID", "CLIENT_ID", "DRUGS_ID", "PERIOD_ID", "Q", "V", "INN",
               "INN_ID", "Full medication name", "NFC Code (1)", "NFC Code (2)",
               "ATC Code (4)", "ATC Code (5)"]
    test_missing = ["ORG_ID", "CLIENT_ID"]  # навмисно неповний

    print(f"  Full set: missing = {validate_raw_columns(test_ok)} (expected [])")
    print(f"  Partial:  missing = {validate_raw_columns(test_missing)} (expected 11 items)")
