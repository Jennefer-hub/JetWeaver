import os
import sys
import urllib.request

EFF_URL = "https://www.eff.org/files/2016/07/18/eff_large_wordlist.txt"
OUTPUT_BIN = "eff_words.bin"

def build_eff_cache():
    print("[*] Fetching official EFF Large Wordlist...")
    try:
        req = urllib.request.Request(
            EFF_URL,
            headers={"User-Agent": "JetWeaver-Setup/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
    except Exception as e:
        print(f"[!] Failed to download wordlist: {e}")
        sys.exit(1)

    words = []
    for line in content.strip().splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            words.append(parts[1].lower())

    if len(words) != 7776:
        print(f"[!] Warning: Expected 7,776 words, parsed {len(words)}. Aborting.")
        sys.exit(1)

    # Serialize into a newline-delimited binary format for sub-millisecond offline reads
    raw_payload = "\n".join(words).encode("utf-8")
    with open(OUTPUT_BIN, "wb") as f:
        f.write(raw_payload)

    print(f"[+] Successfully validated 7,776 EFF words.")
    print(f"[+] Compiled offline dictionary cache to: {OUTPUT_BIN} ({len(raw_payload)} bytes)")

if __name__ == "__main__":
    build_eff_cache()
