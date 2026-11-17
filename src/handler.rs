use signal_hook::consts::{SIGINT, SIGPIPE};
use signal_hook::flag;
use std::io::{self, BufRead, Write};
use std::process;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

pub struct InterruptionHandler {
    interrupted: Arc<AtomicBool>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum TriageDecision {
    SynthesizeEarly,
    HardAbort,
}

impl InterruptionHandler {
    /// Registers POSIX signal hooks:
    /// - Routes SIGINT (Ctrl+C) to an atomic flag for interactive triage.
    /// - Suppresses SIGPIPE termination so detached tmux/SSH sessions do not crash on write.
    pub fn new() -> io::Result<Self> {
        let interrupted = Arc::new(AtomicBool::new(false));
        flag::register(SIGINT, Arc::clone(&interrupted))?;

        let sigpipe_sink = Arc::new(AtomicBool::new(false));
        flag::register(SIGPIPE, sigpipe_sink)?;

        Ok(Self { interrupted })
    }

    /// Returns whether SIGINT has been caught.
    pub fn is_interrupted(&self) -> bool {
        self.interrupted.load(Ordering::SeqCst)
    }

    /// Resets the interruption flag (used in test harness).
    #[allow(dead_code)]
    pub fn reset(&self) {
        self.interrupted.store(false, Ordering::SeqCst);
    }
}

/// Safely writes to stdout without panicking if the terminal or SSH pipe is closed.
pub fn safe_write(text: &str) {
    let mut out = io::stdout();
    let _ = out.write_all(text.as_bytes());
    let _ = out.flush();
}

/// Interactive triage prompt triggered when Ctrl+C is caught during entropy harvesting.
pub fn handle_interruption_triage(samples_collected: usize) -> TriageDecision {
    safe_write("\n\n");
    safe_write("===============================================================\n");
    safe_write(" [!] OBSERVATION WINDOW INTERRUPTED BY USER (SIGINT / Ctrl+C)\n");
    safe_write("===============================================================\n");
    safe_write(&format!("[*] Epochs Collected So Far: {}\n", samples_collected));

    if samples_collected < 10 {
        safe_write("[-] Insufficient entropy (< 10 epochs). Cannot synthesize securely.\n");
        safe_write("[-] Hard abort executed. Scrubbing memory state...\n");
        process::exit(130);
    }

    safe_write("\n[?] Early synthesize keys with current entropy pool? [Y/n]: ");

    let mut response = String::new();
    let stdin = io::stdin();
    if stdin.lock().read_line(&mut response).is_err() {
        return TriageDecision::HardAbort;
    }

    let clean = response.trim().to_lowercase();
    if clean.is_empty() || clean == "y" || clean == "yes" {
        safe_write("[+] Early synthesis accepted. Finalizing accumulated pool...\n");
        TriageDecision::SynthesizeEarly
    } else {
        safe_write("[-] Hard abort selected. Scrubbing state and exiting...\n");
        TriageDecision::HardAbort
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_handler_registration() {
        let handler = InterruptionHandler::new().expect("Failed to register signal hooks");
        assert!(!handler.is_interrupted());
        handler.reset();
        assert!(!handler.is_interrupted());
    }

    #[test]
    fn test_safe_write_does_not_panic() {
        safe_write("test safe write call\n");
    }
}
