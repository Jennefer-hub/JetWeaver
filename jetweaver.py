import os
import sys
import time
import signal
import hashlib
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

# --- IMPORT MODULAR SUBSYSTEMS (MATCHING ACTUAL REPO FILENAMES) ---
from secure import SecureStoryReader
from time_token import parse_time_token, format_human_duration
from hardening_quirk import (
    HardenedEntropyAccumulator,
    perturb_silicon,
    get_thermal_sensors,
    get_interrupt_delta,
    get_memory_jitter
)
from diceware import DicewareEngine
from export import secure_ephemeral_export


class InterruptionHandler:
    """Catches SIGINT (Ctrl+C) and ignores SIGPIPE for safe background tmux runs."""
    def __init__(self):
        self.interrupted = False
        signal.signal(signal.SIGINT, self._handle_sigint)
        if hasattr(signal, "SIGPIPE"):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    def _handle_sigint(self, signum, frame):
        self.interrupted = True


def safe_write(text: str) -> None:
    """Safely writes to stdout without crashing if tmux/SSH detaches."""
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except (IOError, BrokenPipeError):
        pass


def process_story(story_bytes: bytearray) -> bytes:
    """
    Computes a 512-bit semantic digest directly over the mutable bytearray
    without decoding the full secret into an immutable Python str.
    """
    byte_len = len(story_bytes)
    in_word = False
    word_count = 0
    non_space_bytes = 0

    for b in story_bytes:
        if b in (32, 9, 10, 13):  # space, \t, \n, \r
            in_word = False
        else:
            non_space_bytes += 1
            if not in_word:
                word_count += 1
                in_word = True

    avg_len = non_space_bytes / max(word_count, 1)
    header = f"STORY_LEN:{byte_len}|WORDS:{word_count}|AVG_LEN:{avg_len:.3f}|BODY:".encode("utf-8")

    hasher = hashlib.sha512()
    hasher.update(header)
    hasher.update(story_bytes)
    return hasher.digest()


def synthesize_keys(hardware_salt: bytes, story_digest: bytes) -> tuple[dict, bytes]:
    """
    Derives multi-tier credentials and a 32-byte composite Diceware seed
    via RFC 5869 HKDF-SHA256 (weaving hardware salt + semantic story digest).
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=128,
        salt=hardware_salt,
        info=b"JetWeaver-Master-Key-Expansion-v2",
    )
    derived = hkdf.derive(story_digest)

    # 1. Master Vault Key (32-char complex symbols)
    charset = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*()-_=+"
    master_key = "".join(charset[b % len(charset)] for b in derived[:32])

    # 2. Standard 16-Char Token
    alphanumeric = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    std_chars = [alphanumeric[b % len(alphanumeric)] for b in derived[32:46]]
    std_chars.extend(["!", str(derived[47] % 10)])
    std_token = "".join(std_chars)

    # 3. Raw Hex Key (Bytes 48..80)
    hex_key = derived[48:80].hex()

    # 4. Dedicated 32-byte HKDF seed (Bytes 80..112) combining story + hardware for Diceware
    diceware_seed = derived[80:112]

    keys = {
        "Master Vault Key (32-char)"   : master_key,
        "Standard Token (16-char)"     : std_token,
        "Raw Entropy Salt (Hex)"       : hex_key,
    }
    return keys, diceware_seed


def main():
    print("=" * 65)
    print("   PROJECT JETWEAVER: UNIFIED MASTER PIPELINE INITIALIZED")
    print("=" * 65)

    # --- STAGE 1: TIME TOKEN PARSING ---
    print("\n[+] Enter observation duration (e.g. '30sc', '5mt', '1hr', '1wk'):")
    raw_time = input("> ").strip()
    try:
        duration_sec = parse_time_token(raw_time)
        print(f"[+] Target window locked: {duration_sec} seconds ({format_human_duration(duration_sec)})")
    except ValueError as err:
        print(f"[!] {err} Defaulting to 10 seconds.")
        duration_sec = 10

    # --- STAGE 2: SECURE STORY INGESTION ---
    input("\n[Press Enter to open Secure Terminal for Memory/Story Input] > ")
    story_buffer = SecureStoryReader.read_story()

    if not len(story_buffer):
        print("[!] Error: Story buffer cannot be empty.")
        sys.exit(1)

    print(f"[+] Story ingested securely ({len(story_buffer)} bytes). Hashing semantic anchor...")
    story_digest = process_story(story_buffer)
    SecureStoryReader.zeroize(story_buffer)
    print("[+] Memory scrubbed. Story purged from RAM.")

    # --- STAGE 3: HARDENED ENTROPY OBSERVATION WINDOW ---
    print(f"\n[+] Initiating Hardened Silicon Telemetry Observation ({duration_sec}s)...")
    print("[*] Controls: Press [Ctrl+C] at any time to trigger Early Synthesis.\n")

    sig_handler = InterruptionHandler()
    accumulator = HardenedEntropyAccumulator()
    end_time = time.time() + duration_sec
    base_sleep_ms = 40.0
    last_ui_refresh = 0.0

    while True:
        if sig_handler.interrupted:
            safe_write("\n\n" + "!" * 65 + "\n")
            safe_write(" [!] OBSERVATION WINDOW INTERRUPTED BY USER (SIGINT)\n")
            safe_write("!" * 65 + "\n")
            safe_write(f"[*] Epochs Collected: {accumulator.sample_count}\n")

            if accumulator.sample_count < 10:
                safe_write("[-] Insufficient entropy (< 10 samples). Aborting.\n")
                sys.exit(130)

            try:
                import termios
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
            except Exception:
                pass

            try:
                choice = input("\n[?] Early synthesize keys with current entropy pool? [Y/n]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                choice = "n"

            if choice in ("", "y", "yes"):
                safe_write("[+] Early synthesis accepted. Finalizing pool...\n")
                break
            else:
                safe_write("[-] Hard abort selected. Scrubbing state...\n")
                sys.exit(130)

        now = time.time()
        remaining = end_time - now
        if remaining <= 0:
            safe_write("\n\n[+] Observation window reached nominal completion.\n")
            break

        # Perturbation & Jitter
        perturb_silicon(rounds=1500)
        jitter_offset_ms = (int.from_bytes(os.urandom(1), "little") / 255.0 * 12.0) - 6.0
        target_sleep_ms = max(10.0, base_sleep_ms + jitter_offset_ms)
        target_sleep_ns = int(target_sleep_ms * 1_000_000)

        t_before = time.perf_counter_ns()
        time.sleep(target_sleep_ms / 1000.0)
        t_after = time.perf_counter_ns()

        scheduling_jitter_ns = (t_after - t_before) - target_sleep_ns
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

        if (now - last_ui_refresh) >= 0.2:
            cpu_temp = thermals.get("cpu-thermal", 0.0)
            status_line = (
                f"\r[Time Left: {remaining:05.1f}s] Samples: {accumulator.sample_count:04d} | "
                f"Jitter: {scheduling_jitter_ns:+07d} ns | CPU: {cpu_temp:.1f}°C | Pool: {current_pool[:12]}..."
            )
            safe_write(status_line)
            last_ui_refresh = now

    hardware_salt = accumulator.finalize_bytes()

    # --- STAGE 4: SYNTHESIS & DICEWARE GENERATION ---
    print("\n[+] Synthesizing cryptographic keys and passphrases...")
    base_keys, diceware_seed = synthesize_keys(hardware_salt, story_digest)

    diceware = DicewareEngine()
    passphrases = diceware.generate_passphrases(diceware_seed)

    all_credentials = {
        **base_keys,
        "5-Word Diceware (~65 bits)"    : passphrases["passphrase_5"],
        "6-Word Diceware (~78 bits)"    : passphrases["passphrase_6"],
        "Hybrid Form-Ready Passphrase"  : passphrases["hybrid_passphrase"],
    }

    print("\n" + "=" * 65)
    print("               JETWEAVER PIPELINE: SUCCESS")
    print("=" * 65)
    print(f"Total Epochs Processed : {accumulator.sample_count}")
    print("-" * 65)
    for k, v in all_credentials.items():
        print(f"{k:<30} : {v}")
    print("=" * 65)

    # --- STAGE 5: EPHEMERAL EXPORT OPTION ---
    export_choice = input("\n[?] Export credentials to a secure chmod 600 ephemeral file? [y/N]: ").strip().lower()
    if export_choice in ("y", "yes"):
        secure_ephemeral_export(all_credentials)
    else:
        print("[+] Skipping export. Secure memory cleared.")


if __name__ == "__main__":
    main()
