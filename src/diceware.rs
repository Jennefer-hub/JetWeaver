use sha2::{Digest, Sha256};

pub const EFF_WORDLIST_COUNT: usize = 7776;
pub const REJECTION_LIMIT: u16 = 62208; // 8 * 7776 (Highest multiple below 2^16)

#[derive(Debug, Clone)]
pub struct PassphraseSet {
    pub passphrase_5: String,
    pub passphrase_6: String,
    pub hybrid: String,
}

pub struct DicewareEngine {
    words: Vec<&'static str>,
}

impl DicewareEngine {
    /// Loads and validates the compile-time embedded EFF wordlist.
    pub fn new() -> Result<Self, String> {
        let raw = include_str!("eff_words.txt");
        let words: Vec<&'static str> = raw
            .lines()
            .map(|l| l.trim())
            .filter(|l| !l.is_empty())
            .collect();

        if words.len() != EFF_WORDLIST_COUNT {
            return Err(format!(
                "Corrupted wordlist: expected {} words, found {}.",
                EFF_WORDLIST_COUNT,
                words.len()
            ));
        }

        Ok(Self { words })
    }

    /// Extracts unbiased word indices [0..7775] using rejection sampling.
    /// Eliminates modulo bias across 16-bit integers.
    pub fn derive_indices(&self, entropy_stream: &[u8], count: usize) -> Vec<usize> {
        let mut indices = Vec::with_capacity(count);
        let mut stream = entropy_stream.to_vec();
        let mut offset = 0;
        let mut counter: u32 = 0;

        while indices.len() < count {
            // Expand stream deterministically using SHA-256 counter blocks if exhausted
            if offset + 2 > stream.len() {
                let mut hasher = Sha256::new();
                hasher.update(&stream);
                hasher.update(&counter.to_be_bytes());
                let chunk = hasher.finalize();
                stream.extend_from_slice(&chunk);
                counter = counter.wrapping_add(1);
            }

            // Read 16-bit big-endian unsigned integer
            let val = u16::from_be_bytes([stream[offset], stream[offset + 1]]);
            offset += 2;

            // Reject any value >= 62208 to guarantee zero modulo bias
            if val < REJECTION_LIMIT {
                indices.push((val % (EFF_WORDLIST_COUNT as u16)) as usize);
            }
        }

        indices
    }

    /// Derives standard 5-word, 6-word, and hybrid passphrases from a 32-byte hardware salt.
    pub fn generate_passphrases(&self, salt: &[u8; 32]) -> PassphraseSet {
        // 1. Standard 5-Word Passphrase (~64.6 bits entropy)
        let idx_5 = self.derive_indices(&salt[0..16], 5);
        let phrase_5 = idx_5
            .iter()
            .map(|&i| self.words[i])
            .collect::<Vec<_>>()
            .join("-");

        // 2. Standard 6-Word Passphrase (~77.5 bits entropy)
        let mut seed_6 = Vec::with_capacity(24);
        seed_6.extend_from_slice(&salt[16..32]);
        seed_6.extend_from_slice(&salt[0..8]);
        let idx_6 = self.derive_indices(&seed_6, 6);
        let phrase_6 = idx_6
            .iter()
            .map(|&i| self.words[i])
            .collect::<Vec<_>>()
            .join("-");

        // 3. Hybrid Form-Ready Passphrase (4 words + hardware hex token + numeric tail)
        let idx_hybrid = self.derive_indices(&salt[8..24], 4);
        let hex_token = format!("{:02x}{:02x}", salt[0], salt[1]);
        let num_token = (salt[31] % 90) + 10; // Two-digit integer (10..99)
        let hybrid = format!(
            "{}-{}.{}.{}-{}#{}",
            self.words[idx_hybrid[0]],
            self.words[idx_hybrid[1]],
            hex_token,
            self.words[idx_hybrid[2]],
            self.words[idx_hybrid[3]],
            num_token
        );

        PassphraseSet {
            passphrase_5: phrase_5,
            passphrase_6: phrase_6,
            hybrid,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_embedded_wordlist_load() {
        let engine = DicewareEngine::new().expect("Failed to load embedded wordlist");
        assert_eq!(engine.words.len(), 7776);
        assert_eq!(engine.words[0], "abacus");
        assert_eq!(engine.words[7775], "zoom");
    }

    #[test]
    fn test_deterministic_output() {
        let engine = DicewareEngine::new().unwrap();
        let test_salt = [0x42u8; 32];
        let run1 = engine.generate_passphrases(&test_salt);
        let run2 = engine.generate_passphrases(&test_salt);

        assert_eq!(run1.passphrase_5, run2.passphrase_5);
        assert_eq!(run1.passphrase_6, run2.passphrase_6);
        assert_eq!(run1.hybrid, run2.hybrid);
    }

    #[test]
    fn test_unbiased_indices_range() {
        let engine = DicewareEngine::new().unwrap();
        let seed = [0xA5u8; 32];
        let indices = engine.derive_indices(&seed, 100);
        assert_eq!(indices.len(), 100);
        for idx in indices {
            assert!(idx < 7776);
        }
    }
}
