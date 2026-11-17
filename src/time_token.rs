use regex::Regex;

pub const DEFAULT_MIN_SEC: u64 = 3;
pub const DEFAULT_MAX_SEC: u64 = 604_800; // 1 week

/// Multiplies a unit identifier to its equivalent duration in seconds.
fn unit_multiplier(unit: &str) -> Option<u64> {
    match unit {
        "sc" | "s" | "sec" => Some(1),
        "mt" | "m" | "min" => Some(60),
        "hr" | "h" => Some(3_600),
        "dy" | "d" | "day" => Some(86_400),
        "wk" | "w" | "week" => Some(604_800),
        _ => None,
    }
}

/// Validates that total duration falls within allowable bounds.
fn validate_bounds(total_sec: u64, min_sec: u64, max_sec: u64) -> Result<u64, String> {
    if total_sec < min_sec {
        return Err(format!(
            "Duration too short ({}s). Minimum allowed is {}s.",
            total_sec, min_sec
        ));
    }
    if total_sec > max_sec {
        return Err(format!(
            "Duration exceeds maximum ({}s). Maximum allowed is {}s (1wk).",
            total_sec, max_sec
        ));
    }
    Ok(total_sec)
}

/// Parses single, compound, or raw numeric time strings into total seconds.
///
/// Supported formats:
/// - Single unit: "45sc", "10mt", "2hr", "1dy", "1wk"
/// - Compound units: "1hr 30mt 15sc", "2dy 4hr"
/// - Raw integer fallback: "60", "10"
pub fn parse_time_token(time_str: &str, min_sec: u64, max_sec: u64) -> Result<u64, String> {
    let clean = time_str.trim().to_lowercase();
    if clean.is_empty() {
        return Err("Time input cannot be empty.".to_string());
    }

    // Case A: Pure integer seconds string (e.g. "60", "120")
    if clean.chars().all(|c| c.is_ascii_digit()) {
        let val = clean
            .parse::<u64>()
            .map_err(|_| "Integer value overflowed 64-bit integer.".to_string())?;
        return validate_bounds(val, min_sec, max_sec);
    }

    // Case B: Tokenized input using regex (e.g. "1hr 30mt", "45sc")
    let re = Regex::new(r"(\d+)\s*([a-zA-Z]+)").unwrap();
    let matches: Vec<(u64, String, String)> = re
        .captures_iter(&clean)
        .filter_map(|cap| {
            let val_str = cap.get(1)?.as_str();
            let unit_str = cap.get(2)?.as_str().to_string();
            let full_match = cap.get(0)?.as_str().to_string();
            let val = val_str.parse::<u64>().ok()?;
            Some((val, unit_str, full_match))
        })
        .collect();

    if matches.is_empty() {
        return Err(format!(
            "Invalid time format: '{}'. Expected format like '30sc', '5mt', '2hr', or '1wk'.",
            time_str
        ));
    }

    // Guard: Ensure every non-whitespace character was matched
    let mut reconstructed = String::new();
    for (val, unit, _) in &matches {
        reconstructed.push_str(&format!("{}{}", val, unit));
    }
    let stripped_clean: String = clean.chars().filter(|c| !c.is_whitespace()).collect();
    if reconstructed != stripped_clean {
        return Err(format!(
            "Unrecognized characters in time string: '{}'",
            time_str
        ));
    }

    let mut total_sec: u64 = 0;
    for (val, unit, _) in matches {
        match unit_multiplier(&unit) {
            Some(mult) => {
                let segment = val
                    .checked_mul(mult)
                    .ok_or_else(|| "Arithmetic overflow during duration calculation.".to_string())?;
                total_sec = total_sec
                    .checked_add(segment)
                    .ok_or_else(|| "Arithmetic overflow during duration calculation.".to_string())?;
            }
            None => {
                return Err(format!(
                    "Unknown time unit '{}'. Supported units: sc, s, sec, mt, m, min, hr, h, dy, d, day, wk, w, week",
                    unit
                ));
            }
        }
    }

    validate_bounds(total_sec, min_sec, max_sec)
}

/// Converts total seconds back into a formatted human-readable string (e.g. "1hr 30mt 15sc").
pub fn format_human_duration(seconds: u64) -> String {
    let weeks = seconds / 604_800;
    let mut rem = seconds % 604_800;
    let days = rem / 86_400;
    rem %= 86_400;
    let hours = rem / 3_600;
    rem %= 3_600;
    let minutes = rem / 60;
    let secs = rem % 60;

    let mut parts = Vec::new();
    if weeks > 0 {
        parts.push(format!("{}wk", weeks));
    }
    if days > 0 {
        parts.push(format!("{}dy", days));
    }
    if hours > 0 {
        parts.push(format!("{}hr", hours));
    }
    if minutes > 0 {
        parts.push(format!("{}mt", minutes));
    }
    if secs > 0 || parts.is_empty() {
        parts.push(format!("{}sc", secs));
    }

    parts.join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_single_units() {
        assert_eq!(parse_time_token("45sc", 3, 604800).unwrap(), 45);
        assert_eq!(parse_time_token("10mt", 3, 604800).unwrap(), 600);
        assert_eq!(parse_time_token("2hr", 3, 604800).unwrap(), 7200);
        assert_eq!(parse_time_token("1dy", 3, 604800).unwrap(), 86400);
        assert_eq!(parse_time_token("1wk", 3, 604800).unwrap(), 604800);
    }

    #[test]
    fn test_compound_units() {
        assert_eq!(parse_time_token("1hr 30mt 15sc", 3, 604800).unwrap(), 5415);
        assert_eq!(parse_time_token("2dy 4hr", 3, 604800).unwrap(), 187200);
    }

    #[test]
    fn test_raw_seconds() {
        assert_eq!(parse_time_token("60", 3, 604800).unwrap(), 60);
    }

    #[test]
    fn test_rejection_of_invalid_units() {
        assert!(parse_time_token("500ms", 3, 604800).is_err());
        assert!(parse_time_token("10xyz", 3, 604800).is_err());
    }

    #[test]
    fn test_bounds_enforcement() {
        assert!(parse_time_token("0sc", 3, 604800).is_err());
        assert!(parse_time_token("2sc", 3, 604800).is_err());
        assert!(parse_time_token("2wk", 3, 604800).is_err());
    }

    #[test]
    fn test_human_formatting() {
        assert_eq!(format_human_duration(5415), "1hr 30mt 15sc");
        assert_eq!(format_human_duration(86400), "1dy");
        assert_eq!(format_human_duration(45), "45sc");
    }
}
