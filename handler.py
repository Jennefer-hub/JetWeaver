import os
import sys
import time
import signal
import hashlib
from typing import Dict, Any

# Ignore broken pipe signals when terminal detaches
signal.signal(signal.SIGPIPE, signal.SIG_IGN)

from hardening_quirk import (
    HardenedEntropyAccumulator,
    perturb_silicon,
    get_thermal_sensors,
    get_interrupt_delta,
    get_memory_jitter
)

class InterruptionHandler:
    """Catches SIGINT (Ctrl+C) and triggers interactive decision triage."""
    def __init__(self):
        self.interrupted = False
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _handle_sigint(self, signum, frame):
        self.interrupted = True

def safe_flush_print(text: str):
    """Prints status updates safely even if stdout/pty is detached."""
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except (BrokenPipeError, IOError):
        pass

def run_resilient_loop(duration_sec: int):
    print("=" * 65)
    print("   JETWEAVER: RESILIENT FAULT-TOLERANT HARVEST ENGINE")
    print("=" * 65)
    print(f"[*] Target Duration : {duration_sec}s")
    print("[*] Controls        : Press [Ctrl+C] to test Early Synthesis\n")

    handler = InterruptionHandler()
    accumulator = HardenedEntropyAccumulator()
    end_time = time.time() + duration_sec
    base_sleep_ms = 40.0
    last_ui_update = 0.0

    while True:
        # Check if SIGINT was caught
        if handler.interrupted:
            safe_flush_print("\n\n" + "!" * 65 + "\n")
            safe_flush_print(" [!] OBSERVATION WINDOW INTERRUPTED BY USER (SIGINT)\n")
            safe_flush_print("!" * 65 + "\n")
            safe_flush_print(f"[*] Samples Collected So Far: {accumulator.sample_count}\n")
            
            if accumulator.sample_count < 10:
                safe_flush_print("[-] Insufficient entropy collected (< 10 samples). Aborting.\n")
                sys.exit(130)

            try:
                # Flush stdin buffer before asking
                import termios
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
            except Exception:
                pass

            try:
                choice = input("\n[?] Early synthesize keys with current entropy pool? [Y/n]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                choice = "n"

            if choice in ("", "y", "yes"):
                safe_flush_print("[+] Proceeding with Early Synthesis...\n")
                break
            else:
                safe_flush_print("[-] Hard abort selected. Scrubbing pool from memory...\n")
                sys.exit(130)

        now = time.time()
        remaining = end_time - now
        if remaining <= 0:
            safe_flush_print("\n\n[+] Observation window reached nominal completion.\n")
            break

        # 1. Hardware Perturbation
        perturb_silicon(rounds=1500)

        # 2. Dynamic Cadence Jitter
        jitter_offset_ms = (int.from_bytes(os.urandom(1), "little") / 255.0 * 12.0) - 6.0
        target_sleep_ms = max(10.0, base_sleep_ms + jitter_offset_ms)
        target_sleep_ns = int(target_sleep_ms * 1_000_000)

        # 3. High-res Timing
        t_before = time.perf_counter_ns()
        time.sleep(target_sleep_ms / 1000.0)
        t_after = time.perf_counter_ns()

        actual_elapsed_ns = t_after - t_before
        scheduling_jitter_ns = actual_elapsed_ns - target_sleep_ns

        # 4. Ingest Telemetry
        thermals = get_thermal_sensors()
        interrupt_hash = get_interrupt_delta()
        mem_counters = get_memory_jitter()

        current_pool = accumulator.ingest_epoch(
            jitter_ns=scheduling_jitter_ns,
            nominal_interval_ns=target_sleep_ns,
            thermals=thermals,
            interrupt_hash=interrupt_hash,
            mem_counters=mem_counters
        )

        # Rate-limit stdout updates to 5 Hz (every 0.2s) to prevent detached pty buffer crashes
        if (now - last_ui_update) >= 0.2:
            cpu_temp = thermals.get("cpu-thermal", 0.0)
            status_line = (
                f"\r[Time Left: {remaining:05.1f}s] Samples: {accumulator.sample_count:04d} | "
                f"Jitter: {scheduling_jitter_ns:+07d} ns | CPU: {cpu_temp:.1f}°C | Pool: {current_pool[:12]}..."
            )
            safe_flush_print(status_line)
            last_ui_update = now

    final_seed = accumulator.finalize_bytes()

    print("\n" + "=" * 65)
    print("             SYNTHESIS HANDOVER READY")
    print("=" * 65)
    print(f"Final Sample Count    : {accumulator.sample_count}")
    print(f"Derived Hardware Salt : {final_seed.hex()}")
    print("=" * 65)
    return final_seed

if __name__ == "__main__":
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_resilient_loop(duration)
