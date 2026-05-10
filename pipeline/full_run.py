# =============================================================================
# FULL PIPELINE ORCHESTRATOR - drug_substitution_engine
# =============================================================================
# Файл: pipeline/full_run.py
# Дата: 2026-04-27
# Опис: Single entry-point: A0 (discover) → A1-A4 (parallel) → B → C.
# =============================================================================

"""
Full pipeline orchestrator — одна команда від raw CSV до 4 фінальних файлів.

Виконує (з resume + corruption recovery):
    Phase A0:  discover_markets.py — markets_list.csv
    Phase A:   parallel runner на всіх READY ринках (resume aware)
    Phase B:   cross_market.py — drug_statistics.parquet
    Phase C:   final_export.py — 2 CSV + 2 XLSX + validation_report.txt

Має:
    - Pre-flight checks (DATA_SETS exists, disk space, тощо)
    - Persistent log file у `logs/run_TIMESTAMP.log`
    - Rich Live dashboard (через runner)
    - Final summary

Використання:
    # Подвійний клік run.bat → запускає це
    python -m pipeline.full_run

    # З custom параметрами:
    python -m pipeline.full_run --workers 4 --min-market-count 20

    # Force перерахунок ВСЬОГО (ігнорувати існуючі parquet):
    python -m pipeline.full_run --force

    # Перші N ринків (для тесту):
    python -m pipeline.full_run --limit 5
"""

import argparse
import logging
import shutil
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    RAW_DATA_PATH,
    RAW_FILE_PATTERN,
    PREPROC_FILES,
    LOGS_PATH,
    ensure_directories,
    load_markets_list,
)
from config.machine_params import (
    MAX_WORKERS,
    MIN_FREE_DISK_GB,
    WORK_DRIVE,
)


# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging() -> Path:
    """
    Налаштувати persistent file logging.

    Повертає шлях до log файлу. Console output не йде через logging
    (rich Live займає stdout).
    """
    LOGS_PATH.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_PATH / f"run_{timestamp}.log"

    # Кореневий logger пише ТІЛЬКИ у файл (console залишаємо чистим для rich)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    # Очистити попередні handlers (якщо повторний запуск у тому ж процесі)
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(file_handler)

    return log_path


log = logging.getLogger(__name__)


# =============================================================================
# PRE-FLIGHT CHECKS
# =============================================================================

def preflight_checks() -> Tuple[bool, List[Tuple[str, str]]]:
    """
    Перевірити критичні умови перед запуском.

    Returns:
        (all_ok, [(status, message), ...]) — статуси: OK / WARN / FAIL
    """
    checks: List[Tuple[str, str]] = []
    all_ok = True

    # 1. RAW_DATA_PATH існує і має CSV
    if not RAW_DATA_PATH.exists():
        checks.append(("FAIL", f"DATA_SETS path not found: {RAW_DATA_PATH}"))
        all_ok = False
    else:
        n_csv = len(list(RAW_DATA_PATH.glob(RAW_FILE_PATTERN)))
        if n_csv == 0:
            checks.append(("FAIL", f"DATA_SETS path has no CSV: {RAW_DATA_PATH}"))
            all_ok = False
        else:
            checks.append(("OK", f"DATA_SETS path: {n_csv} CSV files"))

    # 2. Disk space
    try:
        free_gb = shutil.disk_usage(WORK_DRIVE).free / (1024 ** 3)
        if free_gb < MIN_FREE_DISK_GB:
            checks.append(("WARN", f"Disk free: {free_gb:.1f} GB (recommended >= {MIN_FREE_DISK_GB} GB)"))
        else:
            checks.append(("OK", f"Disk free: {free_gb:.1f} GB on {WORK_DRIVE}"))
    except Exception as e:
        checks.append(("WARN", f"Disk check failed: {e}"))

    # 3. markets_list.csv (буде створено discovery якщо немає)
    if PREPROC_FILES["markets_list"].exists():
        checks.append(("OK", f"markets_list.csv exists"))
    else:
        checks.append(("INFO", f"markets_list.csv missing — will be created via discovery"))

    return all_ok, checks


def print_preflight(checks: List[Tuple[str, str]]) -> None:
    """Вивід результатів pre-flight в консоль."""
    console = Console()
    table = Table(title="Pre-flight checks", show_header=True, header_style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Check")
    for status, msg in checks:
        color = {"OK": "green", "WARN": "yellow", "FAIL": "red", "INFO": "cyan"}.get(status, "white")
        table.add_row(f"[{color}]{status}[/{color}]", msg)
    console.print(table)


# =============================================================================
# PIPELINE STAGES
# =============================================================================

def stage_discover() -> bool:
    """Phase A0: discover markets → markets_list.csv."""
    log.info("=== STAGE: Discover markets ===")
    rprint("\n[bold cyan]>>> STAGE: Discover markets[/bold cyan]\n")

    from pipeline.discover_markets import (
        discover_markets,
        save_markets_list,
        print_summary_console,
        STATUS_READY,
    )

    t0 = time.time()
    df, summary = discover_markets()
    out_path = save_markets_list(df)
    elapsed = time.time() - t0

    log.info(f"Discovery: {summary['total']} files, "
             f"READY={summary['ready']}, OVERSIZED={summary['oversized']}, "
             f"EMPTY={summary['empty']}, MALFORMED={summary['malformed']}")

    print_summary_console(df, summary, out_path, elapsed)

    if summary["ready"] == 0:
        log.error("No READY markets after discovery.")
        return False
    return True


def stage_phase_a(market_ids: List[int],
                   max_workers: int,
                   force: bool) -> Dict[int, Dict[str, Any]]:
    """Phase A: parallel run на всіх ринках."""
    log.info(f"=== STAGE: Phase A (parallel runner, {len(market_ids)} markets) ===")
    rprint(f"\n[bold cyan]>>> STAGE: Phase A — Parallel Processing ({len(market_ids)} markets)[/bold cyan]\n")

    from pipeline.runner import run_parallel
    return run_parallel(market_ids, max_workers=max_workers, force=force)


def stage_phase_b() -> Dict[str, Any]:
    """Phase B: cross-market aggregation → drug_statistics.parquet."""
    log.info("=== STAGE: Phase B (cross-market) ===")
    rprint("\n[bold cyan]>>> STAGE: Phase B — Cross-Market Aggregation[/bold cyan]\n")

    from pipeline.cross_market import run_cross_market, print_cross_market_result
    result = run_cross_market()
    print_cross_market_result(result)

    if result.get("status") == "success":
        log.info(f"Phase B: {result['drugs_total']} drugs aggregated "
                 f"(unimodal={result['drugs_unimodal']}, multimodal={result['drugs_multimodal']})")
    else:
        log.error(f"Phase B failed: {result.get('error', '?')}")

    return result


def stage_phase_c(min_market_count: int) -> Dict[str, Any]:
    """Phase C: final export → 4 файли."""
    log.info(f"=== STAGE: Phase C (final export, min_market_count={min_market_count}) ===")
    rprint("\n[bold cyan]>>> STAGE: Phase C — Final Export[/bold cyan]\n")

    from pipeline.final_export import run_final_export, print_final_export_result
    result = run_final_export(min_market_count=min_market_count)
    print_final_export_result(result)

    if result.get("status") == "success":
        log.info(f"Phase C: {result['drugs_accepted']} drugs accepted, "
                 f"{result['subs_pairs_total']} substitute pairs")
        for key, info in result.get("outputs", {}).items():
            log.info(f"  {Path(info['path']).name}: {info.get('rows', '-')} rows, "
                     f"{info['size_kb']} KB")
    else:
        log.error(f"Phase C failed: {result.get('error', '?')}")

    return result


# =============================================================================
# FINAL SUMMARY
# =============================================================================

def print_final_summary(
    overall_elapsed_sec: float,
    started_at: datetime,
    log_path: Path,
    phase_a_results: Dict[int, Dict[str, Any]],
    phase_b_result: Optional[Dict[str, Any]],
    phase_c_result: Optional[Dict[str, Any]],
) -> None:
    """Підсумкова таблиця в кінці повного pipeline."""
    console = Console()

    finished_at = datetime.now()

    table = Table(title="Full Pipeline Summary", show_header=True, header_style="bold")
    table.add_column("Phase", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Details")

    # Phase A
    n_total = len(phase_a_results) if phase_a_results else 0
    n_success = sum(1 for r in (phase_a_results or {}).values()
                    if r["overall_status"] == "success")
    n_no_data = sum(1 for r in (phase_a_results or {}).values()
                    if r["overall_status"] == "no_data")
    n_errors = sum(1 for r in (phase_a_results or {}).values()
                   if r["overall_status"] in ("error", "crashed"))
    a_status = "[green]OK[/green]" if n_errors == 0 else f"[red]{n_errors} FAIL[/red]"
    table.add_row("Phase A", a_status,
                  f"{n_success} success, {n_no_data} no-data, {n_errors} errors (of {n_total})")

    # Phase B
    if phase_b_result:
        b_status = phase_b_result.get("status", "?")
        b_color = {"success": "green", "no_data": "yellow", "error": "red"}.get(b_status, "white")
        details = f"{phase_b_result.get('drugs_total', '-')} drugs"
        table.add_row("Phase B", f"[{b_color}]{b_status.upper()}[/{b_color}]", details)

    # Phase C
    if phase_c_result:
        c_status = phase_c_result.get("status", "?")
        c_pass = phase_c_result.get("all_pass", False)
        c_color = "green" if c_status == "success" and c_pass else "red"
        text = f"{phase_c_result.get('drugs_accepted', '-')} drugs, " \
               f"{phase_c_result.get('subs_pairs_total', '-')} pairs, " \
               f"validation: {'PASSED' if c_pass else 'FAILED'}"
        table.add_row("Phase C", f"[{c_color}]{c_status.upper()}[/{c_color}]", text)

    console.print(table)

    # Final files
    if phase_c_result and phase_c_result.get("status") == "success":
        files_table = Table(title="Output files (results/final/)",
                            show_header=True, header_style="bold")
        files_table.add_column("File", style="cyan")
        files_table.add_column("Rows", justify="right")
        files_table.add_column("Size KB", justify="right")
        for key, info in phase_c_result.get("outputs", {}).items():
            files_table.add_row(
                Path(info["path"]).name,
                f"{info.get('rows', '-')}" if isinstance(info.get('rows'), int) else "-",
                f"{info['size_kb']:.2f}",
            )
        console.print(files_table)

    # Times
    times_table = Table(show_header=False, expand=False, box=None)
    times_table.add_column(style="cyan")
    times_table.add_column(justify="right")
    times_table.add_row("Started",        started_at.strftime("%Y-%m-%d %H:%M:%S"))
    times_table.add_row("Finished",       finished_at.strftime("%Y-%m-%d %H:%M:%S"))
    times_table.add_row("Total wall time", _fmt_seconds(overall_elapsed_sec))
    times_table.add_row("Log file",       str(log_path))
    console.print(times_table)


def _fmt_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s:02d}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}h {m:02d}m {s:02d}s"


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

def run_full_pipeline(
    max_workers: Optional[int] = None,
    force: bool = False,
    min_market_count: int = 20,
    market_limit: Optional[int] = None,
) -> int:
    """
    Виконати повний pipeline: discover → A → B → C.

    Args:
        max_workers:      Кількість parallel workers (default з config).
        force:            Якщо True — ігнорувати існуючі parquet.
        min_market_count: Поріг для Phase C drug filter (default 20).
        market_limit:     Якщо задано — обробити лише перших N READY ринків (для тесту).

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    started_at = datetime.now()
    overall_t0 = time.time()

    # Logging setup
    log_path = setup_logging()
    log.info("=" * 70)
    log.info(f"FULL PIPELINE STARTED — {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"  workers={max_workers or MAX_WORKERS}  force={force}  "
             f"min_market_count={min_market_count}  limit={market_limit}")
    log.info("=" * 70)

    console = Console()
    console.print(Panel.fit(
        f"[bold cyan]Drug Substitution Engine — Full Pipeline[/bold cyan]\n"
        f"Started:  {started_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Workers:  {max_workers or MAX_WORKERS}\n"
        f"Force:    {force}\n"
        f"Min markets:  {min_market_count}\n"
        f"Log file: {log_path}",
        border_style="cyan",
    ))

    try:
        # === Pre-flight ===
        all_ok, checks = preflight_checks()
        for status, msg in checks:
            log.info(f"  [{status}] {msg}")
        print_preflight(checks)
        if not all_ok:
            log.error("Pre-flight FAILED — abort")
            rprint("\n[red]Pre-flight checks FAILED. Pipeline aborted.[/red]")
            return 1

        # === Phase A0: Discover (only if markets_list.csv missing) ===
        ensure_directories()
        if not PREPROC_FILES["markets_list"].exists():
            ok = stage_discover()
            if not ok:
                log.error("Discovery returned 0 READY markets — abort")
                return 1
        else:
            log.info("Discovery skipped: markets_list.csv exists")
            rprint("[dim]Discovery skipped: markets_list.csv already exists.[/dim]")

        # Load READY markets
        df_ready = load_markets_list()
        df_ready = df_ready[df_ready["STATUS"] == "READY"].sort_values("CLIENT_ID")
        market_ids = df_ready["CLIENT_ID"].astype(int).tolist()
        if market_limit is not None:
            market_ids = market_ids[:market_limit]
            rprint(f"[yellow]Limit applied:[/yellow] processing first {len(market_ids)} markets")
            log.info(f"Limit applied: {len(market_ids)} markets")

        if not market_ids:
            log.error("No READY markets to process")
            return 1

        # === Phase A: Parallel runner ===
        a_results = stage_phase_a(market_ids,
                                  max_workers=max_workers or MAX_WORKERS,
                                  force=force)

        n_a_failed = sum(1 for r in a_results.values()
                         if r["overall_status"] in ("error", "crashed"))
        if n_a_failed > 0:
            log.warning(f"Phase A: {n_a_failed} markets failed — Phase B/C will use partial data")
            rprint(f"[yellow]WARN:[/yellow] {n_a_failed} markets failed in Phase A. "
                   f"Continuing with available data...")

        # === Phase B: Cross-market ===
        b_result = stage_phase_b()
        if b_result.get("status") not in ("success", "no_data"):
            log.error(f"Phase B failed — abort: {b_result.get('error')}")
            print_final_summary(
                time.time() - overall_t0, started_at, log_path,
                a_results, b_result, None,
            )
            return 1

        # === Phase C: Final export ===
        c_result = stage_phase_c(min_market_count=min_market_count)

        # === Final summary ===
        overall_elapsed = time.time() - overall_t0
        print_final_summary(overall_elapsed, started_at, log_path,
                            a_results, b_result, c_result)

        log.info("=" * 70)
        log.info(f"FULL PIPELINE FINISHED — total {_fmt_seconds(overall_elapsed)}")
        log.info("=" * 70)

        # Exit code: 0 if Phase C succeeded with all validations passed
        if c_result.get("status") == "success" and c_result.get("all_pass"):
            return 0
        return 1

    except KeyboardInterrupt:
        log.warning("Pipeline interrupted by user (Ctrl+C)")
        rprint("\n[yellow]Pipeline interrupted by user.[/yellow]")
        rprint(f"[dim]Log: {log_path}[/dim]")
        return 130
    except Exception as e:
        log.exception(f"UNEXPECTED ERROR: {type(e).__name__}: {e}")
        rprint(f"\n[red]UNEXPECTED ERROR:[/red] {type(e).__name__}: {e}")
        rprint(f"[dim]See log for details: {log_path}[/dim]")
        return 2


# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Full pipeline: discover → A (parallel) → B → C → 4 final files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  python -m pipeline.full_run                       # default: всі ринки\n"
               "  python -m pipeline.full_run --workers 4\n"
               "  python -m pipeline.full_run --limit 5             # тестовий прогон\n"
               "  python -m pipeline.full_run --force               # ігнорувати existing parquet\n"
               "  python -m pipeline.full_run --min-market-count 3  # м'якший Phase C фільтр\n",
    )
    parser.add_argument("--workers", "-w", type=int, default=None,
                        help=f"Кількість parallel workers (default: {MAX_WORKERS})")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Перерахувати все (ігнорувати existing parquet)")
    parser.add_argument("--min-market-count", "-m", type=int, default=20,
                        help="Phase C drug filter (default 20, Sequential Analyzer Study 02)")
    parser.add_argument("--limit", "-n", type=int, default=None,
                        help="Обробити лише перших N READY ринків (для тестування)")

    args = parser.parse_args()

    return run_full_pipeline(
        max_workers=args.workers,
        force=args.force,
        min_market_count=args.min_market_count,
        market_limit=args.limit,
    )


if __name__ == "__main__":
    sys.exit(main())
