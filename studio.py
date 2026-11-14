import os
import sys
import json
import math
import time
import atexit
import random
import shutil
import logging
import threading
import importlib
import subprocess
import re
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# Windows consoles default to legacy encodings; braille/box art needs UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Enable Windows ANSI Escape Sequences & Verify Color Support
ANSI_SUPPORTED = True
if os.name == 'nt':
    ANSI_SUPPORTED = (os.system('') == 0)


def disable_quickedit():
    """Windows 'QuickEdit' freezes a console the moment you click it (the app
    looks stuck until you press Enter). Turn it off for this run and restore
    the original console mode on exit."""
    if os.name != "nt" or not sys.stdin or not sys.stdin.isatty():
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-10)                # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if not k32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        original = mode.value
        # clear ENABLE_QUICK_EDIT_MODE (0x40), set ENABLE_EXTENDED_FLAGS (0x80)
        k32.SetConsoleMode(handle, (original | 0x0080) & ~0x0040)
        atexit.register(lambda: k32.SetConsoleMode(handle, original))
    except Exception:
        pass


disable_quickedit()

# CLI FLAGS:  --no-anim   --theme=classic|solar|kryptonite
ANIM = ANSI_SUPPORTED and sys.stdout.isatty()
THEME_FLAG = None
ARGS = []
for _a in sys.argv[1:]:
    if _a == "--no-anim":
        ANIM = False
    elif _a.startswith("--theme="):
        THEME_FLAG = _a.split("=", 1)[1].strip().lower()
    else:
        ARGS.append(_a)

# AUTONOMOUS DIRECTORY DETECTION & SELF-STRUCTURING
ROOT_DIR = Path(__file__).resolve().parent
LOG_DIR = ROOT_DIR / "logs"
OUTPUT_DIR = ROOT_DIR / "output"
SIGNED_DIR = OUTPUT_DIR / "signed"
PROFILE_DIR = ROOT_DIR / "profiles"
DECODED_DIR = ROOT_DIR / "BASE"
DEP_DIR = ROOT_DIR / "dependencies"

for _d in (LOG_DIR, OUTPUT_DIR, SIGNED_DIR, PROFILE_DIR, DEP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

ENV_PATH = ROOT_DIR / "pipeline_settings.env"
TIMINGS_PATH = PROFILE_DIR / "timings.json"

logging.basicConfig(
    filename=LOG_DIR / "pipeline.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# KRYPTONIAN PALETTE SYSTEM
if ANSI_SUPPORTED:
    C_KRYPTON_BLUE = "\033[38;5;33m"
    C_DEEP_BLUE    = "\033[38;5;25m"
    C_CRIMSON      = "\033[38;5;196m"
    C_GOLD         = "\033[38;5;220m"
    C_ICE          = "\033[97m"
    C_CYAN         = "\033[96m"
    C_STEEL        = "\033[90m"
    C_SUCCESS      = "\033[92m"
    C_BOLD         = "\033[1m"
    C_RESET        = "\033[0m"
    CLR            = "\033[K"
else:
    C_KRYPTON_BLUE = C_DEEP_BLUE = C_CRIMSON = C_GOLD = ""
    C_ICE = C_CYAN = C_STEEL = C_SUCCESS = C_BOLD = C_RESET = CLR = ""

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def fg(n):
    return f"\033[38;5;{n}m" if ANSI_SUPPORTED else ""


def bg(n):
    return f"\033[48;5;{n}m" if ANSI_SUPPORTED else ""


def vlen(s):
    """Visible length of a string (ANSI codes ignored)."""
    return len(ANSI_RE.sub("", s))


def clip(s, n):
    return s if len(s) <= n else "…" + s[-(n - 1):]


def term_cols():
    return shutil.get_terminal_size((100, 40)).columns


# DYNAMIC THEMES
#  R = cape, B = suit, G = emblem, bar = main gradient (progress/borders/headings)
THEMES = {
    "classic": {
        "R": [88, 124, 160, 196, 203, 196, 160, 124],
        "B": [18, 25, 32, 33, 39, 75, 39, 33, 32, 25],
        "G": [136, 178, 220, 226, 229, 226, 220, 178],
        "bar": [21, 27, 33, 63, 99, 135, 171, 205, 196, 202, 208, 214, 220, 226],
        "wm_top": [196, 202, 208, 214, 220, 226],
        "wm_bottom": [21, 27, 33, 39, 45, 51, 87],
        "glow": 51, "flash": 231,
        "trail": [226, 220, 214, 208, 202, 196, 160, 124, 88, 240],
        "confetti": [33, 39, 196, 202, 220, 226, 231],
    },
    "solar": {
        "R": [130, 166, 202, 208, 214, 208, 202, 166],
        "B": [94, 136, 178, 220, 226, 229, 226, 220, 178, 136],
        "G": [220, 226, 229, 231, 229, 226],
        "bar": [130, 166, 202, 208, 214, 220, 226, 229, 231],
        "wm_top": [229, 226, 220, 214, 208, 202],
        "wm_bottom": [166, 202, 208, 214, 220, 226],
        "glow": 231, "flash": 15,
        "trail": [231, 229, 226, 220, 214, 208, 202, 166, 130, 94],
        "confetti": [202, 208, 214, 220, 226, 229, 231],
    },
    "kryptonite": {
        "R": [22, 28, 34, 40, 46, 40, 34, 28],
        "B": [22, 28, 34, 35, 41, 48, 41, 35, 34, 28],
        "G": [70, 76, 82, 118, 154, 118, 82, 76],
        "bar": [22, 28, 34, 40, 46, 82, 118, 154, 190],
        "wm_top": [157, 121, 118, 82, 46],
        "wm_bottom": [22, 28, 34, 40, 46, 82],
        "glow": 118, "flash": 231,
        "trail": [231, 157, 118, 82, 46, 40, 34, 28, 22, 236],
        "confetti": [28, 34, 46, 82, 118, 154, 231],
    },
}
THEME = THEMES["classic"]


def apply_theme(name):
    global THEME
    THEME = THEMES.get((name or "classic").lower(), THEMES["classic"])


def grad_pick(grad, phase):
    idx = int((math.sin(phase) + 1) / 2 * (len(grad) - 1) + 0.5)
    return grad[idx]


def grad_color(stops, pos):
    pos = max(0.0, min(1.0, pos))
    return stops[int(pos * (len(stops) - 1) + 0.5)]


def grad_text(text, stops=None, shift=None, bold=False):
    """Per-character gradient. shift=None -> static; a number -> flowing."""
    stops = stops or THEME["bar"]
    n = max(len(text) - 1, 1)
    out = []
    for i, ch in enumerate(text):
        if ch == " ":
            out.append(ch)
            continue
        pos = i / n
        if shift is not None:
            pos = 1 - abs(2 * ((pos + shift) % 1.0) - 1)      # triangle wave
        out.append(f"{fg(grad_color(stops, pos))}{ch}")
    return (C_BOLD if bold else "") + "".join(out) + C_RESET


def tag(text, bgc, fgc=231):
    return f"{bg(bgc)}{fg(fgc)}{C_BOLD} {text} {C_RESET}"


FUNNY_QUOTES = [
    "\"Faster than a speeding bullet, able to bypass rotation matrices in a single bound.\"",
    "\"It's a bird! It's a plane! No, it's just your CPU encoding HEVC at 60fps.\"",
    "\"Debugging live wallpapers is 90% black screens and 10% pure architectural precision.\"",
    "\"Look, up in the sky! It's Superman! Wait, no, that's just an Oppo battery warning.\"",
    "\"Even the Man of Steel would take a coffee break while compiling Smali bytecode.\"",
    "\"Turning raw pixels into elite mobile art since day one.\""
]

PORTRAIT_ART = [
    ("S", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣠⠴⣖⣿⣿⣽⣶⣦⣀"),
    ("S", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⡾⠋⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣦⣄"),
    ("S", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣷⣀⠀⢩⣫⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷"),
    ("S", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿⠈⢳⣸⣿⣿⣿⣿⣿⣿⠿⠛⠉⣿⣿"),
    ("B", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿⠀⠀⡙⠻⣿⡿⠀⠀⠀⠀⠀⠀⣿⡇"),
    ("B", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣤⣿⡿⠀⠀⠉⠛⠛⢁⠀⠀⠀⠀⠀⠀⢻⡇"),
    ("B", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣯⣽⡇⠈⢻⢷⣶⣦⠝⠀⡰⡶⣶⡿⣗⢸⢻"),   # eye row (heat vision)
    ("B", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢹⣻⡄⠀⠀⠀⠁⠘⠀⠀⡇⠀⠈⠀⠀⢸⣿"),
    ("B", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⡇⠀⠀⠀⠀⠀⠀⠀⣻⡆⠀⠀⠀⢸⡾"),
    ("R", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⡇⠀⠀⠀⠀⡀⢉⣉⠉⢁⠀⠀⠀⢸"),
    ("R", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣷⡄⠀⠀⠀⠀⠀⠉⠝⠉⠀⠀⠀⡾"),
    ("R", "⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⢸⡇⢻⣄⠀⠀⠀⠀⠀⠀⠀⠀⢀⣾⣧"),
    ("G", "⠀⠀⠀⠀⠀⣠⠴⠚⠉⠁⠹⡒⢲⡀⠀⠀⠀⢀⣸⠃⠀⠹⣷⡀⠀⠀⠰⠀⠀⢠⡿⠁⣽"),
    ("G", "⠀⠀⠀⢰⠞⠁⠀⠀⠀⠀⠀⠙⡄⢳⣤⠴⠒⠋⠀⠀⠀⠀⢌⠻⠷⠶⠾⠿⠿⠿⡇⠀⢹⠳⣤⡄⡼⠓⢢⡜⠉⠓⠒⠦⣤⡄"),
    ("G", "⠀⠀⠀⢸⠀⢘⣦⣀⠀⠀⠀⠀⠘⣆⢳⡀⠀⠀⠀⠀⠀⠀⠈⢧⡀⠀⠀⠀⠀⣰⠃⠀⠈⠀⠀⠁⢀⡞⠁⠀⠀⠀⠀⣀⡇"),
    ("G", "⠀⢀⣠⠾⠚⠋⠀⠈⠙⠦⣀⠀⠀⠘⡆⢻⡄⠀⠀⠀⠀⠀⠀⠀⠳⠀⠀⠀⢰⠃⠀⠀⠀⠀⢰⠃⢠⠞⠀⠀⠀⢀⣤⠞⠛⠳⢤⣀"),
    ("R", "⠚⠋⠀⠀⠀⠀⠀⠀⠀⠀⠈⠛⠛⠛⠛⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⠙⠛⠛⠛⠛⠛⠛⠛⠛⠛⠒⠛⠀⠀⠀⠀⠀⠈⠛⢦⣄"),
    ("R", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣠⣤⣤⣤⣤⣤⣤⣤⣦⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣀⣀⣀⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠻⣦⡀"),
    ("R", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡴⠋⡠⢶⡆⠀⠀⠀⢀⣠⠤⠶⠶⠶⠶⠤⣄⡀⠀⠀⢶⡒⣶⠆⠀⣈⠳⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠻⣆"),
    ("R", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⠞⢁⡜⢡⠏⠀⠀⠀⡴⠋⠀⠀⠀⠀⠀⠀⠀⠀⠙⢦⣀⣀⣛⣁⣀⡴⠋⢧⠘⣦⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘"),
    ("R", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⣼⠃⢀⠞⠀⡟⠀⠀⠀⡞⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⢣⡈⢷"),
    ("R", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠳⣌⠳⣤⡇⠀⠀⠀⠙⠦⣀⣀⡀⠀⠀⣀⣀⣀⣀⡤⠤⢤⣀⠀⠀⠀⠀⢀⡴⠋⣵⠟"),
    ("R", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠳⣌⠁⠀⠀⠀⠀⠀⠀⠉⠉⠉⠉⠉⠉⠉⠀⠀⠀⠀⠈⠙⢢⡀⡠⠊⢠⡞⠁"),
    ("B", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠳⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⢀⡴⠉"),
    ("B", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠱⢄⠀⢶⡤⢄⣀⣀⡤⠤⠴⠶⠶⠤⣄⠀⠀⠀⠀⡴⠋"),
    ("B", "⠀⠀⠀⠀⠀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠳⣄⡉⠢⠤⠴⠦⢄⠀⠀⠀⠀⢀⡇⠀⣠⠞"),
    ("B", "⠀⠀⢐⣲⣯⡿⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠛⢦⡀⠀⢠⣞⣀⣀⣀⡤⠞⢀⡜⠁"),
    ("B", "⠀⠀⠈⠙⠻⣜⣴⡆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⢦⡀⢶⡒⠒⣶⣄⡴⠋"),
    ("B", "⠀⠀⠀⠀⠀⠀⠉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⢦⡓⠞⣳⠏"),
    ("B", "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⠟⠁"),
]
EYE_ROW = 6
SUPER_ART = [
    r" ____  _   _ ____  _____ ____  ",
    r"/ ___|| | | |  _ \| ____|  _ \ ",
    r"\___ \| | | | |_) |  _| | |_) |",
    r" ___) | |_| |  __/| |___|  _ < ",
    r"|____/ \___/|_|   |_____|_| \_\ ",
]
PROTOCOL_ART = [
    r" ____  ____   ___ _____ ___   ____ ___  _     ",
    r"|  _ \|  _ \ / _ \_   _/ _ \ / ___/ _ \| |    ",
    r"| |_) | |_) | | | || || | | | |  | | | | |    ",
    r"|  __/|  _ <| |_| || || |_| | |__| |_| | |___ ",
    r"|_|   |_| \_\\___/ |_| \___/ \____\___/|_____|",
]
WORDMARK_ART = SUPER_ART + PROTOCOL_ART

# ----------------------------------------------------------------------------
# ANIMATION ENGINE
# ----------------------------------------------------------------------------
@contextmanager
def hidden_cursor():
    if ANIM:
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
    try:
        yield
    finally:
        if ANIM:
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()


def animate_block(frame_fn, frames, delay):
    """Redraw a multi-line block in place; static final frame if animation is off
    or the terminal is too short to redraw safely."""
    first = frame_fn(0)
    n = len(first)
    rows = shutil.get_terminal_size((100, 40)).lines
    if not ANIM or n + 2 > rows:
        print("\n".join(frame_fn(frames - 1)))
        return
    with hidden_cursor():
        sys.stdout.write("\n".join(l + CLR for l in first) + "\n")
        for f in range(1, frames):
            time.sleep(delay)
            sys.stdout.write(f"\033[{n}A" + "\n".join(l + CLR for l in frame_fn(f)) + "\n")
            sys.stdout.flush()


def typewrite(text, delay=0.008):
    if not ANIM:
        print(text)
        return
    for tok in re.split(r"(\x1b\[[0-9;]*m)", text):
        if tok.startswith("\x1b"):
            sys.stdout.write(tok)
        else:
            for ch in tok:
                sys.stdout.write(ch)
                sys.stdout.flush()
                time.sleep(delay)
    sys.stdout.write("\n")


def sky(row, t, n):
    """Twinkling starfield trailing off to the right of the portrait."""
    s = []
    for c in range(n):
        v = (c * 13 + row * 7 + (t // 3) * 5) % 23
        if v == 0:
            s.append(f"{fg(250)}.")
        elif v == 11:
            s.append(f"{fg(grad_pick(THEME['G'], c + t * 0.3))}*")
        elif v == 17:
            s.append(f"{fg(grad_pick(THEME['B'], c + t * 0.2))}+")
        else:
            s.append(" ")
    return "".join(s) + C_RESET


def portrait_frame(t):
    cols = term_cols()
    reveal = t * 3
    beam_phase = t % 24
    heat = reveal >= len(PORTRAIT_ART) and 14 <= beam_phase < 20
    out = []
    for row, (kind, art) in enumerate(PORTRAIT_ART):
        if row >= reveal:
            out.append("")
            continue
        if row == EYE_ROW and heat:
            beam_len = min(max(0, cols - 12 - len(art)), (beam_phase - 13) * 8)
            out.append(f"          {fg(196)}{C_BOLD}{art}{C_RESET}"
                       f"{fg(203)}{C_BOLD}{'=' * beam_len}{C_RESET}")
            continue
        color = C_STEEL if kind == "S" else fg(grad_pick(THEME[kind], row * 0.5 - t * 0.45))
        line = f"          {color}{art}{C_RESET}"
        room = min(26, cols - 12 - len(art) - 2)
        if room > 2:
            line += "  " + sky(row, t, room)
        out.append(line)
    return out


def wordmark_frame(t):
    """Gradient wordmark (red->gold / blue->cyan) with a white-hot sweep."""
    sweep = t * 3 - 8
    out = []
    for row, text in enumerate(WORDMARK_ART):
        stops = THEME["wm_top"] if row < len(SUPER_ART) else THEME["wm_bottom"]
        n = max(len(text) - 1, 1)
        buf, last = [], None
        for i, ch in enumerate(text):
            if ch == " ":
                buf.append(" ")
                continue
            d = abs(i - sweep)
            col = THEME["flash"] if d <= 1 else THEME["glow"] if d <= 4 else grad_color(stops, i / n)
            if col != last:
                buf.append(fg(col))
                last = col
            buf.append(ch)
        out.append("  " + C_BOLD + "".join(buf) + C_RESET)
    return out


def rule_line(width, shift=0.0):
    return "  " + grad_text("━" * width, THEME["bar"], shift=shift)


def flight_bar(pos, t, width=36):
    """One-line Superman flying through a starfield (used for the victory lap)."""
    cells = []
    for x in range(width):
        if (x + t) % 7 == 0:
            cells.append((".", 240))
        elif (x + 2 * t) % 13 == 0:
            cells.append(("*", 250))
        else:
            cells.append((" ", None))
    for k, col in enumerate(THEME["trail"]):
        x = pos - 3 - k
        if 0 <= x < width:
            cells[x] = ("=" if k < 5 else "-" if k < 8 else ".", col)
    for dx, ch, col in ((-2, "=", 39), (-1, "S", 220), (0, ">", 196)):
        x = pos + dx
        if 0 <= x < width:
            cells[x] = (ch, col)
    buf = [f"{fg(col)}{ch}" if col is not None else ch for ch, col in cells]
    return f"{C_STEEL}|{C_RESET}{''.join(buf)}{C_RESET}{C_STEEL}|{C_RESET}"


def victory_flight():
    if not ANIM:
        return
    width = max(20, min(60, term_cols() - 8))
    with hidden_cursor():
        for t in range((width + 14) // 2 + 2):
            sys.stdout.write(f"\r  {flight_bar(t * 2, t, width)}{CLR}")
            sys.stdout.flush()
            time.sleep(0.02)
        sys.stdout.write("\r" + CLR)
        sys.stdout.flush()


def confetti_frame(t, width=None, height=7):
    width = width or max(20, min(74, term_cols() - 6))
    cols = THEME["confetti"]
    chars = "*+.o"
    out = []
    for y in range(height):
        buf = []
        for x in range(width):
            if (x * 31 + (y - t) * 17) % 23 == 0:
                buf.append(f"{fg(cols[(x * 5 + y * 3 + t) % len(cols)])}{chars[(x + y + t) % len(chars)]}")
            else:
                buf.append(" ")
        out.append("  " + "".join(buf) + C_RESET)
    return out


def panel_lines(title, rows, t=0, width=None):
    """Gradient-bordered box whose border colours flow as t increases."""
    width = width or min(78, term_cols() - 4)
    inner = width - 2
    stops = THEME["bar"]
    shift = t * 0.04

    top_plain = "╔═ " + title + " " + "═" * max(0, inner - len(title) - 3) + "╗"
    bot_plain = "╚" + "═" * inner + "╝"

    def colour(plain, title_span=None):
        n = max(len(plain) - 1, 1)
        buf = []
        for i, ch in enumerate(plain):
            if title_span and title_span[0] <= i < title_span[1]:
                buf.append(f"{C_BOLD}{fg(231)}{ch}")
            else:
                pos = 1 - abs(2 * ((i / n + shift) % 1.0) - 1)
                buf.append(f"{fg(grad_color(stops, pos))}{ch}")
        return "".join(buf) + C_RESET

    lines = ["  " + colour(top_plain, (3, 3 + len(title)))]
    for r, row in enumerate(rows):
        pos = 1 - abs(2 * (((r % 7) / 7 + shift) % 1.0) - 1)
        b = fg(grad_color(stops, pos))
        pad = max(0, inner - 2 - vlen(row))
        lines.append(f"  {b}║{C_RESET} {row}{' ' * pad} {b}║{C_RESET}")
    lines.append("  " + colour(bot_plain))
    return lines


def show_panel(title, rows, frames=16, delay=0.04):
    animate_block(lambda t: panel_lines(title, rows, t), frames, delay)


def section(text):
    print(f"\n  {grad_text('▰▰▰ ' + text + ' ▰▰▰', THEME['bar'], bold=True)}")


def ask(num, label, hint="", default=""):
    h = f" {C_STEEL}({hint}){C_RESET}" if hint else ""
    d = f" {C_STEEL}[{default}]{C_RESET}" if default else ""
    prompt = f"  {tag(num, 27)} {grad_text(label, THEME['bar'])}{h}{d} {fg(226)}▸{C_RESET} "
    return input(prompt).strip()


def halt(msg, extra=None):
    print(f"\n  {tag('HALT', 196, 226)} {C_CRIMSON}{msg}{C_RESET}")
    if extra:
        print(f"  {C_STEEL}{extra}{C_RESET}")
    print()


def kryptonite_alert(desc):
    msg = f"KRYPTONITE DETECTED // {desc}"
    greens = [22, 28, 34, 40, 46, 82, 118, 82, 46, 40, 34, 28]
    if ANIM:
        with hidden_cursor():
            for i in range(20):
                sys.stdout.write(f"\r  {tag('FAIL', greens[i % len(greens)], 16)} "
                                 f"{fg(greens[i % len(greens)])}{C_BOLD}{msg}{C_RESET}{CLR}")
                sys.stdout.flush()
                time.sleep(0.05)
        sys.stdout.write("\r" + CLR)
    print(f"  {tag('FAIL', 196, 226)} {C_CRIMSON}{C_BOLD}{msg}{C_RESET}")


# ----------------------------------------------------------------------------
# PROGRESS BARS
# ----------------------------------------------------------------------------
def render_bar(frac, width, t):
    """Blue->red->gold gradient bar with a travelling shimmer and a bright head."""
    frac = max(0.0, min(1.0, frac))
    grad = THEME["bar"]
    full = int(frac * width)
    shimmer = (t * 1.5) % (width + 8) - 4
    cells = []
    for i in range(width):
        if i < full or frac >= 1.0:
            col = 231 if abs(i - shimmer) < 1 else grad_color(grad, i / max(width - 1, 1))
            cells.append(f"{fg(col)}█")
        elif i == full:
            cells.append(f"{fg(THEME['flash'] if t % 6 < 3 else THEME['glow'])}▶")
        else:
            cells.append(f"{fg(238)}░")
    return "".join(cells) + C_RESET


def estimate_frac(elapsed, est):
    """Eased 'illusion' progress: climbs fast, slows down, never hits 100% early."""
    return 0.96 * (1 - math.exp(-2.5 * elapsed / max(est, 1.0)))


def fmt_eta(sec):
    sec = int(max(0, sec))
    return f"{sec // 60}:{sec % 60:02d}"


def load_timings():
    try:
        return json.loads(TIMINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_timing(key, elapsed):
    data = load_timings()
    old = data.get(key)
    data[key] = round(elapsed if old is None else 0.5 * old + 0.5 * elapsed, 2)
    try:
        TIMINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


PROGRESS_RE = re.compile(r"out_time_(?:us|ms)=(\d+)")
STAGE_TOTAL = 4
_stage_counter = 0


def run_command(cmd_list, desc, key, est=20.0, duration=None, numbered=True, fatal=True):
    """Run a tool with an animated progress bar.
    - duration given (FFmpeg): the bar is REAL, driven by ffmpeg's -progress output.
    - otherwise: eased estimate calibrated from previous runs (profiles/timings.json).
    stdin is closed so no tool can ever sit waiting for a keypress."""
    global _stage_counter
    label = "EXEC"
    if numbered:
        _stage_counter += 1
        label = f"STAGE {_stage_counter}/{STAGE_TOTAL}"
    est = load_timings().get(key, est)

    print(f"\n  {tag(label, 196, 226)} {grad_text(desc, THEME['bar'], bold=True)}")
    logging.info(f"Starting: {desc} -> {' '.join(cmd_list)}")

    state = {"frac": None, "code": None, "out": deque(maxlen=300), "err": deque(maxlen=300)}

    def _worker():
        try:
            proc = subprocess.Popen(
                cmd_list, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        except OSError as e:
            state["err"].append(f"Tool not found or not executable: {e}\n")
            state["code"] = 127
            return

        def _drain():
            for line in proc.stderr:
                state["err"].append(line)

        te = threading.Thread(target=_drain, daemon=True)
        te.start()
        for line in proc.stdout:
            state["out"].append(line)
            if duration:
                m = PROGRESS_RE.match(line)
                if m:
                    state["frac"] = min(1.0, int(m.group(1)) / 1e6 / duration)
        proc.wait()
        te.join(timeout=5)
        state["code"] = proc.returncode

    worker = threading.Thread(target=_worker, daemon=True)
    start = time.time()
    worker.start()

    width = max(10, min(40, term_cols() - 46))
    shown, t = 0.0, 0
    with hidden_cursor():
        while worker.is_alive():
            el = time.time() - start
            real = state["frac"]
            target = min(0.99, real if real is not None else estimate_frac(el, est))
            if target > shown:
                shown += (target - shown) * 0.3
            if ANIM:
                if real is not None and shown > 0.03:
                    eta = fmt_eta(el * (1 - shown) / shown)
                elif real is None and el < est:
                    eta = fmt_eta(est - el)
                else:
                    eta = "finishing"
                sys.stdout.write(
                    f"\r  {tag('EXEC', 27)} {render_bar(shown, width, t)} "
                    f"{C_BOLD}{fg(226)}{int(shown * 100):3d}%{C_RESET} "
                    f"{C_STEEL}{el:5.1f}s ETA {eta}{C_RESET}{CLR}")
                sys.stdout.flush()
                time.sleep(0.05)
            else:
                time.sleep(0.2)
            t += 1
        worker.join()

    elapsed = time.time() - start
    ok = state["code"] == 0

    if not ok:
        if ANIM:
            sys.stdout.write("\r" + CLR)
        kryptonite_alert(desc)
        logging.error(f"Error in {desc}: {''.join(state['err'])}")
        tail = list(state["err"])[-30:] or list(state["out"])[-30:]
        print(f"{C_STEEL}{''.join(tail)}{C_RESET}")
        if fatal:
            sys.exit(1)
        return False

    save_timing(key, elapsed)
    logging.info(f"Success: {desc} ({elapsed:.1f}s)")
    print(f"\r  {tag('EXEC', 34)} {render_bar(1.0, width, t)} "
          f"{C_BOLD}{C_SUCCESS}100%{C_RESET} {C_STEEL}{elapsed:5.1f}s{C_RESET}{CLR}")
    print(f"  {tag('OK', 34, 16)} {C_SUCCESS}{desc} verified{C_RESET}")
    return True


# ----------------------------------------------------------------------------
# BANNER
# ----------------------------------------------------------------------------
def print_banner():
    print()
    animate_block(portrait_frame, len(PORTRAIT_ART) // 3 + 40, 0.035)
    print()
    animate_block(wordmark_frame, (max(len(l) for l in WORDMARK_ART) + 8) // 3 + 3, 0.03)

    animate_block(lambda t: [rule_line(56, t * 0.03)], 30, 0.03)
    typewrite(f"    {tag('V1', 196, 226)} {C_STEEL}|{C_RESET} {grad_text('BY HAYAKAZ3', THEME['wm_top'], bold=True)}", 0.015)
    typewrite(f"    {grad_text('AUTONOMOUS LIVE WALLPAPER GENERATING SCRIPT', THEME['wm_bottom'])}", 0.006)
    typewrite(f"    {grad_text('OPPO SYSTEM COMPILER & STUDIO', THEME['bar'])}", 0.006)
    print(rule_line(56, 0.0))
    print()
    typewrite(f"  {fg(226)}[*]{C_RESET} {C_ICE}{random.choice(FUNNY_QUOTES)}{C_RESET}", 0.012)
    print()


# ----------------------------------------------------------------------------
# SETUP / CONFIG
# ----------------------------------------------------------------------------
def run_onboarding_wizard():
    show_panel("INITIALIZATION PROTOCOL // LOCAL DEPENDENCY DISCOVERY",
               [f"{C_CYAN}Auto-scanning local 'dependencies/' directory...{C_RESET}"], frames=12)

    ffmpeg_local = DEP_DIR / "ffmpeg" / "bin" / "ffmpeg.exe"
    d_ffmpeg = str(ffmpeg_local) if ffmpeg_local.exists() else "ffmpeg"
    d_apktool = str(DEP_DIR / "apktool.jar") if (DEP_DIR / "apktool.jar").exists() else "apktool"
    d_signer = str(DEP_DIR / "uber-apk-signer.jar") if (DEP_DIR / "uber-apk-signer.jar").exists() else "uber-apk-signer.jar"
    print()

    def_ffmpeg = ask("01", "FFmpeg path", default=d_ffmpeg) or d_ffmpeg
    def_apktool = ask("02", "Apktool path", default=d_apktool) or d_apktool
    def_signer = ask("03", "Signer JAR path", default=d_signer) or d_signer
    def_author = ask("04", "Operator ID", default="Hayakaz3") or "Hayakaz3"
    def_theme = (ask("05", "Theme", hint="classic / solar / kryptonite", default="classic") or "classic").lower()
    if def_theme not in THEMES:
        def_theme = "classic"

    env_content = f"""# SUPER PROTOCOL ENVIRONMENT CONFIGURATION
PROJECT_NAME=Super Protocol by Hayakaz3
STUDIO_AUTHOR={def_author}
FFMPEG_PATH={def_ffmpeg}
APKTOOL_PATH={def_apktool}
APKSIGNER_PATH={def_signer}
THEME={def_theme}
"""
    ENV_PATH.write_text(env_content, encoding="utf-8")
    print(f"\n  {tag('OK', 34, 16)} Configuration locked to {C_ICE}pipeline_settings.env{C_RESET}\n")


def load_environment():
    if not ENV_PATH.exists():
        run_onboarding_wizard()

    env_vars = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return env_vars


ENV = load_environment()
FFMPEG_BIN = ENV.get("FFMPEG_PATH", "ffmpeg")
APKTOOL_RAW = ENV.get("APKTOOL_PATH", "apktool")
APKSIGNER_RAW = ENV.get("APKSIGNER_PATH", "uber-apk-signer.jar")
STUDIO_AUTHOR = ENV.get("STUDIO_AUTHOR", "Hayakaz3")
apply_theme(THEME_FLAG or ENV.get("THEME", "classic"))


def get_tool_cmd(tool_path_str):
    if tool_path_str.endswith(".jar"):
        return ["java", "-jar", tool_path_str]
    return [tool_path_str]


def load_config():
    profile_path = PROFILE_DIR / "reference.json"
    if profile_path.exists():
        with open(profile_path, "r", encoding="utf-8") as f:
            return json.load(f)

    default_config = {
        "target_codec": "libx265",
        "width": 1440,
        "height": 3168,
        "fps": 60,
        "crf": 20,
        "target_asset_path": "BASE/assets/unlocked.mp4"
    }
    profile_path.write_text(json.dumps(default_config, indent=4), encoding="utf-8")
    return default_config


def unique_path(p):
    """Never overwrite: foo.apk -> foo_2.apk -> foo_3.apk ..."""
    if not p.exists():
        return p
    i = 2
    while True:
        q = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not q.exists():
            return q
        i += 1


def rel(p):
    try:
        return str(Path(p).relative_to(ROOT_DIR))
    except ValueError:
        return str(p)


# ----------------------------------------------------------------------------
# VIDEO HELPERS
# ----------------------------------------------------------------------------
def probe_duration(video):
    """Video length in seconds (read from FFmpeg's banner) so the bar can be real."""
    try:
        p = subprocess.run(get_tool_cmd(FFMPEG_BIN) + ["-nostdin", "-i", video],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        pass
    return None


def extract_last_frame(input_video, scale_filter):
    """Replace BASE/assets/backup.jpg with the final frame of the video."""
    target = DECODED_DIR / "assets" / "backup.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = get_tool_cmd(FFMPEG_BIN) + [
        "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-sseof", "-1", "-i", input_video, "-an",
        "-vf", scale_filter, "-pix_fmt", "yuvj420p", "-q:v", "2",
        "-update", "1", str(target)
    ]
    run_command(cmd, "Capturing final frame -> assets/backup.jpg", key="frame", est=4)
    if not target.exists() or target.stat().st_size == 0:
        print(f"  {tag('WARN', 220, 16)} backup.jpg was not produced; the old one (if any) is unchanged.")


# ----------------------------------------------------------------------------
# ICON
# ----------------------------------------------------------------------------
def ensure_pillow():
    """Import Pillow, installing it automatically if it is missing."""
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        pass

    print(f"\n  {tag('ICON', 39, 16)} {C_CYAN}Pillow not found - installing the icon engine automatically...{C_RESET}")
    base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "Pillow"]
    ok = run_command(base, "Installing Pillow (icon resizer)", key="pip", est=25,
                     numbered=False, fatal=False)
    if not ok:
        ok = run_command(base + ["--user"], "Retrying Pillow install (user scope)", key="pip",
                         est=25, numbered=False, fatal=False)
    if not ok:
        return False
    importlib.invalidate_caches()
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        print(f"  {tag('WARN', 220, 16)} Pillow installed but needs a restart of the script to load.")
        return False


def inject_custom_icon(decoded_dir):
    """If profiles/icon.png exists, resize it for every density and swap it in.
    If it does not exist this does nothing at all."""
    icon_source = PROFILE_DIR / "icon.png"
    if not icon_source.exists():
        return

    print(f"\n  {tag('ICON', 39, 16)} {C_CYAN}Master emblem detected ({C_ICE}profiles/icon.png{C_CYAN}) - building density matrix...{C_RESET}")
    if not ensure_pillow():
        print(f"  {tag('WARN', 220, 16)} Icon skipped (Pillow unavailable). Build continues with the original icon.")
        return
    from PIL import Image

    res_dir = decoded_dir / "res"
    manifest_path = decoded_dir / "AndroidManifest.xml"
    if not res_dir.exists() or not manifest_path.exists():
        print(f"  {tag('WARN', 220, 16)} No res/ or manifest in BASE - icon skipped.")
        return

    manifest = manifest_path.read_text(encoding="utf-8")
    app = re.search(r"<application\b[^>]*>", manifest, re.S)
    app_tag = app.group(0) if app else ""

    targets = {}     # resource name -> resource type
    new_app_tag = app_tag

    def collect(attr):
        nonlocal new_app_tag
        m = re.search(rf'android:{attr}="([^"]*)"', app_tag)
        if not m:
            return False
        ref = re.fullmatch(r"@(mipmap|drawable)/([\w]+)", m.group(1))
        if ref:
            targets[ref.group(2)] = ref.group(1)
        else:   # unresolved reference (e.g. @0x7f...) -> point it at our own resource
            targets["ic_launcher"] = "mipmap"
            new_app_tag = new_app_tag.replace(m.group(0), f'android:{attr}="@mipmap/ic_launcher"')
        return True

    has_icon = collect("icon")
    collect("roundIcon")
    if not has_icon:
        targets["ic_launcher"] = "mipmap"
        new_app_tag = new_app_tag.replace("<application", '<application android:icon="@mipmap/ic_launcher"', 1)

    # Remove every existing variant (adaptive XML, webp, other-density PNGs) so
    # nothing overrides the new PNGs.
    for p in list(res_dir.rglob("*")):
        if p.is_file() and p.stem in targets and p.parent.name.split("-")[0] in ("mipmap", "drawable"):
            p.unlink()

    densities = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
    try:
        img = Image.open(icon_source).convert("RGBA")
        if img.width != img.height:     # pad (never distort) to a square canvas
            side = max(img.size)
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
            img = canvas
        for name, rtype in targets.items():
            for dens, size in densities.items():
                folder = res_dir / f"{rtype}-{dens}"
                folder.mkdir(parents=True, exist_ok=True)
                img.resize((size, size), Image.Resampling.LANCZOS).save(folder / f"{name}.png", "PNG")
        if new_app_tag != app_tag:
            manifest_path.write_text(manifest.replace(app_tag, new_app_tag, 1), encoding="utf-8")
        print(f"  {tag('OK', 34, 16)} {C_SUCCESS}Icon injected for {', '.join(sorted(targets))} across all 5 density tiers.{C_RESET}")
    except Exception as e:
        print(f"  {tag('WARN', 220, 16)} Icon processing failed: {e}")


def update_manifest(decoded_dir, new_app_name, unique_suffix):
    manifest_path = decoded_dir / "AndroidManifest.xml"
    if not manifest_path.exists():
        return

    print(f"\n  {tag('MNFT', 135, 231)} {C_CYAN}Synchronizing AndroidManifest.xml & package identity...{C_RESET}")
    content = manifest_path.read_text(encoding="utf-8")

    # Unique package name per build so Android treats each as an independent app
    safe_suffix = re.sub(r'[^a-zA-Z0-9]', '', unique_suffix).lower()
    new_package_name = f"com.hayakaz3.wallpaper.{safe_suffix}"

    if 'package="' in content:
        content = re.sub(r'package="[^"]+"', f'package="{new_package_name}"', content)

    if new_app_name:
        if 'android:label=' in content:
            content = re.sub(r'android:label="[^"]*"', f'android:label="{new_app_name}"', content)
        else:
            content = content.replace('<application', f'<application android:label="{new_app_name}"', 1)

    if 'android:icon=' not in content:
        content = content.replace('<application', '<application android:icon="@mipmap/ic_launcher"', 1)

    manifest_path.write_text(content, encoding="utf-8")
    print(f"  {tag('OK', 34, 16)} Unique Package ID locked: {C_CYAN}{new_package_name}{C_RESET}")


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    print_banner()

    if len(ARGS) < 1:
        halt("No input media stream detected.",
             "Drag and drop an MP4 onto pipeline_drop.bat   |   flags: --no-anim  --theme=classic|solar|kryptonite")
        sys.exit(1)

    input_video = ARGS[0]
    if not Path(input_video).exists():
        halt(f"Input video not found: {input_video}")
        sys.exit(1)

    config = load_config()

    section("TARGET PACKAGE CONFIGURATION")
    custom_app_name = ask("01", "Application Label", hint="e.g. Mirage Live Wallpaper")
    custom_apk_name = ask("02", "Output APK Name", hint="e.g. Mirage_Wallpaper.apk")

    if not custom_apk_name:
        custom_apk_name = "Oppo_Custom_LiveWallpaper.apk"
    if not custom_apk_name.lower().endswith(".apk"):
        custom_apk_name += ".apk"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_stem = re.sub(r"[^\w.\-]+", "_", Path(custom_apk_name).stem)
    unique_suffix = f"{safe_stem}_{timestamp}"

    print()
    show_panel("SYSTEM TELEMETRY", [
        f"{C_STEEL}WORKSPACE   :{C_RESET} {C_ICE}{clip(str(ROOT_DIR), 54)}{C_RESET}",
        f"{C_STEEL}OPERATOR    :{C_RESET} {C_ICE}{STUDIO_AUTHOR}{C_RESET}",
        f"{C_STEEL}OPTICAL     :{C_RESET} {C_CYAN}{config['width']}x{config['height']} @ {config['fps']}FPS [{config['target_codec'].upper()} // EDGE-FILL]{C_RESET}",
        f"{C_STEEL}BUILD ID    :{C_RESET} {fg(226)}{unique_suffix}{C_RESET}",
        f"{C_STEEL}THEME       :{C_RESET} {grad_text((THEME_FLAG or ENV.get('THEME', 'classic')).upper(), THEME['bar'], bold=True)}",
    ])

    if not DECODED_DIR.exists():
        halt("Decoded APK substrate 'BASE' not located in workspace.", f"Required path: {DECODED_DIR}")
        sys.exit(1)

    mission_start = time.time()

    target_asset = DECODED_DIR / "assets" / "unlocked.mp4"
    target_asset.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: Transcode video (edge-to-edge: scale up + crop, zero black bars)
    scale_filter = (
        f"scale={config['width']}:{config['height']}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={config['width']}:{config['height']}"
    )
    duration = probe_duration(input_video)

    ffmpeg_cmd = get_tool_cmd(FFMPEG_BIN) + [
        "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-progress", "pipe:1", "-nostats",
        "-i", input_video,
        "-c:v", config["target_codec"],
        "-crf", str(config["crf"]),
        "-vf", scale_filter,
        "-r", str(config["fps"]),
        "-an", str(target_asset)
    ]
    run_command(ffmpeg_cmd, "Transcoding video stream with FFmpeg (HEVC Edge-to-Edge)",
                key="ffmpeg", est=40, duration=duration)

    # Step 2: last frame of the video -> assets/backup.jpg
    extract_last_frame(input_video, scale_filter)

    # Step 3: custom icon (only if profiles/icon.png exists) + unique package identity
    inject_custom_icon(DECODED_DIR)
    update_manifest(DECODED_DIR, custom_app_name, unique_suffix)

    # Step 4: rebuild APK - every build gets its own unsigned file
    unsigned_apk = unique_path(OUTPUT_DIR / f"{unique_suffix}_unsigned.apk")
    apktool_cmd = get_tool_cmd(APKTOOL_RAW) + ["b", str(DECODED_DIR), "-o", str(unsigned_apk)]
    run_command(apktool_cmd, "Compiling APK architecture via Apktool", key="apktool", est=45)

    # Step 5: sign - then rename to this build's unique name
    sign_cmd = get_tool_cmd(APKSIGNER_RAW) + ["--apks", str(unsigned_apk), "--out", str(SIGNED_DIR)]
    run_command(sign_cmd, "Applying cryptographic signature via uber-apk-signer", key="sign", est=12)

    # uber-apk-signer names its output <input>-aligned-signed.apk or -aligned-debugSigned.apk
    candidates = [p for p in SIGNED_DIR.glob(f"{unsigned_apk.stem}*.apk")]
    if not candidates:
        print(f"\n  {tag('WARN', 220, 16)} Signed APK not found in {rel(SIGNED_DIR)}.")
        print(f"  {C_STEEL}Fallback artifact:{C_RESET} {C_CYAN}{unsigned_apk}{C_RESET}\n")
        return

    generated = max(candidates, key=lambda p: p.stat().st_mtime)
    final_output = unique_path(SIGNED_DIR / f"{unique_suffix}.apk")
    generated.rename(final_output)

    # Victory!
    victory_flight()
    total = time.time() - mission_start
    if ANIM:
        animate_block(confetti_frame, 22, 0.06)
    pkg_id = re.sub(r'[^a-zA-Z0-9]', '', unique_suffix).lower()[:24]
    mission_txt = grad_text(f'{total:.1f} seconds', THEME['bar'], bold=True)
    show_panel("COMPILATION COMPLETE // PACKAGE READY FOR DEPLOYMENT", [
        f"{C_STEEL}UNSIGNED :{C_RESET} {C_CYAN}{clip(rel(unsigned_apk), 56)}{C_RESET}",
        f"{C_STEEL}SIGNED   :{C_RESET} {fg(226)}{C_BOLD}{clip(rel(final_output), 56)}{C_RESET}",
        f"{C_STEEL}PACKAGE  :{C_RESET} {C_ICE}com.hayakaz3.wallpaper.{pkg_id}...{C_RESET}",
        f"{C_STEEL}MISSION  :{C_RESET} {mission_txt}",
    ], frames=24)
    print()
    closing = grad_text('"Up, up, and away."', THEME['bar'], bold=True)
    typewrite(f"  {fg(226)}[*]{C_RESET} {closing}\n", 0.02)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.stdout.write("\033[?25h" if ANSI_SUPPORTED else "")
        print(f"\n  {tag('ABORT', 220, 16)} Flight cancelled by operator.\n")
        sys.exit(130)
