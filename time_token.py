import re
from typing import Optional

# Canonical multipliers in seconds
TIME_MULTIPLIERS = {
    # Seconds
    "sc": 1,
    "s": 1,
    "sec": 1,
    # Minutes
    "mt": 60,
    "m": 60,
    "min": 60,
    # Hours
    "hr": 3600,
    "h": 3600,
    # Days
    "dy": 86400,
    "d": 86400,
    "day": 86400,
    # Weeks
    "wk": 604800,
    "w": 604800,
    "week": 604800,
}

# Regex matches: <optional whitespace><integer><unit string>
TOKEN_REGEX = re.compile(r"(\d+)\s*([a-zA-Z]+)")

def parse_time_token(time_str: str, min_sec: int = 3, max_sec: int = 604800) -> int:
    """
    Parses single, compound, or raw numeric time strings into total seconds.
    Examples:
      '30sc'         -> 30
      '5mt'          -> 300
      '1hr 30mt'     -> 5400
      '1dy'          -> 86400
      '10'           -> 10 (raw integer fallback)
    Enforces min_sec (default 3s) and max_sec (default 1 week).
    """
    clean_str = time_str.strip().lower()
    if not clean_str:
        raise ValueError("Time input cannot be empty.")

    # Case A: Plain integer string (e.g. "10", "60")
    if clean_str.isdigit():
        total_sec = int(clean_str)
        return _validate_bounds(total_sec, min_sec, max_sec)

    # Case B: Tokenized input (e.g. "1hr 30mt", "45sc")
    matches = TOKEN_REGEX.findall(clean_str)
    if not matches:
        raise ValueError(
            f"Invalid time format: '{time_str}'. Expected format like '30sc', '5mt', '2hr', or '1wk'."
        )

    # Validate that the entire string was consumed by tokens
    reconstructed = "".join(f"{val}{unit}" for val, unit in matches)
    stripped_original = re.sub(r"\s+", "", clean_str)
    if reconstructed != stripped_original:
        raise ValueError(f"Unrecognized characters in time string: '{time_str}'")

    total_sec = 0
    for value_str, unit_str in matches:
        if unit_str not in TIME_MULTIPLIERS:
            supported = ", ".join(sorted(set(TIME_MULTIPLIERS.keys())))
            raise ValueError(f"Unknown time unit '{unit_str}'. Supported units: {supported}")
        total_sec += int(value_str) * TIME_MULTIPLIERS[unit_str]

    return _validate_bounds(total_sec, min_sec, max_sec)

def _validate_bounds(total_sec: int, min_sec: int, max_sec: int) -> int:
    if total_sec < min_sec:
        raise ValueError(f"Duration too short ({total_sec}s). Minimum allowed is {min_sec}s.")
    if total_sec > max_sec:
        raise ValueError(f"Duration exceeds maximum ({total_sec}s). Maximum allowed is {max_sec}s (1wk).")
    return total_sec

def format_human_duration(seconds: int) -> str:
    """Helper to convert total seconds back into a clean readable string."""
    weeks, rem = divmod(seconds, 604800)
    days, rem = divmod(rem, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts = []
    if weeks: parts.append(f"{weeks}wk")
    if days: parts.append(f"{days}dy")
    if hours: parts.append(f"{hours}hr")
    if minutes: parts.append(f"{minutes}mt")
    if secs or not parts: parts.append(f"{secs}sc")
    return " ".join(parts)

if __name__ == "__main__":
    print("=" * 65)
    print("   JETWEAVER: TIME TOKEN SUFFIX PARSER TEST SUITE")
    print("=" * 65)

    test_cases = [
        "45sc",
        "10mt",
        "2hr",
        "1dy",
        "1wk",
        "1hr 30mt 15sc",
        "2dy 4hr",
        "60",         # raw seconds
        "500ms",      # invalid unit test
        "0sc",        # boundary below minimum test
    ]

    for test in test_cases:
        try:
            parsed = parse_time_token(test)
            human_repr = format_human_duration(parsed)
            print(f"[*] Input: '{test:<15}' -> {parsed:>7d} seconds  ({human_repr})")
        except ValueError as err:
            print(f"[!] Input: '{test:<15}' -> REJECTED ({err})")

    print("=" * 65)
