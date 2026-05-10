# =============================================================================
# DISCOVER MARKETS - drug_substitution_engine / Phase A0
# =============================================================================
# Файл: pipeline/discover_markets.py
# Дата: 2026-04-27
# Опис: Phase A0 — швидке discovery ринків у DATA_SETS через sniff (nrows=3).
# =============================================================================

"""
Phase A0: Discovery — сканування DATA_SETS, валідація колонок, отримання CLIENT_ID
+ NFC1 discovery (накопичувальний master registry).

Відповідає канонічному `cross_pharm_market_analysis/exec_scripts/01_did_processing/01_preproc.py`
(адаптовано до нового scope; див. ROADMAP §4 та ALGORITHMS Phase A0).

Стратегія:
    1. Швидкий sniff (`nrows=3`) для отримання CLIENT_ID + валідації колонок.
    2. Повний read однієї колонки `NFC Code (1)` для збору унікальних NFC1
       форм випуску (variant b з обговорення — додатковий read лише потрібної
       колонки, ~5-10 хв на 152 GB raw).
    3. Оновлення `data/master/nfc1_config.json` (накопичувально):
       - all_categories: додаються нові, старі лишаються (історичні).
       - categories_history: трекає дату першої появи кожної категорії.
       - compatibility_groups, excluded: НІКОЛИ не перезаписуються (бізнес-правила).

Вхід:
    D:\\RADYSLAV_PROJECTS\\DATA_SETS\\pd_ds_4_pres\\*.csv  (read-only)

Вихід:
    data/intermediate/00_preproc/markets_list.csv
        Колонки: CLIENT_ID, FILE_NAME, FILE_PATH, FILE_SIZE_MB, STATUS, REASON
    data/master/nfc1_config.json
        Master registry NFC1 категорій з business rules.

Використання:
    # Повний запуск:
    python -m pipeline.discover_markets

    # Smoke-test на N перших файлах:
    python -m pipeline.discover_markets --limit 5
"""

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table
from rich.console import Console

# Project root → sys.path для імпортів config/ та core/
SCRIPT_PATH  = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.paths import (
    RAW_DATA_PATH,
    RAW_FILE_PATTERN,
    CSV_SEPARATOR,
    CSV_ENCODING_OUT,
    PREPROC_FILES,
    NFC1_CONFIG_PATH,
    ensure_directories,
    validate_raw_data_path,
)
from config.column_mapping import RAW_REQUIRED_COLUMNS, validate_raw_columns
from config.machine_params import MAX_FILE_SIZE_MB


# =============================================================================
# CONSTANTS
# =============================================================================

SNIFF_NROWS = 3  # читаємо лише перші 3 рядки для discovery
NFC1_RAW_COLUMN = "NFC Code (1)"  # назва колонки в raw CSV (до маппінгу)


# Можливі STATUS значення
STATUS_READY     = "READY"
STATUS_EMPTY     = "EMPTY"
STATUS_MALFORMED = "MALFORMED"
STATUS_OVERSIZED = "OVERSIZED"   # файл валідний, але розмір > MAX_FILE_SIZE_MB


# Default бізнес-правила для нового nfc1_config.json (тільки при першому
# створенні; на наступних запусках НЕ переписується).
DEFAULT_COMPATIBILITY_GROUPS: List[Dict[str, Any]] = [
    {
        "name": "ORAL_SOLID_RETARD",
        "description": "Тверді пероральні форми (звичайні + ретард-форми) — клінічно взаємозамінні.",
        "members": [
            "Пероральные твердые обычные",
            "Пероральные твердые длительно действующие",
        ],
    },
]
DEFAULT_EXCLUDED: List[str] = [
    "Не предназначенные для использования у человека и прочие",
]


# =============================================================================
# CORE: SNIFF SINGLE FILE
# =============================================================================

def sniff_market_file(file_path: Path) -> Dict[str, Any]:
    """
    Швидко перевірити один CSV: прочитати nrows=3, витягти CLIENT_ID,
    провалідувати колонки.

    НЕ читає повний файл (HDD-aware optimization). На 207 файлах ~ 1-2 сек загалом.

    Args:
        file_path: Шлях до CSV.

    Returns:
        Dict із полями:
            CLIENT_ID:    Optional[int]
            FILE_NAME:    str
            FILE_PATH:    str (absolute)
            FILE_SIZE_MB: float
            STATUS:       'READY' | 'EMPTY' | 'MALFORMED'
            REASON:       str (порожній якщо READY)
    """
    result: Dict[str, Any] = {
        "CLIENT_ID":    None,
        "FILE_NAME":    file_path.name,
        "FILE_PATH":    str(file_path),
        "FILE_SIZE_MB": 0.0,
        "STATUS":       STATUS_MALFORMED,
        "REASON":       "",
    }

    # Розмір файлу
    try:
        result["FILE_SIZE_MB"] = round(file_path.stat().st_size / (1024 * 1024), 2)
    except OSError as e:
        result["REASON"] = f"stat failed: {e}"
        return result

    # Sniff
    try:
        df = pd.read_csv(file_path, sep=CSV_SEPARATOR, nrows=SNIFF_NROWS)
    except pd.errors.EmptyDataError:
        result["STATUS"] = STATUS_EMPTY
        result["REASON"] = "empty file (no header)"
        return result
    except Exception as e:
        result["REASON"] = f"read_csv failed: {type(e).__name__}: {e}"
        return result

    # Empty check (header є, але рядків немає)
    if len(df) == 0:
        result["STATUS"] = STATUS_EMPTY
        result["REASON"] = "0 data rows"
        return result

    # Валідація колонок
    missing = validate_raw_columns(df.columns.tolist())
    if missing:
        result["REASON"] = f"missing columns: {missing}"
        return result

    # CLIENT_ID — має бути константним у файлі (sniff перевіряє лише перші 3 рядки)
    client_ids = df["CLIENT_ID"].unique()
    if len(client_ids) != 1:
        result["REASON"] = f"CLIENT_ID not constant in first {SNIFF_NROWS} rows: {client_ids.tolist()}"
        return result

    try:
        client_id = int(client_ids[0])
    except (ValueError, TypeError) as e:
        result["REASON"] = f"CLIENT_ID not integer: {client_ids[0]!r} ({e})"
        return result

    result["CLIENT_ID"] = client_id

    # Size filter — файл валідний, але занадто великий для безпечного процесингу.
    # Не помилка — просто виключаємо з pipeline через memory pressure.
    if result["FILE_SIZE_MB"] > MAX_FILE_SIZE_MB:
        result["STATUS"] = STATUS_OVERSIZED
        result["REASON"] = f"size {result['FILE_SIZE_MB']:.0f} MB > MAX_FILE_SIZE_MB ({MAX_FILE_SIZE_MB} MB)"
        return result

    result["STATUS"] = STATUS_READY
    return result


# =============================================================================
# NFC1 DISCOVERY (variant b: дочитуємо лише потрібну колонку повним read)
# =============================================================================

def scan_nfc1_in_file(file_path: Path) -> Set[str]:
    """
    Зчитати з CSV ЛИШЕ колонку `NFC Code (1)` та повернути множину унікальних
    значень. На відміну від sniff (nrows=3), читає весь файл, бо в одному
    ринку може бути багато різних NFC1.

    Args:
        file_path: Шлях до raw CSV.

    Returns:
        Set унікальних NFC1-значень (без NaN/порожніх).
    """
    try:
        col = pd.read_csv(
            file_path,
            sep=CSV_SEPARATOR,
            usecols=[NFC1_RAW_COLUMN],
        )[NFC1_RAW_COLUMN]
    except Exception:
        return set()

    return {str(v).strip() for v in col.dropna().unique() if str(v).strip()}


def update_nfc1_config(
    discovered: Set[str],
    files_scanned: int,
    config_path: Path = NFC1_CONFIG_PATH,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Накопичувально оновити master JSON з NFC1-категоріями.

    Поведінка:
        - Якщо JSON немає → створити з default compatibility_groups + excluded.
        - Якщо є → додати тільки нові категорії (не перезаписувати існуючі).
        - compatibility_groups і excluded НІКОЛИ не змінюються автоматично.
        - metadata.first_discovered_at — immutable.
        - metadata.last_discovered_at, last_run_files_scanned — оновлюються.

    Args:
        discovered:    Множина категорій, знайдених у поточному запуску discovery.
        files_scanned: Скільки raw файлів просканували.
        config_path:   Шлях до nfc1_config.json.

    Returns:
        (config, newly_added) — оновлений dict + список нових категорій.
    """
    now_iso  = datetime.now().isoformat(timespec="seconds")
    today    = datetime.now().date().isoformat()

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {
            "_comment": "Master data: NFC1 categories registry. Accumulating across runs.",
            "metadata": {
                "first_discovered_at":      now_iso,
                "last_discovered_at":       now_iso,
                "last_run_files_scanned":   files_scanned,
                "version":                  1,
            },
            "all_categories":       [],
            "categories_history":   {},
            "compatibility_groups": DEFAULT_COMPATIBILITY_GROUPS,
            "excluded":             DEFAULT_EXCLUDED,
        }

    existing = set(cfg.get("all_categories", []))
    newly_added = sorted(discovered - existing)

    # Накопичувано додаємо нові категорії
    if newly_added:
        cfg["all_categories"] = sorted(existing | set(newly_added))
        history = cfg.setdefault("categories_history", {})
        for cat in newly_added:
            history.setdefault(cat, today)

    # Оновлюємо тільки runtime-метаінформацію (не чіпаємо first_discovered_at)
    md = cfg.setdefault("metadata", {})
    md.setdefault("first_discovered_at", now_iso)
    md["last_discovered_at"]     = now_iso
    md["last_run_files_scanned"] = files_scanned
    md.setdefault("version", 1)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    return cfg, newly_added


# =============================================================================
# ORCHESTRATOR
# =============================================================================

def discover_markets(
    raw_dir: Path = RAW_DATA_PATH,
    pattern: str = RAW_FILE_PATTERN,
    limit: Optional[int] = None,
    collect_nfc1: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, int], Set[str]]:
    """
    Просканувати raw_dir, виконати sniff кожного CSV, зібрати унікальні NFC1.

    Args:
        raw_dir:      Папка з raw CSV.
        pattern:      Glob-маска для файлів.
        limit:        Якщо задано — обробити лише перші N файлів (smoke-test).
        collect_nfc1: Якщо True — на READY/OVERSIZED файлах додатково читає
                      колонку NFC Code (1) для побудови master registry.

    Returns:
        (df, summary, discovered_nfc1)
            df      — DataFrame зі всіма sniff результатами (READY/MALFORMED/EMPTY/OVERSIZED).
            summary — dict { 'total': N, 'ready': N, 'empty': N, 'malformed': N, ... }.
            discovered_nfc1 — set унікальних NFC1, виявлених у датасеті.
    """
    files = sorted(raw_dir.glob(pattern))
    if limit is not None:
        files = files[:limit]

    rows: List[Dict[str, Any]] = []
    discovered_nfc1: Set[str] = set()

    for file_path in files:
        try:
            row = sniff_market_file(file_path)
        except Exception as e:
            row = {
                "CLIENT_ID":    None,
                "FILE_NAME":    file_path.name,
                "FILE_PATH":    str(file_path),
                "FILE_SIZE_MB": round(file_path.stat().st_size / (1024 * 1024), 2)
                                if file_path.exists() else 0.0,
                "STATUS":       STATUS_MALFORMED,
                "REASON":       f"unhandled exception: {type(e).__name__}: {e}",
            }
        rows.append(row)

        # NFC1 scan: робимо тільки для файлів, які успішно пройшли sniff (READY або
        # OVERSIZED). MALFORMED/EMPTY скіпаємо — там не буде валідних даних.
        if collect_nfc1 and row["STATUS"] in (STATUS_READY, STATUS_OVERSIZED):
            try:
                discovered_nfc1 |= scan_nfc1_in_file(file_path)
            except Exception:
                # Не блокуємо discovery через помилку NFC1 read
                pass

    df = pd.DataFrame(rows, columns=[
        "CLIENT_ID", "FILE_NAME", "FILE_PATH", "FILE_SIZE_MB", "STATUS", "REASON",
    ])

    summary = {
        "total":     len(df),
        "ready":     int((df["STATUS"] == STATUS_READY).sum()),
        "empty":     int((df["STATUS"] == STATUS_EMPTY).sum()),
        "malformed": int((df["STATUS"] == STATUS_MALFORMED).sum()),
        "oversized": int((df["STATUS"] == STATUS_OVERSIZED).sum()),
    }
    return df, summary, discovered_nfc1


# =============================================================================
# OUTPUT
# =============================================================================

def save_markets_list(df: pd.DataFrame) -> Path:
    """
    Зберегти результат discovery у markets_list.csv.

    Args:
        df: DataFrame з результатами sniff (усі статуси).

    Returns:
        Шлях до збереженого файлу.
    """
    out_path = PREPROC_FILES["markets_list"]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Сортуємо: READY першими (за CLIENT_ID), потім OVERSIZED/EMPTY/MALFORMED
    df_out = df.copy()
    status_order = {STATUS_READY: 0, STATUS_OVERSIZED: 1, STATUS_EMPTY: 2, STATUS_MALFORMED: 3}
    df_out["_status_order"] = df_out["STATUS"].map(status_order)
    df_out = df_out.sort_values(
        ["_status_order", "CLIENT_ID", "FILE_NAME"],
        na_position="last",
    ).drop(columns="_status_order")

    df_out.to_csv(out_path, sep=CSV_SEPARATOR, encoding=CSV_ENCODING_OUT, index=False)
    return out_path


# =============================================================================
# CLI / DISPLAY
# =============================================================================

def print_summary_console(df: pd.DataFrame, summary: Dict[str, int],
                           output_path: Path, elapsed_sec: float) -> None:
    """Красивий вивід у консоль через rich."""
    console = Console()

    # Banner
    console.print(Panel.fit(
        "[bold cyan]Phase A0: Discovery[/bold cyan] — sniff raw files (nrows=3)",
        border_style="cyan",
    ))

    # Summary table
    table = Table(title="Summary", show_header=True, header_style="bold")
    table.add_column("Metric",   style="cyan")
    table.add_column("Value",    justify="right", style="green")
    table.add_row("Total files",        f"{summary['total']}")
    table.add_row("[green]READY[/green]",         f"{summary['ready']}")
    table.add_row("[blue]OVERSIZED[/blue]",        f"{summary['oversized']}  (>{MAX_FILE_SIZE_MB} MB, excluded)")
    table.add_row("[yellow]EMPTY[/yellow]",        f"{summary['empty']}")
    table.add_row("[red]MALFORMED[/red]",          f"{summary['malformed']}")
    table.add_row("Elapsed",            f"{elapsed_sec:.2f} s")
    console.print(table)

    # Якщо є MALFORMED — деталі
    bad = df[df["STATUS"] != STATUS_READY]
    if len(bad) > 0:
        bad_table = Table(title="Non-READY files", show_header=True, header_style="bold red")
        bad_table.add_column("File",   style="white")
        bad_table.add_column("Status", style="yellow")
        bad_table.add_column("Reason")
        for _, row in bad.head(20).iterrows():
            bad_table.add_row(row["FILE_NAME"], row["STATUS"], row["REASON"])
        if len(bad) > 20:
            bad_table.caption = f"...показано перших 20 з {len(bad)}"
        console.print(bad_table)

    # Output info
    console.print(f"\n[bold]Output:[/bold] {output_path}")
    console.print(f"[dim]CSV separator: '{CSV_SEPARATOR}', encoding: {CSV_ENCODING_OUT}[/dim]")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase A0: Discovery — sniff raw market files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  python -m pipeline.discover_markets\n"
               "  python -m pipeline.discover_markets --limit 5",
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=None,
        metavar="N",
        help="Обробити лише перші N файлів (smoke-test).",
    )
    args = parser.parse_args()

    try:
        # Pre-flight: переконатись, що raw та внутрішні папки існують
        validate_raw_data_path()
        ensure_directories()

        # Discovery (markets + NFC1)
        t0 = time.time()
        df, summary, discovered_nfc1 = discover_markets(limit=args.limit)
        elapsed = time.time() - t0

        # Save markets_list.csv
        out_path = save_markets_list(df)

        # Update master nfc1_config.json (accumulating registry)
        scanned_files = summary["ready"] + summary["oversized"]
        cfg, newly_added = update_nfc1_config(discovered_nfc1, scanned_files)

        # Display
        print_summary_console(df, summary, out_path, elapsed)
        rprint(f"\n[bold cyan]NFC1 master registry:[/bold cyan] {NFC1_CONFIG_PATH}")
        rprint(f"  Categories discovered in this run:  {len(discovered_nfc1)}")
        rprint(f"  Categories total in master:         {len(cfg.get('all_categories', []))}")
        if newly_added:
            rprint(f"  [yellow]Newly added (first time seen):[/yellow] {len(newly_added)}")
            for cat in newly_added:
                rprint(f"    + {cat}")
        else:
            rprint(f"  [dim]No new categories (all already in master).[/dim]")

        # Exit code: 0 якщо хоч один READY, 1 інакше
        if summary["ready"] == 0:
            rprint("[bold red]ERROR:[/bold red] No READY files. Pipeline cannot proceed.")
            return 1
        return 0

    except FileNotFoundError as e:
        rprint(f"[bold red]ERROR:[/bold red] {e}")
        return 1
    except Exception as e:
        rprint(f"[bold red]UNEXPECTED ERROR:[/bold red] {type(e).__name__}: {e}")
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
