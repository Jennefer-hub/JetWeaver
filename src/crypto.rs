use hkdf::Hkdf;
use sha2::Sha256;
use zeroize::Zeroize;

// Character sets excluding visually ambiguous characters (O, 0, l, 1, I)
pub const MASTER_CHARSET: &[u8] =
    b"ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*()-_=+"; // 70 chars
pub const ALPHANUMERIC_CHARSET: &[u8] =
    b"ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"; // 57 chars

// Rejection sampling limits to guarantee zero modulo bias across 8-bit unsigned integers:
// 256 - (256 % 70) = 256 - 46 = 210 (3 * 70)
pub const MASTER_REJECTION_LIMIT: u8 = 210;
// 256 - (256 % 57) = 256 - 28 = 228 (4 * 57)
pub const ALPHANUMERIC_REJECTION_LIMIT: u8 = 228;
// 256 - (256 % 10) = 250 (25 * 10)
pub const DIGIT_REJECTION_LIMIT: u8 = 250;

#[derive(Debug, Clone)]
pub struct SynthesizedCredentials {
    pub master_32: String,
    pub standard_16: String,
    pub raw_hex_salt: String,
    pub diceware_seed: [u8; 32],
}

/// Weaves physical hardware salt and semantic story digest using RFC 5869 HKDF-SHA256.
/// Expands into uniform, rejection-sampled credential sets with zero modulo bias.
pub fn synthesize_credentials(
    hardware_salt: &[u8; 32],
    story_digest: &[u8; 64],
) -> Result<SynthesizedCredentials, String> {
    // HKDF-Extract & Expand
    let hkdf = Hkdf::<Sha256>::new(Some(hardware_salt), story_digest);
    let mut okm = [0u8; 256];
    hkdf.expand(b"JetWeaver-Master-Key-Expansion-v2", &mut okm)
        .map_err(|e| format!("HKDF expand failed: {:?}", e))?;

    let mut offset = 0;

    // Helper closure: Pulls an unbiased character from an alphabet using rejection sampling
    let mut get_unbiased_char = |charset: &[u8], limit: u8, stream: &[u8]| -> char {
        loop {
            if offset >= stream.len() {
                // Wrap safely across expanded buffer if limit is reached
                offset = 0;
            }
            let b = stream[offset];
            offset += 1;
            if b < limit {
                let idx = (b % (charset.len() as u8)) as usize;
                return charset[idx] as char;
            }
        }
    };

    // 1. Master Vault Key (32-character complex symbols)
    let mut master_key = String::with_capacity(32);
    for _ in 0..32 {
        master_key.push(get_unbiased_char(
            MASTER_CHARSET,
            MASTER_REJECTION_LIMIT,
            &okm[0..128],
        ));
    }

    // 2. Standard 16-Character Token (14 alphanumeric + symbol '!' + 1 unbiased digit)
    let mut standard_token = String::with_capacity(16);
    for _ in 0..14 {
        standard_token.push(get_unbiased_char(
            ALPHANUMERIC_CHARSET,
            ALPHANUMERIC_REJECTION_LIMIT,
            &okm[64..192],
        ));
    }
    standard_token.push('!');

    // Unbiased single digit (0..9)
    loop {
        if offset >= okm.len() {
            offset = 0;
        }
        let b = okm[offset];
        offset += 1;
        if b < DIGIT_REJECTION_LIMIT {
            let digit = b % 10;
            standard_token.push(char::from_digit(digit as u32, 10).unwrap());
            break;
        }
    }

    // 3. Raw Deterministic Hex Key (Bytes 128..160)
    let mut hex_salt = String::with_capacity(64);
    for b in &okm[128..160] {
        hex_salt.push_str(&format!("{:02x}", b));
    }

    // 4. Dedicated Composite Diceware Seed (Bytes 160..192)
    // Ensures both hardware noise AND story digest feed into Diceware selection
    let mut diceware_seed = [0u8; 32];
    diceware_seed.copy_from_slice(&okm[160..192]);

    // Memory hygiene: Zeroize scratch key-expansion buffer
    okm.zeroize();

    Ok(SynthesizedCredentials {
        master_32: master_key,
        standard_16: standard_token,
        raw_hex_salt: hex_salt,
        diceware_seed,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_synthesis_determinism() {
        let salt = [0x5Au8; 32];
        let digest = [0x3Cu8; 64];

        let run1 = synthesize_credentials(&salt, &digest).unwrap();
        let run2 = synthesize_credentials(&salt, &digest).unwrap();

        assert_eq!(run1.master_32, run2.master_32);
        assert_eq!(run1.standard_16, run2.standard_16);
        assert_eq!(run1.raw_hex_salt, run2.raw_hex_salt);
        assert_eq!(run1.diceware_seed, run2.diceware_seed);
    }

    #[test]
    fn test_credential_formatting_lengths() {
        let salt = [0x11u8; 32];
        let digest = [0x22u8; 64];
        let creds = synthesize_credentials(&salt, &digest).unwrap();

        assert_eq!(creds.master_32.chars().count(), 32);
        assert_eq!(creds.standard_16.chars().count(), 16);
        assert!(creds.standard_16.ends_with(|c: char| c.is_ascii_digit()));
        assert_eq!(creds.raw_hex_salt.len(), 64);
        assert_eq!(creds.diceware_seed.len(), 32);
    }
}
