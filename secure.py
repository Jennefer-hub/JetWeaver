import sys
import os
import gc
import tty
import termios
import shutil

class SecureStoryReader:
    """
    2D Terminal Input Engine with Poem / Multi-Line Support:
    - [Alt+Enter] or [Ctrl+N]: Inserts manual newline for stanzas/poem structure.
    - [Enter]: Submits and locks in the story.
    - [Arrow Keys]: Left/Right cursor movement, Up/Down line jumping.
    - [Ctrl+R]: Toggle cleartext reveal / asterisk hide.
    - Memory zeroization upon completion.
    """

    @staticmethod
    def enter_alternate_screen():
        """Switches terminal to isolated alternate screen buffer."""
        sys.stdout.write("\033[?1049h\033[2J\033[H")
        sys.stdout.flush()

    @staticmethod
    def exit_alternate_screen():
        """Restores main screen buffer and cleans terminal state."""
        sys.stdout.write("\033[?1049l")
        sys.stdout.flush()

    @staticmethod
    def _render_viewport(header: str, prefix: str, buffer: bytearray, cursor_pos: int, is_revealed: bool):
        """
        Renders the static header, handles manual line breaks (\n) and terminal column wrapping,
        then positions the terminal cursor at the exact 2D coordinate.
        """
        cols, _ = shutil.get_terminal_size((80, 24))
        prefix_len = len(prefix)
        usable_width = max(20, cols - prefix_len - 2)

        # Decode or mask
        if is_revealed:
            display_chars = [chr(b) if (32 <= b <= 126 or b == 10) else "?" for b in buffer]
        else:
            display_chars = ["\n" if b == 10 else "*" for b in buffer]

        # Break text into paragraphs by manual \n, then word/character-wrap each
        full_text = "".join(display_chars)
        raw_paragraphs = full_text.split("\n")

        visual_rows = []
        cursor_row = 0
        cursor_col = 0
        char_counter = 0
        cursor_located = False

        for p_idx, para in enumerate(raw_paragraphs):
            para_len = len(para)
            if not para:
                # Blank line (empty stanza)
                if not cursor_located and char_counter == cursor_pos:
                    cursor_row = len(visual_rows)
                    cursor_col = 0
                    cursor_located = True
                visual_rows.append("")
            else:
                # Wrap long paragraphs across usable_width
                for i in range(0, max(1, para_len), usable_width):
                    chunk = para[i : i + usable_width]
                    chunk_len = len(chunk)
                    if not cursor_located and char_counter <= cursor_pos <= char_counter + chunk_len:
                        cursor_row = len(visual_rows)
                        cursor_col = cursor_pos - char_counter
                        cursor_located = True
                    visual_rows.append(chunk)
                    char_counter += chunk_len

            # Account for the \n delimiter between paragraphs
            if p_idx < len(raw_paragraphs) - 1:
                if not cursor_located and cursor_pos == char_counter:
                    # Cursor is sitting at the very end of this line right before \n
                    cursor_row = len(visual_rows) - 1
                    cursor_col = len(visual_rows[-1]) if visual_rows else 0
                    cursor_located = True
                char_counter += 1

        if not cursor_located:
            cursor_row = max(0, len(visual_rows) - 1)
            cursor_col = len(visual_rows[-1]) if visual_rows else 0

        # Draw to terminal
        header_lines = header.split("\n")
        start_row = len(header_lines) + 1

        out = ["\033[H"]
        for h_line in header_lines:
            out.append(f"{h_line}\033[K\n")

        for idx, row_text in enumerate(visual_rows):
            p = prefix if idx == 0 else (" " * prefix_len)
            out.append(f"{p}{row_text}\033[K\n")

        out.append("\033[J")

        # Position hardware cursor
        target_row = start_row + cursor_row
        target_col = prefix_len + cursor_col + 1
        out.append(f"\033[{target_row};{target_col}H")

        sys.stdout.write("".join(out))
        sys.stdout.flush()

    @staticmethod
    def read_story(
        header: str = (
            "[SECURE TERMINAL]\n"
            "Controls: [Alt+Enter / Ctrl+N] New Stanza/Line | [Arrows] Navigate\n"
            "          [Ctrl+R] Peek/Hide Text              | [Enter] Submit Story"
        ),
        line_prefix: str = "> "
    ) -> bytearray:
        """
        Interactive multi-line poem/text editor inside an isolated memory buffer.
        """
        SecureStoryReader.enter_alternate_screen()

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        buffer = bytearray()
        cursor_pos = 0
        is_revealed = False

        try:
            tty.setcbreak(fd)
            SecureStoryReader._render_viewport(header, line_prefix, buffer, cursor_pos, is_revealed)

            while True:
                raw_bytes = os.read(fd, 32)
                if not raw_bytes:
                    continue

                # 1. Alt+Enter detection (\x1b\r or \x1b\n) -> Insert Line Break
                if raw_bytes in (b"\x1b\r", b"\x1b\n"):
                    buffer.insert(cursor_pos, 10)  # ASCII 10 = '\n'
                    cursor_pos += 1
                    SecureStoryReader._render_viewport(header, line_prefix, buffer, cursor_pos, is_revealed)
                    continue

                # 2. ANSI Escape Sequences (Arrows, Home, End, Delete)
                if raw_bytes.startswith(b"\x1b") and len(raw_bytes) > 1:
                    # Left Arrow
                    if raw_bytes in (b"\x1b[D", b"\x1bOD"):
                        if cursor_pos > 0:
                            cursor_pos -= 1
                    # Right Arrow
                    elif raw_bytes in (b"\x1b[C", b"\x1bOC"):
                        if cursor_pos < len(buffer):
                            cursor_pos += 1
                    # Up Arrow
                    elif raw_bytes in (b"\x1b[A", b"\x1bOA"):
                        # Find previous line start
                        prev_newline = buffer.rfind(b"\n", 0, cursor_pos)
                        if prev_newline != -1:
                            line_before_prev = buffer.rfind(b"\n", 0, prev_newline)
                            prev_line_start = 0 if line_before_prev == -1 else line_before_prev + 1
                            offset = cursor_pos - (prev_newline + 1)
                            cursor_pos = min(prev_newline, prev_line_start + offset)
                        else:
                            cursor_pos = 0
                    # Down Arrow
                    elif raw_bytes in (b"\x1b[B", b"\x1bOB"):
                        next_newline = buffer.find(b"\n", cursor_pos)
                        if next_newline != -1:
                            curr_line_start = buffer.rfind(b"\n", 0, cursor_pos)
                            curr_line_start = 0 if curr_line_start == -1 else curr_line_start + 1
                            offset = cursor_pos - curr_line_start
                            after_next = buffer.find(b"\n", next_newline + 1)
                            target_end = len(buffer) if after_next == -1 else after_next
                            cursor_pos = min(target_end, next_newline + 1 + offset)
                        else:
                            cursor_pos = len(buffer)
                    # Home Key
                    elif raw_bytes in (b"\x1b[H", b"\x1bOH", b"\x1b[1~"):
                        curr_line_start = buffer.rfind(b"\n", 0, cursor_pos)
                        cursor_pos = 0 if curr_line_start == -1 else curr_line_start + 1
                    # End Key
                    elif raw_bytes in (b"\x1b[F", b"\x1bOF", b"\x1b[4~"):
                        next_newline = buffer.find(b"\n", cursor_pos)
                        cursor_pos = len(buffer) if next_newline == -1 else next_newline
                    # Forward Delete
                    elif raw_bytes == b"\x1b[3~":
                        if cursor_pos < len(buffer):
                            del buffer[cursor_pos]

                    SecureStoryReader._render_viewport(header, line_prefix, buffer, cursor_pos, is_revealed)
                    continue

                # 3. Standard character and control key processing
                for b in raw_bytes:
                    # Enter key -> Submit story
                    if b in (10, 13):
                        SecureStoryReader._render_viewport(header, line_prefix, buffer, len(buffer), is_revealed=False)
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        return buffer

                    # Ctrl+N (ASCII 14) -> Alternative Line Break hotkey
                    elif b == 14:
                        buffer.insert(cursor_pos, 10)
                        cursor_pos += 1

                    # Ctrl+R (ASCII 18) -> Toggle Peek/Hide
                    elif b == 18:
                        is_revealed = not is_revealed

                    # Backspace
                    elif b in (127, 8):
                        if cursor_pos > 0:
                            del buffer[cursor_pos - 1]
                            cursor_pos -= 1

                    # Ctrl+C -> Abort
                    elif b == 3:
                        raise KeyboardInterrupt

                    # Printable ASCII characters (Space 32 through ~ 126)
                    elif 32 <= b <= 126:
                        buffer.insert(cursor_pos, b)
                        cursor_pos += 1

                SecureStoryReader._render_viewport(header, line_prefix, buffer, cursor_pos, is_revealed)

        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            SecureStoryReader.exit_alternate_screen()

    @staticmethod
    def zeroize(buf: bytearray):
        """Overwrites bytearray buffer with 0x00 null bytes in RAM."""
        if isinstance(buf, bytearray):
            for i in range(len(buf)):
                buf[i] = 0
            del buf
            gc.collect()

def main():
    print("[*] Testing Multi-Line Poem Input Subsystem...")
    input("Press Enter to test...")

    story_buf = SecureStoryReader.read_story()

    import hashlib
    digest = hashlib.sha256(story_buf).hexdigest()
    length = len(story_buf)

    # Wipe buffer immediately
    SecureStoryReader.zeroize(story_buf)

    print("\n" + "=" * 60)
    print("   INPUT TEST SUCCESSFUL")
    print("=" * 60)
    print(f"Captured Byte Length : {length}")
    print(f"Cryptographic Hash   : {digest}")
    print("Zero-Trace Status    : Buffer scrubbed from RAM. No scrollback traces.")
    print("=" * 60)

if __name__ == "__main__":
    main()
