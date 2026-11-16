import os
import sys

def secure_ephemeral_export(keys: dict, filename: str = "vault_export.txt") -> None:
    """
    Writes generated credentials to a chmod 600 file, waits for user confirmation,
    then securely overwrites the file with 0x00 bytes before unlinking.
    """
    export_path = os.path.abspath(filename)
    
    # 1. Prepare export content
    content = (
        "=================================================================\n"
        "                  JETWEAVER EPHEMERAL EXPORT                      \n"
        "  WARNING: THIS FILE WILL BE DESTROYED UPON SCRIPT COMPLETION   \n"
        "=================================================================\n\n"
    )
    for k, v in keys.items():
        content += f"{k:<25}: {v}\n"
    content += "\n=================================================================\n"
    encoded_bytes = content.encode("utf-8")

    # 2. Open with restricted permissions: only owner can read/write (0o600)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    mode = 0o600
    fd = os.open(export_path, flags, mode)

    try:
        with os.fdopen(fd, "wb") as f:
            f.write(encoded_bytes)
            f.flush()
            os.fsync(f.fileno())  # Force write to physical media

        print(f"\n[+] Ephemeral keys exported to: {export_path}")
        print("[!] Permissions locked to chmod 600 (User Read/Write ONLY).")
        print("[*] Copy your keys now. Once you press Enter, this file will be wiped.")
        
        input("\n[Press Enter when done to securely shred this file] > ")

    finally:
        # 3. Secure file wiping (Null-byte overwriting)
        if os.path.exists(export_path):
            file_len = os.path.getsize(export_path)
            with open(export_path, "wb") as f:
                f.write(b"\x00" * file_len)
                f.flush()
                os.fsync(f.fileno())
            os.remove(export_path)
            print(f"[+] {export_path} securely shredded (zeroized) and unlinked.")

if __name__ == "__main__":
    mock_keys = {
        "Master Vault Key": "v8!K#9pA2xL&zQ_mP+W4rT7yE3nU",
        "5-Word Diceware": "tactical-glacier-monarch-vintage-orbit",
        "Standard 16-Char": "k8M2pL9zQ4wT7y!9"
    }
    secure_ephemeral_export(mock_keys)
