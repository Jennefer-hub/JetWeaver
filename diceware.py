import os
import sys
from typing import List, Tuple

WORDLIST_FILE = os.path.join(os.path.dirname(__file__), "eff_words.bin")

class DicewareEngine:
    """
    Offline Diceware Passphrase Engine:
    - Loads 7,776 EFF words from local binary cache.
    - Uses rejection sampling to guarantee zero modulo bias.
    - Generates 5-word, 6-word, and hybrid delimited passphrases.
    """
    def __init__(self, cache_path: str = WORDLIST_FILE):
        if not os.path.exists(cache_path):
            raise FileNotFoundError(
                f"Wordlist cache '{cache_path}' not found. Run setup_wordlist.py first."
            )
        with open(cache_path, "rb") as f:
            self.words = [w.strip() for w in f.read().decode("utf-8").split("\n") if w.strip()]

        if len(self.words) != 7776:
            raise ValueError(f"Corrupt cache: expected 7,776 words, loaded {len(self.words)}")

    def derive_indices(self, entropy_stream: bytes, count: int) -> List[int]:
        """
        Extracts unbiased word indices [0..7775] using rejection sampling.
        """
        indices = []
        offset = 0
        limit = 62208  # Highest multiple of 7776 below 65536 (8 * 7776)

        # Extend stream via SHA-256 expansion if needed
        import hashlib
        stream = bytearray(entropy_stream)
        counter = 0

        while len(indices) < count:
            if offset + 2 > len(stream):
                # Expand stream deterministically using HKDF-style counter block
                stream.extend(hashlib.sha256(stream + counter.to_bytes(4, "big")).digest())
                counter += 1

            # Read 16-bit big-endian unsigned integer
            val = (stream[offset] << 8) | stream[offset + 1]
            offset += 2

            # Rejection threshold to eliminate modulo bias
            if val < limit:
                indices.append(val % 7776)

        return indices

    def generate_passphrases(self, raw_entropy_salt: bytes) -> dict:
        """
        Derives standard 5-word, 6-word, and hybrid passphrases from entropy.
        """
        # 1. Standard 5-Word Passphrase (~64.6 bits entropy)
        idx_5 = self.derive_indices(raw_entropy_salt[:16], count=5)
        words_5 = [self.words[i] for i in idx_5]
        phrase_5 = "-".join(words_5)

        # 2. Standard 6-Word Passphrase (~77.5 bits entropy)
        idx_6 = self.derive_indices(raw_entropy_salt[16:32] + raw_entropy_salt[:8], count=6)
        words_6 = [self.words[i] for i in idx_6]
        phrase_6 = "-".join(words_6)

        # 3. Hybrid Passphrase (4 words + hardware hex delimiter + numeric suffix)
        idx_hybrid = self.derive_indices(raw_entropy_salt[8:24], count=4)
        hex_token = raw_entropy_salt[:2].hex()
        num_token = str(raw_entropy_salt[-1] % 90 + 10)  # Two-digit integer (10-99)
        hybrid_phrase = f"{self.words[idx_hybrid[0]]}-{self.words[idx_hybrid[1]]}.{hex_token}.{self.words[idx_hybrid[2]]}-{self.words[idx_hybrid[3]]}#{num_token}"

        return {
            "passphrase_5": phrase_5,
            "passphrase_6": phrase_6,
            "hybrid_passphrase": hybrid_phrase
        }

def test_engine():
    print("=" * 65)
    print("   JETWEAVER: EFF DICEWARE PASSPHRASE ENGINE VERIFICATION")
    print("=" * 65)

    engine = DicewareEngine()
    print(f"[+] Loaded {len(engine.words)} EFF words successfully.")

    # Mock test with a sample 32-byte cryptographic salt
    mock_salt = os.urandom(32)
    print(f"[*] Mock Silicon Salt : {mock_salt.hex()[:24]}...\n")

    results = engine.generate_passphrases(mock_salt)
    print(f"1. 5-Word Passphrase (~65 bits) : {results['passphrase_5']}")
    print(f"2. 6-Word Passphrase (~78 bits) : {results['passphrase_6']}")
    print(f"3. Hybrid Form-Ready Passphrase : {results['hybrid_passphrase']}")
    print("=" * 65)

if __name__ == "__main__":
    test_engine()
