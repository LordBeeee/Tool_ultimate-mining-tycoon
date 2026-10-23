from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

# Also cover callers that import this module without going through main.py.
ctypes.windll.user32.SetProcessDPIAware()

import numpy as np
from PIL import ImageGrab


user32 = ctypes.windll.user32
KEYS = {"w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44,
        "e": 0x45, "f": 0x46, "h": 0x48, "b": 0x42,
        "1": 0x31, "2": 0x32, "space": 0x20, "shift": 0x10}
MOUSE_LEFT = 0x0002
MOUSE_LEFT_UP = 0x0004


def roblox_rect() -> tuple[int, int, int, int] | None:
    hwnd = user32.FindWindowW(None, "Roblox")
    if not hwnd or not user32.IsWindowVisible(hwnd):
        return None
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    point = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y, point.x + rect.right, point.y + rect.bottom


def roblox_focused() -> bool:
    hwnd = user32.FindWindowW(None, "Roblox")
    return bool(hwnd and user32.GetForegroundWindow() == hwnd)


def focus_roblox() -> bool:
    hwnd = user32.FindWindowW(None, "Roblox")
    if not hwnd:
        return False
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.1)
    return roblox_focused()


def screenshot() -> np.ndarray:
    rect = roblox_rect()
    if rect is None:
        raise RuntimeError("Không tìm thấy cửa sổ Roblox")
    return np.asarray(ImageGrab.grab(bbox=rect).convert("RGB"))


def held(key: str) -> bool:
    return bool(user32.GetAsyncKeyState(KEYS[key]) & 0x8000)


def key_down(key: str) -> None:
    user32.keybd_event(KEYS[key], 0, 0, 0)


def key_up(key: str) -> None:
    user32.keybd_event(KEYS[key], 0, 2, 0)


def tap(key: str, duration: float = 0.08) -> None:
    key_down(key)
    time.sleep(duration)
    key_up(key)


def click_rel(x: float, y: float) -> None:
    rect = roblox_rect()
    if rect is None:
        raise RuntimeError("Không tìm thấy cửa sổ Roblox")
    left, top, right, bottom = rect
    user32.SetCursorPos(int(left + x * (right - left)), int(top + y * (bottom - top)))
    time.sleep(0.06)
    user32.mouse_event(MOUSE_LEFT, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(MOUSE_LEFT_UP, 0, 0, 0, 0)


def release_all() -> None:
    for key in KEYS:
        key_up(key)
    user32.mouse_event(MOUSE_LEFT_UP, 0, 0, 0, 0)


def drive(keys: list[str], duration: float, stop) -> None:
    if not roblox_focused():
        raise RuntimeError("Roblox mất focus")
    keys = [key for key in keys if key in KEYS]
    for key in keys:
        key_down(key)
    try:
        end = time.monotonic() + duration
        while time.monotonic() < end:
            if stop.is_set() or not roblox_focused():
                break
            time.sleep(max(.001, min(0.05, end - time.monotonic())))
    finally:
        for key in keys:
            key_up(key)
