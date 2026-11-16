import os
import glob
import time
import hashlib
import psutil

def read_sysfs_safe(path):
    """Safely reads Linux virtual sysfs files using unbuffered raw I/O."""
    try:
        with open(path, "rb", buffering=0) as f:
            raw = f.read()
            if not raw:
                return None
            return raw.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None

def read_thermal_zones():
    """Reads temperature in degrees Celsius across all active onboard thermal zones."""
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
                # Filter out dummy sensors reporting negative or 0 values
                if temp_c > 0:
                    readings[sensor_name] = temp_c
            except ValueError:
                continue

    return readings

def sample_scheduling_drift(samples=5, nominal_ns=10_000_000):
    """Measures kernel context-switching drift in nanoseconds."""
    drifts = []
    for _ in range(samples):
        t_start = time.perf_counter_ns()
        time.sleep(nominal_ns / 1_000_000_000.0)  # Sleep nominal 10ms
        t_end = time.perf_counter_ns()
        elapsed = t_end - t_start
        jitter = elapsed - nominal_ns
        drifts.append(jitter)
    return drifts

def sample_memory_entropy():
    """Captures volatile memory allocations and process counter fluctuations."""
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    cpu_freq = psutil.cpu_freq()
    return {
        "mem_free_bytes": mem.free,
        "mem_available_bytes": mem.available,
        "swap_free_bytes": swap.free,
        "cpu_current_freq_mhz": cpu_freq.current if cpu_freq else 0,
    }

def main():
    print("=" * 55)
    print("   PROJECT JETWEAVER: TELEMETRY HARVEST PROBE")
    print("=" * 55)

    # 1. Thermal zones
    thermals = read_thermal_zones()
    print(f"\n[+] Thermal Sensors Found: {len(thermals)}")
    for zone, val in thermals.items():
        print(f"    - {zone}: {val:.2f} °C")

    # 2. Scheduling jitter
    jitters = sample_scheduling_drift()
    avg_jitter = sum(jitters) / len(jitters)
    print(f"\n[+] OS Scheduler Drift (Nominal 10ms sleep):")
    for idx, j in enumerate(jitters):
        print(f"    - Sample {idx+1}: {j:+} ns")
    print(f"    - Mean Drift: {avg_jitter:+.2f} ns")

    # 3. Volatile resource counters
    mem_state = sample_memory_entropy()
    print(f"\n[+] System Resource State:")
    for k, v in mem_state.items():
        print(f"    - {k}: {v}")

    # 4. Ephemeral sample hash
    raw_packet = f"{thermals}{jitters}{mem_state}{time.time_ns()}".encode("utf-8")
    sample_digest = hashlib.sha256(raw_packet).hexdigest()
    print(f"\n[+] Baseline Telemetry Hash (SHA-256):")
    print(f"    {sample_digest}")
    print("=" * 55)

if __name__ == "__main__":
    main()
