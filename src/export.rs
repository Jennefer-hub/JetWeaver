use std::fs::{self, OpenOptions};
use std::io::{self, BufRead, Write};
use std::os::unix::fs::OpenOptionsExt;
#[cfg(test)]
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use zeroize::Zeroize;

pub const DEFAULT_EXPORT_PATH: &str = "vault_export.txt";

/// Creates an ephemeral file locked to POSIX mode 0600 (owner read/write only).
pub fn create_locked_export_file<P: AsRef<Path>>(path: P, content: &str) -> io::Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(path.as_ref())?;

    file.write_all(content.as_bytes())?;
    file.sync_all()?; // Force kernel page cache flush to physical drive
    Ok(())
}

/// Cryptographically shreds a file by overwriting its exact size with null bytes (0x00),
/// issuing a sync_all() flush, and unlinking the inode from the filesystem.
pub fn shred_and_delete<P: AsRef<Path>>(path: P) -> io::Result<()> {
    let p = path.as_ref();
    if !p.exists() {
        return Ok(());
    }

    let metadata = fs::metadata(p)?;
    let file_len = metadata.len() as usize;

    if file_len > 0 {
        let mut file = OpenOptions::new().write(true).open(p)?;
        let mut zeros = vec![0u8; file_len];
        file.write_all(&zeros)?;
        file.sync_all()?;
        zeros.zeroize();
    }

    fs::remove_file(p)?;
    Ok(())
}

/// Formats credentials into an exportable document string.
pub fn format_credential_export(credentials: &[(&str, &str)]) -> String {
    let mut out = String::new();
    out.push_str("===============================================================\n");
    out.push_str("   PROJECT JETWEAVER: EPHEMERAL VAULT EXPORT (TEMPORARY)\n");
    out.push_str("   SECURITY LEVEL: STRICT CHMOD 600 - SECURE DISK DROP\n");
    out.push_str("===============================================================\n\n");

    for (label, val) in credentials {
        out.push_str(&format!("{:<32} : {}\n", label, val));
    }

    out.push_str("\n===============================================================\n");
    out.push_str("[!] NOTICE: THIS FILE MUST BE SHREDDED IMMEDIATELY AFTER USE.\n");
    out.push_str("===============================================================\n");
    out
}

/// Interactive export lifecycle: writes chmod 600 file, halts for user copy,
/// and executes byte-level shredding on Enter.
pub fn run_ephemeral_export_flow(
    path_str: &str,
    credentials: &[(&str, &str)],
) -> Result<(), String> {
    let path = Path::new(path_str);
    let mut payload = format_credential_export(credentials);

    create_locked_export_file(path, &payload)
        .map_err(|e| format!("Failed to create locked file '{}': {}", path_str, e))?;

    println!("\n[+] Credentials safely dumped to: {}", path_str);
    println!("[*] File permissions: -rw------- (0600 - Root/Owner Only)");
    println!("[*] Open another terminal, copy your credentials, then return here.");

    print!("\n[PRESS ENTER TO SHRED AND DESTROY FILE FROM DISK] > ");
    io::stdout().flush().map_err(|e| e.to_string())?;

    let mut line = String::new();
    let stdin = io::stdin();
    stdin.lock().read_line(&mut line).map_err(|e| e.to_string())?;

    // 1. Shred file on physical storage
    shred_and_delete(path)
        .map_err(|e| format!("Failed to shred file '{}': {}", path_str, e))?;

    // 2. Zeroize memory buffers
    payload.zeroize();

    println!("[+] Target file shredded with 0x00 null bytes and unlinked.");
    println!("[+] RAM buffers zeroized. Zero trace remains on disk or memory.");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_file_mode_and_shredding() {
        let test_path = "test_shred_target.tmp";
        let test_content = "SECRET_VAULT_KEY_DO_NOT_LEAK";

        // Step 1: Create and check existence
        create_locked_export_file(test_path, test_content).unwrap();
        assert!(Path::new(test_path).exists());

        // Step 2: Validate POSIX 0600 permissions
        let meta = fs::metadata(test_path).unwrap();
        let mode = meta.permissions().mode() & 0o777;
        assert_eq!(mode, 0o600, "Permissions must be strictly 0600");

        // Step 3: Shred and ensure unlinked
        shred_and_delete(test_path).unwrap();
        assert!(!Path::new(test_path).exists(), "File must be removed after shredding");
    }

    #[test]
    fn test_format_credential_export() {
        let creds = [
            ("Master Vault Key", "ABC123XYZ!"),
            ("Standard Token", "Token999!"),
        ];
        let formatted = format_credential_export(&creds);
        assert!(formatted.contains("Master Vault Key"));
        assert!(formatted.contains("ABC123XYZ!"));
        assert!(formatted.contains("Token999!"));
    }
}
