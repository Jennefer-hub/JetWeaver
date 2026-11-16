import os
import glob
import time
import hashlib
import psutil
from dataclasses import dataclass, field
from typing import List, Dict, Any

def read_sysfs_safe(path: str) -> str:
    """Reads Linux sysfs nodes using unbuffered raw I/O."""
    try:
        with open(path, "rb", buffering=0) as f:
            raw = f.read()
            if not raw:
                return None
            return raw.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None

def get_thermal_sensors() -> Dict[str, float]:
    """Scans and reads active hardware thermal zones."""
    readings = {}
    zone_dirs = sorted(glob.glob("/sys/devices/virtual/thermal/thermal_zone*"))
    for zone in zone_dirs:
        temp_path = os.path.join(zone, "temp")
        type_path = os.path.join(zone, "type")

        sensor_name = read_sysfs_safe(type_path) or os.path.basename(zone)
        temp_str = read_sysfs_safe(temp_path)

        if temp_str is not None:
            try:
                temp_c = int(temp_str) / 1000.0
                if temp_c > 0:
                    readings[sensor_name] = round(temp_c, 2)
            except ValueError:
                continue
    return readings

def get_system_counters() -> Dict[str, Any]:
    """Pulls memory, swap, and CPU frequency fluctuations."""
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    cpu_freq = psutil.cpu_freq()
    return {
        "mem_available": mem.available,
        "swap_free": swap.free,
        "cpu_freq": cpu_freq.current if cpu_freq else 0.0,
    }

class EntropyAccumulator:
    """
    Maintains a rolling cryptographic digest.
    Each sample of physical jitter, thermal drift, and memory state
    is mixed into an internal 256-bit entropy pool.
    """
    def __init__(self, initial_salt: bytes = b""):
        self._hasher = hashlib.sha256()
        self._hasher.update(b"JetWeaver-Initial-Entropy-Pool-v1")
        if initial_salt:
            self._hasher.update(initial_salt)
        self.sample_count = 0
        self.total_jitter_abs_ns = 0

    def mix_sample(self, jitter_ns: int, thermals: Dict[str, float], counters: Dict[str, Any]) -> str:
        """Stirs incoming physical telemetry and timestamp into the SHA-256 pool."""
        sample_time_ns = time.time_ns()
        
        # Binary packet representation
        packet = (
            f"T:{sample_time_ns}|J:{jitter_ns}|TH:{sorted(thermals.items())}|C:{sorted(counters.items())}"
        ).encode("utf-8")
        
        self._hasher.update(packet)
        self.sample_count += 1
        self.total_jitter_abs_ns += abs(jitter_ns)
        
        # Return instantaneous hash representation without finalizing
        return self._hasher.copy().hexdigest()

    def finalize(self) -> str:
        """Locks the entropy pool and produces the final 64-character hex seed."""
        return self._hasher.hexdigest()

def run_observation_window(duration_sec: int, sample_interval_ms: int = 100):
    """
    Runs the live countdown loop, continuously measuring scheduling jitter
    and accumulating hardware noise into the pool.
    """
    print(f"\n[+] Initializing Entropy Accumulation Pool")
    print(f"[+] Observation Window: {duration_sec}s | Interval: {sample_interval_ms}ms\n")

    accumulator = EntropyAccumulator()
    interval_ns = sample_interval_ms * 1_000_000
    end_time = time.time() + duration_sec

    start_mono = time.monotonic()
    
    while True:
        now = time.time()
        remaining = end_time - now
        if remaining <= 0:
            break

        # Measure kernel scheduling drift (jitter)
        t_before = time.perf_counter_ns()
        time.sleep(sample_interval_ms / 1000.0)
        t_after = time.perf_counter_ns()
        
        elapsed_ns = t_after - t_before
        jitter_ns = elapsed_ns - interval_ns

        # Sample hardware state
        thermals = get_thermal_sensors()
        counters = get_system_counters()

        # Mix into continuous rolling hash
        current_digest = accumulator.mix_sample(jitter_ns, thermals, counters)

        # In-place terminal status line
        cpu_temp = thermals.get("cpu-thermal", 0.0)
        gpu_temp = thermals.get("gpu-thermal", 0.0)
        print(
            f"\r[Time Left: {remaining:04.1f}s] Samples: {accumulator.sample_count:04d} | "
            f"Jitter: {jitter_ns:+07d} ns | CPU: {cpu_temp:.1f}°C | Pool: {current_digest[:16]}...",
            end="",
            flush=True
        )

    # Instantaneous handover
    final_seed = accumulator.finalize()
    print("\n\n" + "=" * 65)
    print("   OBSERVATION WINDOW COMPLETE - INSTANTANEOUS HANDOVER")
    print("=" * 65)
    print(f"Total Samples Ingested : {accumulator.sample_count}")
    print(f"Mean Abs Jitter        : {accumulator.total_jitter_abs_ns / accumulator.sample_count:.1f} ns")
    print(f"Final 256-Bit Hardware Seed:")
    print(f"{final_seed}")
    print("=" * 65)
    return final_seed

if __name__ == "__main__":
    import sys
    # Default to 10 seconds for initial testing; accepts CLI arg for duration
    test_duration = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    run_observation_window(test_duration)
