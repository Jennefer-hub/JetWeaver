mod crypto;
mod diceware;
mod entropy;
mod export;
mod handler;
mod secure;
mod time_token;

use crypto::synthesize_credentials;
use diceware::DicewareEngine;
use entropy::{
    compute_jitter_stats, get_interrupt_delta, get_memory_jitter, get_thermal_sensors,
    perturb_silicon, HardenedEntropyAccumulator,
};
use export::{run_ephemeral_export_flow, DEFAULT_EXPORT_PATH};
use handler::{handle_interruption_triage, safe_write, InterruptionHandler, TriageDecision};
use secure::SecureStoryReader;
use time_token::{format_human_duration, parse_time_token, DEFAULT_MAX_SEC, DEFAULT_MIN_SEC};

use std::io::{self, BufRead, Write};
use std::process;
use std::thread;
use std::time::{Duration, Instant};

fn main() {
    println!("===============================================================");
    println!("   PROJECT JETWEAVER: NATIVE HARDWARE CRYPTOGRAPHIC ENGINE");
    println!("   PLATFORM : NVIDIA JETSON ORIN NANO (ARM64 NATIVE)");
    println!("===============================================================");

    // -------------------------------------------------------------
    // STAGE 1: OBSERVATION DURATION INGESTION
    // -------------------------------------------------------------
    println!("\n[Stage 1] Enter observation window (e.g. '15sc', '2mt', '1hr', '1dy'):");
    print!("> ");
    let _ = io::stdout().flush();

    let mut raw_time = String::new();
    let stdin = io::stdin();
    stdin.lock().read_line(&mut raw_time).unwrap_or(0);

    let duration_sec = match parse_time_token(&raw_time, DEFAULT_MIN_SEC, DEFAULT_MAX_SEC) {
        Ok(sec) => {
            println!(
                "[+] Target window locked: {} seconds ({})",
                sec,
                format_human_duration(sec)
            );
            sec
        }
        Err(err) => {
            println!("[!] {}. Defaulting to nominal 10 seconds.", err);
            10
        }
    };

    // -------------------------------------------------------------
    // STAGE 2: MEMORY INGESTION (DUAL-MODE: FAST FORGE VS STORY)
    // -------------------------------------------------------------
    println!("\n[Stage 2] Secret Semantic Narrative Ingestion");
    println!("  [*] Press [ENTER]         -> Fast Silicon Forge (Kernel CSPRNG + Silicon Noise)");
    println!("  [*] Type 's' + [ENTER]    -> Launch Secure Viewport (Story-Anchored Key)");
    print!("Choice [ENTER to Skip] > ");
    let _ = io::stdout().flush();

    let mut choice_buf = String::new();
    let _ = stdin.lock().read_line(&mut choice_buf);
    let choice = choice_buf.trim().to_lowercase();

    let story_digest: [u8; 64] = if choice.is_empty() || choice == "skip" {
        println!("[+] Story bypassed. Fast Silicon Forge activated.");
        let mut kernel_ikm = [0u8; 64];
        getrandom::getrandom(&mut kernel_ikm).expect("Kernel CSPRNG failure for IKM");
        println!("[+] Ingested 64 bytes of kernel CSPRNG entropy into HKDF IKM.");
        kernel_ikm
    } else {
        println!("[*] Launching isolated memory viewport...");
        match SecureStoryReader::read_story() {
            Ok(story_bytes) => {
                if story_bytes.is_empty() {
                    println!("[!] Story buffer empty. Defaulting to kernel CSPRNG IKM.");
                    let mut kernel_ikm = [0u8; 64];
                    getrandom::getrandom(&mut kernel_ikm).expect("Kernel CSPRNG failure");
                    kernel_ikm
                } else {
                    println!(
                        "[+] Story captured ({} bytes). Deriving semantic SHA-512 anchor...",
                        story_bytes.len()
                    );
                    let digest = SecureStoryReader::process_and_zeroize(story_bytes);
                    println!("[+] Memory sanitized. Source buffers zeroized with compiler fences.");
                    digest
                }
            }
            Err(err) => {
                eprintln!("\n[-] Secure input failure: {}", err);
                process::exit(1);
            }
        }
    };

    // -------------------------------------------------------------
    // STAGE 3: SILICON ENTROPY HARVEST & FAULT TRIAGE
    // -------------------------------------------------------------
    println!("\n[Stage 3] Initiating Physical Silicon Entropy Harvest ({}s)", duration_sec);
    println!("[*] Interruption safety active: Press [Ctrl+C] at any time for Early Synthesis.\n");

    let signal_handler = InterruptionHandler::new().expect("Failed to initialize signal hooks");
    let mut accumulator = HardenedEntropyAccumulator::new();

    let target_duration = Duration::from_secs(duration_sec);
    let start_time = Instant::now();
    let base_sleep_ms = 40.0f64;
    let mut last_ui_render = Instant::now();

    loop {
        // POSIX SIGINT check
        if signal_handler.is_interrupted() {
            match handle_interruption_triage(accumulator.sample_count) {
                TriageDecision::SynthesizeEarly => {
                    break;
                }
                TriageDecision::HardAbort => {
                    process::exit(130);
                }
            }
        }

        let elapsed = start_time.elapsed();
        if elapsed >= target_duration {
            safe_write("\n\n[+] Observation window reached nominal completion.\n");
            break;
        }

        let remaining_sec = (target_duration - elapsed).as_secs_f64();

        // 1. Silicon perturbation: Force ALU switching and memory bus churn
        perturb_silicon(1500);

        // 2. Dynamic cadence jitter (±6ms drift)
        let mut rand_byte = [0u8; 1];
        getrandom::getrandom(&mut rand_byte).expect("getrandom failed");
        let jitter_offset_ms = (rand_byte[0] as f64 / 255.0 * 12.0) - 6.0;
        let target_sleep_ms = (base_sleep_ms + jitter_offset_ms).max(10.0);
        let target_sleep_dur = Duration::from_secs_f64(target_sleep_ms / 1000.0);
        let target_sleep_ns = target_sleep_dur.as_nanos() as u64;

        // 3. Sub-microsecond context-switch jitter measurement
        let t_before = Instant::now();
        thread::sleep(target_sleep_dur);
        let actual_elapsed_ns = t_before.elapsed().as_nanos() as u64;
        let scheduling_jitter_ns = (actual_elapsed_ns as i64) - (target_sleep_ns as i64);

        // 4. Low-level hardware telemetry ingestion
        let thermals = get_thermal_sensors();
        let interrupt_hash = get_interrupt_delta();
        let mem_counters = get_memory_jitter();

        // 5. Ingest into continuous SHA-256 pool
        let pool_hex = accumulator.ingest_epoch(
            scheduling_jitter_ns,
            target_sleep_ns,
            &thermals,
            &interrupt_hash,
            mem_counters,
        );

        if last_ui_render.elapsed().as_millis() >= 80 {
            let cpu_temp = thermals
                .iter()
                .find(|(name, _)| name.contains("cpu") || name.contains("CPU"))
                .map(|(_, val)| *val)
                .unwrap_or(0.0);

            let status = format!(
                "\r[Remaining: {:05.1}s] Samples: {:04} | Jitter: {:+08} ns | CPU: {:>4.1}°C | Pool: {}...",
                remaining_sec.max(0.0),
                accumulator.sample_count,
                scheduling_jitter_ns,
                cpu_temp,
                &pool_hex[..12]
            );
            safe_write(&status);
            last_ui_render = Instant::now();
        }
    }

    let (mean_jitter, std_dev_ns) = compute_jitter_stats(&accumulator.jitter_history);
    let hardware_salt = accumulator.finalize_bytes();

    // -------------------------------------------------------------
    // STAGE 4: CRYPTOGRAPHIC SYNTHESIS & DICEWARE EXPANSION
    // -------------------------------------------------------------
    println!("\n[Stage 4] Synthesizing Unbiased Credentials (RFC 5869 HKDF-SHA256)...");
    let creds = synthesize_credentials(&hardware_salt, &story_digest)
        .expect("Cryptographic derivation failure");

    let diceware = DicewareEngine::new().expect("Failed to initialize Diceware wordlist");
    let passphrases = diceware.generate_passphrases(&creds.diceware_seed);

    let credential_matrix = [
        ("Master Vault Key (32-char)", creds.master_32.as_str()),
        ("Standard Token (16-char)", creds.standard_16.as_str()),
        ("Raw Entropy Salt (Hex)", &creds.raw_hex_salt[..32]),
        ("5-Word Diceware (~65 bits)", passphrases.passphrase_5.as_str()),
        ("6-Word Diceware (~78 bits)", passphrases.passphrase_6.as_str()),
        ("Hybrid Form-Ready Key", passphrases.hybrid.as_str()),
    ];

    println!("\n===============================================================");
    println!("             PROJECT JETWEAVER: SYNTHESIS SUCCESS");
    println!("===============================================================");
    println!("Total Epochs Processed   : {}", accumulator.sample_count);
    println!("Mean Scheduling Drift    : {:+.2} ns", mean_jitter);
    println!("Jitter Standard Dev (σ)  : {:.2} ns", std_dev_ns);
    println!("---------------------------------------------------------------");
    for (label, val) in &credential_matrix {
        println!("{:<30} : {}", label, val);
    }
    println!("===============================================================");

    // -------------------------------------------------------------
    // STAGE 5: EPHEMERAL EXPORT LIFECYCLE
    // -------------------------------------------------------------
    print!("\n[?] Export credentials to a chmod 600 self-destructing file? [y/N]: ");
    let _ = io::stdout().flush();

    let mut export_choice = String::new();
    stdin.lock().read_line(&mut export_choice).unwrap_or(0);

    let clean_choice = export_choice.trim().to_lowercase();
    if clean_choice == "y" || clean_choice == "yes" {
        if let Err(e) = run_ephemeral_export_flow(DEFAULT_EXPORT_PATH, &credential_matrix) {
            eprintln!("[-] Ephemeral export error: {}", e);
        }
    } else {
        println!("[+] Ephemeral export bypassed. All key state cleared from memory.");
    }
}
