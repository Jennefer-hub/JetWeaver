use crossterm::{
    cursor::{self, MoveTo},
    event::{self, Event, KeyCode, KeyEventKind, KeyModifiers},
    execute,
    terminal::{self, Clear, ClearType, EnterAlternateScreen, LeaveAlternateScreen},
};
use sha2::{Digest, Sha512};
use std::io::{self, stdout, Write};
use zeroize::Zeroize;

struct TerminalGuard;

impl TerminalGuard {
    fn enter() -> io::Result<Self> {
        terminal::enable_raw_mode()?;
        let mut out = stdout();
        execute!(out, EnterAlternateScreen, Clear(ClearType::All), cursor::Show)?;
        Ok(Self)
    }
}

impl Drop for TerminalGuard {
    fn drop(&mut self) {
        let mut out = stdout();
        let _ = execute!(out, Clear(ClearType::All), cursor::Show, LeaveAlternateScreen);
        let _ = out.flush();
        let _ = terminal::disable_raw_mode();
    }
}

pub struct SecureStoryReader;

impl SecureStoryReader {
    fn render_viewport(
        header: &str,
        prefix: &str,
        buffer: &[u8],
        cursor_pos: usize,
        is_revealed: bool,
    ) -> io::Result<usize> {
        let (cols_u16, _) = terminal::size().unwrap_or((80, 24));
        let cols = cols_u16 as usize;
        let prefix_len = prefix.len();
        let usable_width = cols.saturating_sub(prefix_len + 2).max(20);

        let display_chars: Vec<char> = buffer
            .iter()
            .map(|&b| {
                if b == b'\n' {
                    '\n'
                } else if is_revealed {
                    if (32..=126).contains(&b) {
                        b as char
                    } else {
                        '?'
                    }
                } else {
                    '*'
                }
            })
            .collect();

        let full_text: String = display_chars.into_iter().collect();
        let raw_paragraphs: Vec<&str> = full_text.split('\n').collect();

        let mut visual_rows: Vec<String> = Vec::new();
        let mut cursor_row = 0;
        let mut cursor_col = 0;
        let mut char_counter = 0;
        let mut cursor_located = false;

        for (p_idx, &para) in raw_paragraphs.iter().enumerate() {
            let para_chars: Vec<char> = para.chars().collect();
            let para_len = para_chars.len();

            if para_len == 0 {
                if !cursor_located && char_counter == cursor_pos {
                    cursor_row = visual_rows.len();
                    cursor_col = 0;
                    cursor_located = true;
                }
                visual_rows.push(String::new());
            } else {
                let mut start = 0;
                while start < para_len {
                    let end = (start + usable_width).min(para_len);
                    let chunk: String = para_chars[start..end].iter().collect();
                    let chunk_len = chunk.chars().count();

                    if !cursor_located && char_counter <= cursor_pos && cursor_pos <= char_counter + chunk_len {
                        cursor_row = visual_rows.len();
                        cursor_col = cursor_pos - char_counter;
                        cursor_located = true;
                    }

                    visual_rows.push(chunk);
                    char_counter += chunk_len;
                    start = end;
                }
            }

            if p_idx < raw_paragraphs.len() - 1 {
                if !cursor_located && cursor_pos == char_counter {
                    cursor_row = visual_rows.len().saturating_sub(1);
                    cursor_col = visual_rows.last().map(|s| s.chars().count()).unwrap_or(0);
                    cursor_located = true;
                }
                char_counter += 1;
            }
        }

        if !cursor_located {
            cursor_row = visual_rows.len().saturating_sub(1);
            cursor_col = visual_rows.last().map(|s| s.chars().count()).unwrap_or(0);
        }

        let header_lines: Vec<&str> = header.lines().collect();
        let start_row = header_lines.len();

        let mut out = stdout();
        execute!(out, MoveTo(0, 0))?;

        for h_line in &header_lines {
            execute!(out, Clear(ClearType::CurrentLine))?;
            out.write_all(h_line.as_bytes())?;
            out.write_all(b"\r\n")?;
        }

        for (idx, row_text) in visual_rows.iter().enumerate() {
            execute!(out, Clear(ClearType::CurrentLine))?;
            let p = if idx == 0 { prefix } else { &" "[..prefix_len.min(1)] };
            out.write_all(p.as_bytes())?;
            out.write_all(row_text.as_bytes())?;
            out.write_all(b"\r\n")?;
        }

        execute!(out, Clear(ClearType::FromCursorDown))?;

        let target_col = (prefix_len + cursor_col) as u16;
        let target_row = (start_row + cursor_row) as u16;
        execute!(out, MoveTo(target_col, target_row))?;
        out.flush()?;

        Ok(usable_width)
    }

    pub fn read_story() -> Result<Vec<u8>, String> {
        let _guard = TerminalGuard::enter().map_err(|e| e.to_string())?;

        let header = concat!(
            "===============================================================\r\n",
            "   PROJECT JETWEAVER: SECURE MEMORY INGESTION (RUST)\r\n",
            "   Controls: [Alt+Enter / Ctrl+N] Line Break | [Arrows] Navigate\r\n",
            "             [Ctrl+R] Peek/Hide Text         | [Enter] Submit\r\n",
            "==============================================================="
        );
        let prefix = "> ";

        let mut buffer: Vec<u8> = Vec::with_capacity(512);
        let mut cursor_pos: usize = 0;
        let mut is_revealed = false;

        Self::render_viewport(header, prefix, &buffer, cursor_pos, is_revealed)
            .map_err(|e| e.to_string())?;

        loop {
            let event = event::read().map_err(|e| e.to_string())?;

            if let Event::Key(key) = event {
                if key.kind == KeyEventKind::Release {
                    continue;
                }

                match (key.code, key.modifiers) {
                    (KeyCode::Enter, KeyModifiers::NONE) => {
                        break;
                    }
                    (KeyCode::Enter, KeyModifiers::ALT) | (KeyCode::Char('n'), KeyModifiers::CONTROL) => {
                        buffer.insert(cursor_pos, b'\n');
                        cursor_pos += 1;
                    }
                    (KeyCode::Char('r'), KeyModifiers::CONTROL) => {
                        is_revealed = !is_revealed;
                    }
                    (KeyCode::Home, _) | (KeyCode::Char('a'), KeyModifiers::CONTROL) => {
                        let prev_newline = buffer[..cursor_pos].iter().rposition(|&b| b == b'\n');
                        cursor_pos = prev_newline.map(|idx| idx + 1).unwrap_or(0);
                    }
                    (KeyCode::End, _) | (KeyCode::Char('e'), KeyModifiers::CONTROL) => {
                        let next_newline = buffer[cursor_pos..].iter().position(|&b| b == b'\n');
                        cursor_pos = next_newline.map(|idx| cursor_pos + idx).unwrap_or(buffer.len());
                    }
                    (KeyCode::Left, _) => {
                        if cursor_pos > 0 {
                            cursor_pos -= 1;
                        }
                    }
                    (KeyCode::Right, _) => {
                        if cursor_pos < buffer.len() {
                            cursor_pos += 1;
                        }
                    }
                    (KeyCode::Up, _) => {
                        if let Some(prev_nl) = buffer[..cursor_pos].iter().rposition(|&b| b == b'\n') {
                            let line_before = buffer[..prev_nl].iter().rposition(|&b| b == b'\n');
                            let line_start = line_before.map(|i| i + 1).unwrap_or(0);
                            let col_offset = cursor_pos - (prev_nl + 1);
                            cursor_pos = prev_nl.min(line_start + col_offset);
                        } else {
                            cursor_pos = 0;
                        }
                    }
                    (KeyCode::Down, _) => {
                        if let Some(next_nl) = buffer[cursor_pos..].iter().position(|&b| b == b'\n') {
                            let curr_start = buffer[..cursor_pos]
                                .iter()
                                .rposition(|&b| b == b'\n')
                                .map(|i| i + 1)
                                .unwrap_or(0);
                            let col_offset = cursor_pos - curr_start;
                            let abs_next_nl = cursor_pos + next_nl;
                            let line_after_start = abs_next_nl + 1;
                            let line_after_len = buffer[line_after_start..]
                                .iter()
                                .position(|&b| b == b'\n')
                                .unwrap_or(buffer.len() - line_after_start);
                            cursor_pos = (line_after_start + col_offset).min(line_after_start + line_after_len);
                        } else {
                            cursor_pos = buffer.len();
                        }
                    }
                    (KeyCode::Backspace, _) => {
                        if cursor_pos > 0 {
                            buffer.remove(cursor_pos - 1);
                            cursor_pos -= 1;
                        }
                    }
                    (KeyCode::Delete, _) => {
                        if cursor_pos < buffer.len() {
                            buffer.remove(cursor_pos);
                        }
                    }
                    (KeyCode::Char('c'), KeyModifiers::CONTROL) => {
                        buffer.zeroize();
                        return Err("Input cancelled by user (Ctrl+C).".to_string());
                    }
                    (KeyCode::Char(c), KeyModifiers::NONE | KeyModifiers::SHIFT) => {
                        if c.is_ascii() && !c.is_ascii_control() {
                            buffer.insert(cursor_pos, c as u8);
                            cursor_pos += 1;
                        }
                    }
                    _ => {}
                }

                Self::render_viewport(header, prefix, &buffer, cursor_pos, is_revealed)
                    .map_err(|e| e.to_string())?;
            }
        }

        Ok(buffer)
    }

    pub fn process_and_zeroize(mut story_bytes: Vec<u8>) -> [u8; 64] {
        let mut hasher = Sha512::new();
        hasher.update(&story_bytes);
        let digest = hasher.finalize();

        story_bytes.zeroize();

        let mut out = [0u8; 64];
        out.copy_from_slice(&digest);
        out
    }
}
