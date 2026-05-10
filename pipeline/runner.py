# =============================================================================
# PARALLEL RUNNER - drug_substitution_engine / Phase A
# =============================================================================
# Файл: pipeline/runner.py
# Дата: 2026-04-27 (extended with Rich Live dashboard + corruption recovery)
# Опис: ProcessPoolExecutor + Rich Live dashboard для Phase A1+A2+A3+A4.
# =============================================================================

"""
Parallel runner для повного pipeline Phase A на множині ринків.

Архітектура:
    - ProcessPoolExecutor з MAX_WORKERS workers (з config/machine_params.py)
    - Rich Live dashboard з progress bar, ETA, active workers, stats
    - Corruption-aware resume (phase_output_valid у per_market.process_market_full)
    - Fail-safe per market

Використання:
    python -m pipeline.runner --limit 5
    python -m pipeline.runner --all
    python -m pipeline.runner --market-ids 763807 1439971
    python -m pipeline.runner --all --force
    python -m pipeline.runner --all --workers 4
"""

import argparse
import logging
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from rich import print as rprint
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    MofNCompleteColumn,
    TimeElapsedColumn,
)
from rich.table import Table

# Project root
SCRIPT_PATH  = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.paths import (
    load_markets_list,
    ensure_directories,
)
from config.machine_params import MAX_WORKERS, TOTAL_RAM_GB, CPU_PHYSICAL_CORES, DISK_TYPE
from pipeline.per_market import process_market_full

log = logging.getLogger(__name__)


# =============================================================================
# WORKER ENTRY-POINT
# =============================================================================

def _worker_task(args: Tuple[int, str, bool]) -> Dict[str, Any]:
    """
    Wrapper для `process_market_full()` адаптований для ProcessPoolExecutor.

    Args:
        args: (client_id, file_path_str, force)

    Returns:
        Dict із результатами (повний summary з process_market_full).
    """
    client_id, file_path_str, force = args
    file_path = Path(file_path_str)
    return process_market_full(client_id, file_path, force=force)


# =============================================================================
# RICH LIVE DASHBOARD
# =============================================================================

def _format_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s:02d}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m:02d}m"


def _make_banner(
    machine_workers: int,
    started_at: datetime,
    completed: int = 0,
    total: int = 0,
    overall_t0: Optional[float] = None,
) -> Panel:
    """Banner панель — верх дашборду з кастомним ETA на основі реальної швидкості."""
    if overall_t0 is not None and completed >= 5 and total > completed:
        elapsed = time.time() - overall_t0
        avg_wall_per_market = elapsed / completed
        eta_seconds = avg_wall_per_market * (total - completed)
        eta_str = _format_time(eta_seconds)
        finish_at = (datetime.now().timestamp() + eta_seconds)
        finish_dt = datetime.fromtimestamp(finish_at).strftime("%H:%M:%S")
        eta_line = f"ETA:      ~{eta_str}  (≈ finish at {finish_dt})"
    elif total > 0 and completed < 5:
        eta_line = f"ETA:      calculating... ({completed}/{total} done — need 5+ for stable estimate)"
    else:
        eta_line = ""

    text = (
        f"[bold cyan]Drug Substitution Engine — Phase A Runner[/bold cyan]\n"
        f"Started:  {started_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Machine:  CPU {CPU_PHYSICAL_CORES} cores  |  RAM {TOTAL_RAM_GB} GB  "
        f"|  Disk: {DISK_TYPE}  |  Workers: {machine_workers}"
    )
    if eta_line:
        text += f"\n{eta_line}"
    return Panel(text, border_style="cyan", expand=False)


def _make_active_table(active_markets: Dict[int, float], max_rows: int = 10) -> Panel:
    """Панель з активними workers — оновлюється кожні N сек."""
    if not active_markets:
        return Panel("[dim]All workers idle[/dim]", title="Active workers", border_style="dim")

    table = Table(show_header=True, header_style="bold", expand=False)
    table.add_column("CLIENT_ID", style="cyan")
    table.add_column("Running for", justify="right")

    now = time.time()
    items = sorted(active_markets.items(), key=lambda x: x[1])  # earliest first
    for cid, started in items[:max_rows]:
        elapsed = now - started
        table.add_row(str(cid), _format_time(elapsed))

    if len(items) > max_rows:
        table.caption = f"...плюс ще {len(items) - max_rows}"

    return Panel(table, title=f"Active workers ({len(active_markets)})", border_style="green")


def _make_stats_table(stats: Dict[str, Any]) -> Panel:
    """Панель статистики — completed/failed/skipped тощо."""
    table = Table(show_header=False, expand=False, box=None)
    table.add_column(style="cyan")
    table.add_column(justify="right")

    table.add_row("[green]Success[/green]",        f"{stats['success']}")
    table.add_row("[yellow]No data[/yellow]",      f"{stats['no_data']}")
    table.add_row("[red]Errors[/red]",             f"{stats['errors']}")
    table.add_row("[dim]Resume skips (phases)[/dim]", f"{stats['skipped_phases']}")
    if stats.get("avg_per_market_sec"):
        table.add_row("Avg per market",            _format_time(stats["avg_per_market_sec"]))

    return Panel(table, title="Stats", border_style="dim")


# =============================================================================
# PARALLEL ORCHESTRATOR
# =============================================================================

def run_parallel(
    market_ids: List[int],
    max_workers: Optional[int] = None,
    force: bool = False,
) -> Dict[int, Dict[str, Any]]:
    """
    Запустити Phase A1+A2+A3+A4 паралельно на множині ринків з Rich Live dashboard.

    Args:
        market_ids:  Список CLIENT_ID для обробки.
        max_workers: Кількість parallel workers (default: MAX_WORKERS з config).
        force:       Якщо True — ігнорувати існуючі parquet (перерахувати все).

    Returns:
        Dict[client_id, summary] — результати кожного ринку.
    """
    if max_workers is None:
        max_workers = MAX_WORKERS

    # Resolve file paths з markets_list.csv
    df_markets = load_markets_list()
    market_to_path = dict(zip(df_markets["CLIENT_ID"], df_markets["FILE_PATH"]))

    tasks: List[Tuple[int, str, bool]] = []
    skipped_unknown: List[int] = []
    for cid in market_ids:
        if cid in market_to_path:
            tasks.append((cid, str(market_to_path[cid]), force))
        else:
            skipped_unknown.append(cid)

    if skipped_unknown:
        log.warning(f"{len(skipped_unknown)} markets not in markets_list.csv: "
                    f"{skipped_unknown[:5]}{'...' if len(skipped_unknown) > 5 else ''}")

    if not tasks:
        log.error("No valid markets to process.")
        return {}

    started_at = datetime.now()
    log.info(f"Phase A runner started: {len(tasks)} markets, {max_workers} workers, "
             f"force={force}")

    results: Dict[int, Dict[str, Any]] = {}
    overall_t0 = time.time()

    # Stats accumulators
    stats: Dict[str, Any] = {
        "success": 0,
        "no_data": 0,
        "errors": 0,
        "skipped_phases": 0,
        "avg_per_market_sec": None,
    }
    success_times: List[float] = []
    active_markets: Dict[int, float] = {}  # client_id -> started_at

    # === Rich Live Dashboard ===
    progress = Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TextColumn("[progress.percentage]{task.percentage:>5.1f}%"),
        TextColumn("•"),
        TimeElapsedColumn(),
        expand=False,
    )
    main_task = progress.add_task("Markets", total=len(tasks))

    def render() -> Group:
        completed_n = stats["success"] + stats["no_data"] + stats["errors"]
        return Group(
            _make_banner(max_workers, started_at, completed_n, len(tasks), overall_t0),
            progress,
            _make_active_table(active_markets),
            _make_stats_table(stats),
        )

    with Live(render(), refresh_per_second=2, transient=False) as live:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_cid: Dict[Any, int] = {}
            for t in tasks:
                f = executor.submit(_worker_task, t)
                future_to_cid[f] = t[0]
                # NB: НЕ додаємо в active_markets тут — ProcessPoolExecutor лише
                # ставить задачі в чергу, реально виконується max_workers одночасно.
                # Реальний старт детектуємо через future.running() у polling loop.

            pending = set(future_to_cid.keys())

            try:
                while pending:
                    # Polling: чекаємо до 1 сек на завершення будь-якого future
                    done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)

                    # Детектуємо реально-running futures (а не submit-ed-and-queued)
                    now_ts = time.time()
                    for f in pending:
                        cid = future_to_cid[f]
                        if f.running() and cid not in active_markets:
                            active_markets[cid] = now_ts

                    for future in done:
                        client_id = future_to_cid[future]
                        active_markets.pop(client_id, None)

                        try:
                            result = future.result()
                            results[client_id] = result
                            status = result.get("overall_status", "?")

                            # Update stats
                            if status == "success":
                                stats["success"] += 1
                                success_times.append(result.get("overall_elapsed_sec", 0))
                                stats["avg_per_market_sec"] = sum(success_times) / len(success_times)
                            elif status == "no_data":
                                stats["no_data"] += 1
                            else:
                                stats["errors"] += 1

                            # Count skipped phases (resume)
                            for ph_res in result.get("phases", {}).values():
                                if ph_res.get("status") == "skipped":
                                    stats["skipped_phases"] += 1

                            # Log per-market completion
                            elapsed = result.get("overall_elapsed_sec", 0)
                            log.info(f"  Market {client_id}: {status} ({elapsed:.0f}s)")
                            if status not in ("success", "no_data"):
                                err = result.get("error", "?")
                                failed_at = result.get("failed_at", "?")
                                log.error(f"    Failed at {failed_at}: {err}")
                                tb = result.get("traceback")
                                if tb:
                                    log.error(f"    Traceback: {tb}")

                        except Exception as e:
                            stats["errors"] += 1
                            results[client_id] = {
                                "client_id":           client_id,
                                "overall_status":      "crashed",
                                "overall_elapsed_sec": 0.0,
                                "phases":              {},
                                "failed_at":           "worker",
                                "error":               f"{type(e).__name__}: {e}",
                            }
                            log.exception(f"  Market {client_id}: CRASHED — {e}")

                        progress.update(main_task, advance=1)

                    # Refresh live display
                    live.update(render())

            except KeyboardInterrupt:
                log.warning("KeyboardInterrupt: cancelling pending futures...")
                for f in pending:
                    f.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                raise

        # Final render — make sure last state shows
        live.update(render())

    overall_elapsed = time.time() - overall_t0
    log.info(f"Phase A runner finished: total {_format_time(overall_elapsed)}")

    print_runner_summary(results, overall_elapsed, max_workers, force)
    return results


# =============================================================================
# FINAL SUMMARY
# =============================================================================

def print_runner_summary(
    results: Dict[int, Dict[str, Any]],
    overall_elapsed: float,
    max_workers: int,
    force: bool,
) -> None:
    """Підсумкова таблиця після завершення runner-а."""
    console = Console()

    success    = sum(1 for r in results.values() if r["overall_status"] == "success")
    no_data    = sum(1 for r in results.values() if r["overall_status"] == "no_data")
    errors     = sum(1 for r in results.values() if r["overall_status"] in ("error", "crashed"))

    success_times = [r["overall_elapsed_sec"] for r in results.values()
                     if r["overall_status"] == "success"]
    avg_time = sum(success_times) / len(success_times) if success_times else 0
    sequential_time = sum(success_times)
    speedup = sequential_time / overall_elapsed if overall_elapsed > 0 else 0

    # Phase-level skipped counts
    phase_skipped = {ph: 0 for ph in ("a1", "a2", "a3", "a4")}
    phase_executed = {ph: 0 for ph in ("a1", "a2", "a3", "a4")}
    for r in results.values():
        if r["overall_status"] == "success":
            for ph_key, ph_res in r.get("phases", {}).items():
                if ph_res.get("status") == "skipped":
                    phase_skipped[ph_key] += 1
                else:
                    phase_executed[ph_key] += 1

    table = Table(title="Phase A Runner — Final Summary", show_header=True, header_style="bold")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total markets",   f"{len(results)}")
    table.add_row("[green]Success[/green]",      f"{success}")
    table.add_row("[yellow]No data[/yellow]",    f"{no_data}")
    table.add_row("[red]Errors[/red]",           f"{errors}")
    table.add_row("",                "")
    table.add_row("Workers",         f"{max_workers}")
    table.add_row("Force mode",      f"{force}")
    table.add_row("",                "")
    table.add_row("[bold]Wall time[/bold]",      _format_time(overall_elapsed))
    if success_times:
        table.add_row("Sequential equivalent",   _format_time(sequential_time))
        table.add_row("Speedup",                 f"{speedup:.2f}x")
        table.add_row("Avg per market",          _format_time(avg_time))
    table.add_row("",                "")
    for ph_key in ("a1", "a2", "a3", "a4"):
        e = phase_executed[ph_key]
        s = phase_skipped[ph_key]
        table.add_row(f"Phase {ph_key.upper()} executed / skipped", f"{e} / {s}")

    console.print(table)

    # Errors detail
    error_rows = [(cid, r) for cid, r in results.items()
                  if r["overall_status"] in ("error", "crashed")]
    if error_rows:
        err_table = Table(title="Failed markets", show_header=True, header_style="bold red")
        err_table.add_column("CLIENT_ID")
        err_table.add_column("Failed at")
        err_table.add_column("Error")
        for cid, r in error_rows[:20]:
            err_table.add_row(str(cid), str(r.get("failed_at", "?")), str(r.get("error", ""))[:80])
        if len(error_rows) > 20:
            err_table.caption = f"...показано перших 20 з {len(error_rows)}"
        console.print(err_table)


# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parallel runner — Phase A (A1+A2+A3+A4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  python -m pipeline.runner --limit 5\n"
               "  python -m pipeline.runner --all\n"
               "  python -m pipeline.runner --market-ids 763807 1439971\n"
               "  python -m pipeline.runner --all --force\n",
    )
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--limit", "-n", type=int, help="Перших N READY ринків")
    g.add_argument("--all",   "-a", action="store_true", help="Усі READY ринки")
    g.add_argument("--market-ids", nargs="+", type=int, metavar="ID",
                   help="Конкретні CLIENT_ID для обробки")

    parser.add_argument("--workers", "-w", type=int, default=None,
                        help=f"Кількість workers (default: {MAX_WORKERS})")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Ігнорувати існуючі parquet (перерахувати все)")

    args = parser.parse_args()

    # Default logging if not set up by caller (full_run.py)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    try:
        ensure_directories()
        df_ready_all = load_markets_list()
        df_ready_all = df_ready_all[df_ready_all["STATUS"] == "READY"].sort_values("CLIENT_ID")

        if args.all:
            market_ids = df_ready_all["CLIENT_ID"].astype(int).tolist()
        elif args.limit:
            market_ids = df_ready_all["CLIENT_ID"].astype(int).head(args.limit).tolist()
        else:
            market_ids = list(args.market_ids)

        if not market_ids:
            rprint("[red]ERROR:[/red] No markets selected.")
            return 1

        results = run_parallel(market_ids, max_workers=args.workers, force=args.force)
        n_failed = sum(1 for r in results.values()
                       if r["overall_status"] in ("error", "crashed"))
        return 0 if n_failed == 0 else 1

    except FileNotFoundError as e:
        rprint(f"[red]ERROR:[/red] {e}")
        return 1
    except KeyboardInterrupt:
        rprint("\n[yellow]Interrupted by user (Ctrl+C). Partial results may be saved.[/yellow]")
        return 130
    except Exception as e:
        rprint(f"[red]UNEXPECTED ERROR:[/red] {type(e).__name__}: {e}")
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
