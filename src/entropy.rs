use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::hint::black_box;
use std::io::Read;
use std::path::Path;
use std::time::Instant;

/// Tier 1: Active Hardware Perturbation
/// Runs non-linear floating-point iterations (logistic map) and memory heap churn.
/// std::hint::black_box prevents the LLVM compiler from optimizing away the loop in release mode.
pub fn perturb_silicon(rounds: usize) {
    let mut acc = 1.000007f64;
    for _ in 1..rounds {
        acc = black_box((3.99 * acc * (1.0 - (acc % 1.0))) % 1000.0);
    }

    let mut churn = Vec::with_capacity(128);
    for i in 0..128 {
        churn.push(((acc as u64 + i as u64) % 256) as u8);
    }

    let mut hasher = Sha256::new();
    hasher.update(&churn);
    let _ = black_box(hasher.finalize());
}

/// Tier 2: Low-Level Hardware Telemetry Harvester

/// Scans and parses onboard Jetson thermal zones (/sys/devices/virtual/thermal/thermal_zone*).
pub fn get_thermal_sensors() -> Vec<(String, f32)> {
    let mut sensors = Vec::new();
    let thermal_base = Path::new("/sys/devices/virtual/thermal");
    
    let entries = match fs::read_dir(thermal_base) {
        Ok(e) => e,
        Err(_) => return sensors,
    };

    for entry in entries.flatten() {
        let file_name = entry.file_name().to_string_lossy().to_string();
        if !file_name.starts_with("thermal_zone") {
            continue;
        }

        let zone_path = entry.path();
        let type_path = zone_path.join("type");
        let temp_path = zone_path.join("temp");

        let sensor_name = fs::read_to_string(&type_path)
            .map(|s| s.trim().to_string())
            .unwrap_or_else(|_| file_name.clone());

        if let Ok(temp_str) = fs::read_to_string(&temp_path) {
            if let Ok(milli) = temp_str.trim().parse::<i32>() {
                if milli > 0 {
                    sensors.push((sensor_name, (milli as f32) / 1000.0));
                }
            }
        }
    }

    sensors.sort_by(|a, b| a.0.cmp(&b.0));
    sensors
}

/// Ingests up to 2KB of /proc/interrupts to capture asynchronous I/O and timer events.
pub fn get_interrupt_delta() -> String {
    if let Ok(mut file) = File::open("/proc/interrupts") {
        let mut buf = [0u8; 2048];
        let n = file.read(&mut buf).unwrap_or(0);
        if n > 0 {
            let mut hasher = Sha256::new();
            hasher.update(&buf[..n]);
            let digest = hasher.finalize();
            return format!("{:x}", digest)[..16].to_string();
        }
    }
    "0".repeat(16)
}

/// Parses /proc/meminfo to extract volatile available and free memory counters.
pub fn get_memory_jitter() -> (u64, u64) {
    let mut mem_avail = 0u64;
    let mut mem_free = 0u64;

    if let Ok(content) = fs::read_to_string("/proc/meminfo") {
        for line in content.lines() {
            if line.starts_with("MemAvailable:") {
                mem_avail = line
                    .split_whitespace()
                    .nth(1)
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(0);
            } else if line.starts_with("MemFree:") {
                mem_free = line
                    .split_whitespace()
                    .nth(1)
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(0);
            }
        }
    }
    (mem_avail, mem_free)
}

/// Calculates mean scheduling drift and standard deviation (sigma) across collected epochs.
pub fn compute_jitter_stats(history: &[i64]) -> (f64, f64) {
    if history.is_empty() {
        return (0.0, 0.0);
    }
    let mean = history.iter().sum::<i64>() as f64 / history.len() as f64;
    let variance = history
        .iter()
        .map(|&x| {
            let diff = x as f64 - mean;
            diff * diff
        })
        .sum::<f64>()
        / history.len() as f64;
    (mean, variance.sqrt())
}

/// Tier 3: Hardened Hybrid Cryptographic Accumulator
pub struct HardenedEntropyAccumulator {
    hasher: Sha256,
    pub sample_count: usize,
    pub jitter_history: Vec<i64>,
}

impl HardenedEntropyAccumulator {
    /// Initializes pool seeded with 32 bytes from Linux getrandom(2) syscall.
    pub fn new() -> Self {
        let mut initial_salt = [0u8; 32];
        getrandom::getrandom(&mut initial_salt).expect("Kernel CSPRNG failure");

        let mut hasher = Sha256::new();
        hasher.update(b"JetWeaver-Hardened-Pool-v2:");
        hasher.update(&initial_salt);

        Self {
            hasher,
            sample_count: 0,
            jitter_history: Vec::new(),
        }
    }

    /// Mixes scheduling jitter, telemetry, unbuffered hardware readings, and
    /// 16 bytes of CSPRNG entropy into the continuous digest.
    pub fn ingest_epoch(
        &mut self,
        jitter_ns: i64,
        nominal_interval_ns: u64,
        thermals: &[(String, f32)],
        interrupt_hash: &str,
        mem_counters: (u64, u64),
    ) -> String {
        let mut kernel_salt = [0u8; 16];
        getrandom::getrandom(&mut kernel_salt).expect("Kernel CSPRNG failure");

        let mut thermal_str = String::new();
        for (name, val) in thermals {
            thermal_str.push_str(&format!("{}:{:.2},", name, val));
        }

        let payload = format!(
            "M:{:?}|J:{}/{}|INT:{}|TH:{}|MEM:{},{}|",
            Instant::now(),
            jitter_ns,
            nominal_interval_ns,
            interrupt_hash,
            thermal_str,
            mem_counters.0,
            mem_counters.1
        );

        self.hasher.update(payload.as_bytes());
        self.hasher.update(&kernel_salt);
        self.sample_count += 1;
        self.jitter_history.push(jitter_ns);

        let current_digest = self.hasher.clone().finalize();
        format!("{:x}", current_digest)
    }

    /// Closes the pool with a 32-byte CSPRNG salt and returns the finalized 32-byte hardware key.
    pub fn finalize_bytes(&mut self) -> [u8; 32] {
        let mut final_salt = [0u8; 32];
        getrandom::getrandom(&mut final_salt).expect("Kernel CSPRNG failure");

        self.hasher.update(b"FINAL_SALT:");
        self.hasher.update(&final_salt);

        let digest = self.hasher.clone().finalize();
        let mut out = [0u8; 32];
        out.copy_from_slice(&digest);
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_perturb_silicon_execution() {
        perturb_silicon(100);
    }

    #[test]
    fn test_accumulator_lifecycle() {
        let mut acc = HardenedEntropyAccumulator::new();
        let thermals = vec![("cpu-thermal".to_string(), 45.2)];
        let hex_state = acc.ingest_epoch(1250, 40_000_000, &thermals, "test_hash", (1024, 512));
        assert_eq!(hex_state.len(), 64);
        assert_eq!(acc.sample_count, 1);

        let final_key = acc.finalize_bytes();
        assert_eq!(final_key.len(), 32);
    }

    #[test]
    fn test_jitter_stats() {
        let history = vec![10, 20, 30, 40, 50];
        let (mean, sigma) = compute_jitter_stats(&history);
        assert_eq!(mean, 30.0);
        assert!(sigma > 14.14 && sigma < 14.15);
    }
}
