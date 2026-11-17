# JetWeaver: Native Hardware-Entropy & Memory-Anchored Cryptographic Engine

![Rust](https://img.shields.io/badge/language-Rust-orange.svg)
![Platform](https://img.shields.io/badge/platform-NVIDIA%20Jetson%20Orin%20Nano%20(ARM64)-green.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)

JetWeaver is an edge-native cryptographic key and passphrase derivation engine running bare-metal on an NVIDIA Jetson Orin Nano (ARM64). It anchors high-entropy cryptographic seeds by weaving user-provided semantic narratives with physical silicon non-determinism—harvesting nanosecond kernel scheduling drift, active ALU perturbation, dynamic cadence sleep jitter, and unbuffered `/sys` thermal fluctuations via RFC 5869 HKDF-SHA256.

> **Note on Migration:** The initial proof-of-concept prototype was developed in Python and is permanently preserved under the [`python-legacy`](https://github.com/Jennefer-hub/JetWeaver/tree/python-legacy) branch and the [`v1.0-python`](https://github.com/Jennefer-hub/JetWeaver/releases/tag/v1.0-python) release tag. The current `main` branch represents the production-grade, zero-dependency Rust systems implementation.

---

## Architectural Advantages (Rust vs. Python)

| Feature | Python Prototype (Legacy) | Native Rust Engine (Current) | Systems Advantage |
| :--- | :--- | :--- | :--- |
| **Runtime Dependencies** | Python 3.10, venv, `cryptography`, `psutil` | Zero dependencies (Standalone ARM64 ELF) | No runtime or package managers required on target system |
| **Memory Footprint** | ~35–45 MB | **~2 MB total** | 95% reduction in RAM consumption |
| **Memory Sanitization** | Partial (heap strings retain copies) | **Compiler-Fenced Zeroization** (`zeroize`) | Hardware memory wiping prevents forensic memory dumping |
| **Entropy Purity** | Distorted by Python GIL & Garbage Collection | **Pure Nanosecond Scheduling Drift** | Telemetry measures real silicon and kernel scheduling drift |
| **Wordlist Ingestion** | Runtime disk file reading (`eff_words.bin`) | **Compile-Time Embedding** (`include_str!`) | Binary contains 7,776 EFF words baked directly into read-only memory |
| **Modulo Bias** | Naive modulo operator (`% charset_len`) | **Strict Rejection Sampling** | Zero statistical bias across all derived keys and passphrases |

---

## Subsystems

* **Dual-Mode Ingestion & Memory Isolation (`src/secure.rs`):** Ingests secret narratives inside an isolated ANSI alternate screen buffer (`\033[?1049h`), bypassing shell history and scrollback. Supports 2D cursor navigation, `Ctrl+R` peek toggling, `Alt+Enter` stanza breaks, and instant `[ENTER]` bypass for the Fast Silicon Forge. Memory buffers are wiped using compiler-fenced zeroization.
* **Active Silicon Perturbation & Harvesting (`src/entropy.rs`):** Prevents entropy collapse under idle conditions via chaotic logistic map switching, dynamic sleep cadence ($\pm 15\%$ drift), unbuffered `/sys` thermal readings, and volatile `/proc/interrupts` hashing stirred with kernel CSPRNG seeds (`getrandom(2)`).
* **Cryptographic Synthesis Engine (`src/crypto.rs`):** Executes RFC 5869 HKDF-SHA256 extract-and-expand routines, enforcing zero modulo bias via rejection sampling to forge 32-character master keys, 16-character tokens, and composite seeds.
* **Embedded Diceware Engine (`src/diceware.rs`):** Houses the complete 7,776-word EFF Large Wordlist compiled directly into the binary, deriving unbiased 5-word, 6-word, and hybrid passphrases.
* **Fault Triage & Session Resilience (`src/handler.rs`):** Traps POSIX `SIGINT` (`Ctrl+C`) for interactive early synthesis triage and suppresses `SIGPIPE` for headless background runs in `tmux`.
* **Ephemeral Zeroized File Drop (`src/export.rs`):** Creates temporary credential drops locked to strict POSIX mode `0600` (`-rw-------`), overwriting blocks with `0x00` null bytes and issuing `sync_all()` before unlinking.

---

## Building and Running

### Prerequisites
* NVIDIA Jetson running JetPack 5 / 6 (or any Linux aarch64 / x86_64 host)
* Rust toolchain (`rustc` and `cargo` $\ge 1.70$)

```bash
# 1. Clone repository
git clone [https://github.com/Jennefer-hub/JetWeaver.git](https://github.com/Jennefer-hub/JetWeaver.git)
cd JetWeaver

# 2. Run unit test suite (19 unit tests)
cargo test

# 3. Build optimized release binary
cargo build --release

# 4. Execute standalone binary
./target/release/jetweaver-rust
