import os
import glob
import time
import math
import hashlib
import psutil
from typing import Dict, Any, Tuple

# --- TIER 1: ACTIVE HARDWARE PERTURBATION ---

def perturb_silicon(rounds: int = 1500):
    """
    Executes a short, non-linear floating-point and memory workload.
    Forces CPU ALU switching, memory bus access, and cache line eviction
    to prevent DVFS down-clocking into a static frequency state.
    """
    acc = 1.000007
    # Non-linear iteration (Logistic chaotic map step)
    for i in range(1, rounds):
        acc = (3.99 * acc * (1.0 - (acc % 1.0))) % 1000.0
    
    # Volatile memory heap write/read churn
    churn = bytearray((int(acc) + i) % 256 for i in range(128))
    _ = hashlib.md5(churn).digest()
    del churn

# --- TIER 2: LOW-LEVEL TELEMETRY & SYSTEM REGISTERS ---

def read_sysfs_safe(path: str) -> str:
    """Safely reads sysfs nodes using unbuffered raw I/O."""
    try:
        with open(path, "rb", buffering=0) as f:
            raw = f.read()
            return raw.decode("utf-8", errors="ignore").strip() if raw else None
    except Exception:
        return None

def get_thermal_sensors() -> Dict[str, float]:
    """Reads active Jetson onboard thermal zones."""
    readings = {}
    for zone in sorted(glob.glob("/sys/devices/virtual/thermal/thermal_zone*")):
        temp_path = os.path.join(zone, "temp")
        type_path = os.path.join(zone, "type")
        sensor_name = read_sysfs_safe(type_path) or os.path.basename(zone)
        temp_str = read_sysfs_safe(temp_path)
        if temp_str:
            try:
                temp_c = int(temp_str) / 1000.0
                if temp_c > 0:
                    readings[sensor_name] = round(temp_c, 2)
            except ValueError:
                continue
    return readings

def get_interrupt_delta() -> str:
    """
    Reads hardware interrupt counts across CPU cores from /proc/interrupts.
    Captures non-deterministic I/O events (timer interrupts, network cards, I2C/SPI).
    """
    try:
        with open("/proc/interrupts", "rb", buffering=0) as f:
            # Ingest first 2KB containing rapid-fire timer and I/O lines
            return hashlib.sha256(f.read(2048)).hexdigest()[:16]
    except Exception:
        return "0" * 16

def get_memory_jitter() -> Dict[str, int]:
    """Reads instantaneous volatile memory allocations and swap state."""
    vm = psutil.virtual_memory()
    return {
        "avail": vm.available,
        "free": vm.free,
    }

# --- TIER 3: HARDENED HYBRID ENTROPY ACCUMULATOR ---

class HardenedEntropyAccumulator:
    """
    Cryptographic accumulator combining physical silicon noise,
    dynamic context-switch drift, and OS kernel CSPRNG seeds.
    """
    def __init__(self):
        self._hasher = hashlib.sha256()
        # Seed initial state with 32 bytes of true kernel CSPRNG entropy
        self._hasher.update(b"JetWeaver-Hardened-Pool-v2:" + os.urandom(32))
        self.sample_count = 0
        self.jitter_history = []

    def ingest_epoch(
        self,
        jitter_ns: int,
        nominal_interval_ns: int,
        thermals: Dict[str, float],
        interrupt_hash: str,
        mem_counters: Dict[str, int]
    ) -> str:
        """
        Mixes physical telemetry, execution drift, kernel entropy,
        and high-resolution clock ticks into the SHA-256 digest.
        """
        t_wall_ns = time.time_ns()
        t_mono_ns = time.monotonic_ns()
        kernel_salt = os.urandom(16)  # 128-bit cryptographic guarantee per epoch

        # Telemetry packet
        payload = (
            f"W:{t_wall_ns}|M:{t_mono_ns}|J:{jitter_ns}/{nominal_interval_ns}|"
            f"INT:{interrupt_hash}|TH:{sorted(thermals.items())}|"
            f"MEM:{sorted(mem_counters.items())}|"
        ).encode("utf-8") + kernel_salt

        self._hasher.update(payload)
        self.sample_count += 1
        self.jitter_history.append(jitter_ns)

        # Return rolling pool state
        return self._hasher.copy().hexdigest()

    def finalize_bytes(self) -> bytes:
        """Locks the entropy pool with a final kernel CSPRNG pass."""
        self._hasher.update(b"FINAL_SALT:" + os.urandom(32))
        return self._hasher.digest()

# --- HARVEST CONTROLLER WITH DYNAMIC CADENCE ---

def run_harvest_test(duration_sec: int = 10):
    print("=" * 65)
    print("   JETWEAVER: HARDENED ENTROPY ENGINE (ANTI-COLLAPSE ACTIVE)")
    print("=" * 65)
    print(f"[*] Running {duration_sec}s test with active perturbation & dynamic cadence...\n")

    accumulator = HardenedEntropyAccumulator()
    end_time = time.time() + duration_sec
    base_sleep_ms = 40.0  # Base ~25 Hz sampling rate

    while True:
        now = time.time()
        remaining = end_time - now
        if remaining <= 0:
            break

        # 1. Active hardware perturbation (wake up cores and cause bus traffic)
        perturb_silicon(rounds=2000)

        # 2. Dynamic Cadence: Perturb sleep duration by ±15% to break tick sync
        # Uses os.urandom byte to determine non-deterministic sleep target
        jitter_offset_ms = (int.from_bytes(os.urandom(1), "little") / 255.0 * 12.0) - 6.0
        target_sleep_ms = max(10.0, base_sleep_ms + jitter_offset_ms)
        target_sleep_ns = int(target_sleep_ms * 1_000_000)

        # 3. High-resolution timing of sleep duration
        t_before = time.perf_counter_ns()
        time.sleep(target_sleep_ms / 1000.0)
        t_after = time.perf_counter_ns()

        actual_elapsed_ns = t_after - t_before
        scheduling_jitter_ns = actual_elapsed_ns - target_sleep_ns

        # 4. Gather telemetry
        thermals = get_thermal_sensors()
        interrupt_hash = get_interrupt_delta()
        mem_counters = get_memory_jitter()

        # 5. Mix into the continuous pool
        current_pool = accumulator.ingest_epoch(
            jitter_ns=scheduling_jitter_ns,
            nominal_interval_ns=target_sleep_ns,
            thermals=thermals,
            interrupt_hash=interrupt_hash,
            mem_counters=mem_counters
        )

        cpu_temp = thermals.get("cpu-thermal", 0.0)
        gpu_temp = thermals.get("gpu-thermal", 0.0)
        print(
            f"\r[Left: {remaining:04.1f}s] Samples: {accumulator.sample_count:03d} | "
            f"Jitter: {scheduling_jitter_ns:+08d} ns | CPU: {cpu_temp:.1f}°C | Pool: {current_pool[:14]}...",
            end="",
            flush=True
        )

    # Compute variance / standard deviation of collected jitter
    jitters = accumulator.jitter_history
    mean_jitter = sum(jitters) / len(jitters)
    variance = sum((x - mean_jitter) ** 2 for x in jitters) / len(jitters)
    std_dev_ns = math.sqrt(variance)

    final_seed = accumulator.finalize_bytes()

    print("\n\n" + "=" * 65)
    print("             ENTROPY VERIFICATION SUMMARY")
    print("=" * 65)
    print(f"Total Epochs Processed   : {accumulator.sample_count}")
    print(f"Mean Scheduling Offset   : {mean_jitter:+.2f} ns")
    print(f"Jitter Standard Dev (σ)  : {std_dev_ns:.2f} ns (Robust Variance)")
    print(f"Final 256-bit Seed (Hex) : {final_seed.hex()}")
    print("=" * 65)

if __name__ == "__main__":
    import sys
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    run_harvest_test(duration)
