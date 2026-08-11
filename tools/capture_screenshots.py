"""Capture the running HumanPredict window to docs/screenshots/."""

from __future__ import annotations

import ctypes
import struct
import sys
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
PW_RENDERFULLCONTENT = 2
SRCCOPY = 0x00CC0020


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def window_title(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n == 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def find_humanpredict():
    """Find the Tk app window, not an editor tab that happens to mention HumanPredict."""
    targets = []
    skip_bits = ("cursor", "visual studio", "notepad", "chrome", "firefox", "edge")

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = window_title(hwnd)
        lower = title.lower()
        if "humanpredict" not in lower:
            return True
        if any(bit in lower for bit in skip_bits):
            return True
        # Prefer the real app title from app.py
        if "hr call-in" in lower or title.strip().startswith("HumanPredict"):
            targets.append((hwnd, title))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    if targets:
        return targets

    # Fallback: any visible HumanPredict title that is not an editor
    def cb2(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = window_title(hwnd)
        lower = title.lower()
        if "humanpredict" in lower and not any(bit in lower for bit in skip_bits):
            targets.append((hwnd, title))
        return True

    user32.EnumWindows(EnumWindowsProc(cb2), 0)
    return targets


def capture_hwnd(hwnd):
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)

    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 1 or height <= 1:
        raise RuntimeError(f"Bad window size: {width}x{height}")

    hwnd_dc = user32.GetDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bmp)

    ok = user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)
    if not ok:
        ok = user32.PrintWindow(hwnd, mem_dc, 0)
    if not ok:
        screen_dc = user32.GetDC(0)
        gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, rect.left, rect.top, SRCCOPY)
        user32.ReleaseDC(0, screen_dc)

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = width
    bmi.biHeight = -height
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0
    buf_len = width * height * 4
    buf = (ctypes.c_char * buf_len)()
    gdi32.GetDIBits(mem_dc, bmp, 0, height, buf, ctypes.byref(bmi), 0)

    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)
    return width, height, bytes(buf)


def save_png_with_pillow(width, height, bgra, out_dir: Path):
    from PIL import Image

    img = Image.frombuffer("RGB", (width, height), bgra, "raw", "BGRX", 0, 1)
    full = out_dir / "01-main-window.png"
    img.save(full)
    img.crop((0, 0, width, min(height, int(height * 0.52)))).save(
        out_dir / "02-logging-and-estimate.png"
    )
    img.crop((0, max(0, int(height * 0.38)), width, height)).save(
        out_dir / "03-chart-log-notes.png"
    )
    return full


def save_bmp(width, height, bgra, path: Path):
    row_padded = (width * 3 + 3) & ~3
    img_size = row_padded * height
    header = struct.pack("<2sIHHI", b"BM", 54 + img_size, 0, 0, 54)
    dib = struct.pack("<IIIHHIIIIII", 40, width, height, 1, 24, 0, img_size, 0, 0, 0, 0)
    pixels = bytearray()
    for y in range(height - 1, -1, -1):
        row = bytearray()
        for x in range(width):
            i = (y * width + x) * 4
            row += bgra[i : i + 3]
        row += b"\x00" * (row_padded - width * 3)
        pixels += row
    path.write_bytes(header + dib + pixels)


def main():
    out_dir = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = find_humanpredict()
    if not targets:
        print("NO_WINDOW: Start the app first (python app.py)")
        return 2
    hwnd, title = targets[0]
    print(f"Capturing: {title}")
    width, height, bgra = capture_hwnd(hwnd)
    try:
        path = save_png_with_pillow(width, height, bgra, out_dir)
        print(f"Saved PNG screenshots under {out_dir}")
        print(path)
    except ImportError:
        bmp = out_dir / "01-main-window.bmp"
        save_bmp(width, height, bgra, bmp)
        print(f"Pillow missing; saved BMP: {bmp}")
        print("Install pillow to emit PNG: pip install pillow")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
