# =============================================================================
# MACHINE PARAMETERS - drug_substitution_engine
# =============================================================================
# Файл: config/machine_params.py
# Дата: 2026-04-27
# Опис: Параметри обчислювальної машини під поточний Windows ПК
# =============================================================================

"""
Конфігуратор параметрів обчислювальної машини.

Поточна машина (заповнено на 2026-04-27):
    Windows 10 Pro, Intel Core i7-9700F (8 cores / 8 threads, без HT), 32 GB RAM
    Диск D: HDD (Seagate ST2000DM008, 2TB)

Документація рішень: див. ROADMAP.md §3 (Hardware + Storage Strategy)

Поради при перенесенні на іншу машину:
    1. Оновити CPU_PHYSICAL_CORES, CPU_LOGICAL_CORES, TOTAL_RAM_GB.
    2. Перерахувати MAX_WORKERS за формулою:
         MAX_WORKERS = min(CPU_PHYSICAL_CORES - 2, AVAILABLE_RAM_GB / RAM_PER_WORKER_GB)
       (мінус 2: -1 для ОС, -1 для main/UI процесу)
    3. THREADS_PER_WORKER = 2 якщо CPU має Hyper-Threading (logical = 2 × physical).
       Без HT — лишити 1.
"""


# =============================================================================
# CPU
# =============================================================================

CPU_PHYSICAL_CORES = 8     # i7-9700F: 8 фізичних ядер
CPU_LOGICAL_CORES  = 8     # i7-9700F (F-варіант) — без Hyper-Threading
CPU_BASE_GHZ       = 3.0


# =============================================================================
# MEMORY
# =============================================================================

TOTAL_RAM_GB     = 32
AVAILABLE_RAM_GB = 26      # лишаємо 6 GB для ОС, IDE, браузера

# Очікуваний пік пам'яті per worker.
# На цьому проекті значно вище за канонічний (~0.5 GB), бо файли в 5–40× більші:
#   - Найбільший raw CSV: ~2.2 GB (читається в RAM цілком)
#   - DataFrame після завантаження: ~1.5–2× від CSV (через типи pandas)
#   - Робочі копії під час обробки: +0.5 GB
RAM_PER_WORKER_GB = 2.0


# =============================================================================
# PARALLEL EXECUTION
# =============================================================================

# Формула:
#   MAX_WORKERS = min(CPU_PHYSICAL_CORES - 2, AVAILABLE_RAM_GB / RAM_PER_WORKER_GB)
# Для нашої машини:
#   min(8 - 2, 26 / 2.0) = min(6, 13) = 6
MAX_WORKERS = 6
MIN_WORKERS = 1

# Без HT — INN-thread параллелізм лише додає context-switch overhead.
# Лишаємо 1 (фактично відключено, як у канонічному при HT_disabled).
THREADS_PER_WORKER = 1

# Таймаут на stall detection (секунди).
# 60 хв per market — запас на найбільші файли (~2.2 GB) на HDD.
# Після першого тестового запуску можна зменшити, якщо реальний час менше.
MARKET_TIMEOUT_SEC = 3600

SHOW_PROGRESS = True


# =============================================================================
# DISK
# =============================================================================

# Тип диска D: де розташовані raw + intermediate + results.
# Впливає на стратегію I/O: для HDD уникаємо random reads, читаємо файл цілком.
DISK_TYPE = "HDD"  # 'HDD' | 'SSD' | 'NVMe'

# Шлях до робочого диска (для pre-flight check на вільне місце)
WORK_DRIVE = "D:\\"

# Мінімум вільного місця на робочому диску перед запуском (GB).
# Оцінка: intermediate per market ~6 MB × 207 = ~1.2 GB + final results ~50 MB
MIN_FREE_DISK_GB = 5


# =============================================================================
# INPUT FILE SIZE FILTER (memory protection)
# =============================================================================

# Максимальний розмір raw CSV, який ми обробляємо.
# Файли більше цього порогу позначаються STATUS='OVERSIZED' у markets_list.csv
# та виключаються з pipeline.
#
# Обґрунтування для поточного ПК (32 GB RAM, 6 workers):
#   - CSV 2 GB → DataFrame у RAM ~4-7 GB (pandas overhead)
#   - 6 workers × ~5 GB пік = ~30 GB → межа 32 GB → ризик OOM
#   - Поріг 2048 MB виключає 2 найбільших файли (4270496.csv, 370875.csv)
#   - Файли 1.5-2 GB ще обробляємо (їх 11), але є backstop через timeout
#
# Якщо при тестовому запуску побачимо OOM — знизити поріг до 1500 (виключить ще 11 файлів)
# Якщо буде запас — підняти або поставити 99999 (відключити фільтр)
MAX_FILE_SIZE_MB = 2048


# =============================================================================
# DERIVED PARAMETERS
# =============================================================================

def get_optimal_workers() -> int:
    """
    Обчислити оптимальну кількість workers для поточної машини.

    Враховує:
        - CPU фізичні ядра (мінус 2: ОС + main/UI)
        - Доступну RAM (ділимо на пік per worker)
        - Не менше MIN_WORKERS, не більше MAX_WORKERS.

    Returns:
        Кількість workers для ProcessPoolExecutor.
    """
    cpu_based = max(1, CPU_PHYSICAL_CORES - 2)
    ram_based = max(1, int(AVAILABLE_RAM_GB / RAM_PER_WORKER_GB))
    optimal   = min(cpu_based, ram_based, MAX_WORKERS)
    return max(optimal, MIN_WORKERS)


OPTIMAL_WORKERS = get_optimal_workers()


def get_optimal_threads() -> int:
    """
    Обчислити кількість потоків per worker.

    Без HT (CPU_LOGICAL_CORES == CPU_PHYSICAL_CORES) — повертаємо 1.
    """
    if CPU_LOGICAL_CORES <= CPU_PHYSICAL_CORES:
        return 1
    cpu_based = max(1, CPU_LOGICAL_CORES // max(1, OPTIMAL_WORKERS))
    return min(cpu_based, THREADS_PER_WORKER, 4)


OPTIMAL_THREADS = get_optimal_threads()


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("MACHINE PARAMETERS — drug_substitution_engine")
    print("=" * 60)
    print(f"\nCPU:")
    print(f"  Physical cores:   {CPU_PHYSICAL_CORES}")
    print(f"  Logical cores:    {CPU_LOGICAL_CORES}")
    print(f"  Base clock:       {CPU_BASE_GHZ} GHz")
    print(f"\nMEMORY:")
    print(f"  Total RAM:        {TOTAL_RAM_GB} GB")
    print(f"  Available:        {AVAILABLE_RAM_GB} GB")
    print(f"  Per worker peak:  {RAM_PER_WORKER_GB} GB")
    print(f"\nPARALLEL:")
    print(f"  MAX_WORKERS:      {MAX_WORKERS}")
    print(f"  THREADS/WORKER:   {THREADS_PER_WORKER}")
    print(f"  OPTIMAL_WORKERS:  {OPTIMAL_WORKERS}")
    print(f"  OPTIMAL_THREADS:  {OPTIMAL_THREADS}")
    print(f"  Timeout:          {MARKET_TIMEOUT_SEC} s")
    print(f"\nDISK:")
    print(f"  Type:             {DISK_TYPE}")
    print(f"  Work drive:       {WORK_DRIVE}")
    print(f"  Min free:         {MIN_FREE_DISK_GB} GB")
    print(f"\nFILE FILTER:")
    print(f"  MAX_FILE_SIZE_MB: {MAX_FILE_SIZE_MB} MB ({MAX_FILE_SIZE_MB/1024:.2f} GB)")
