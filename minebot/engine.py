from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable

import cv2
import numpy as np

from . import win
from .store import add_ore, save
from .vision import Ocr, depth_meters, lab_sample, meteor_matches, ore_candidates, ore_name, vehicle_full


MOVEMENT = ("w", "a", "s", "d", "space", "shift", "e", "f", "h", "b", "1", "2")


class Recorder:
    """Poll the actual keyboard and mouse during a human demonstration."""

    def __init__(self, log: Callable[[str], None]) -> None:
        self.log = log
        self.running = False
        self.actions: list[dict] = []
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.running:
            return
        self.actions = []
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self) -> list[dict]:
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        return self.actions.copy()

    def _loop(self) -> None:
        previous: tuple[str, ...] = ()
        left_down = False
        start = time.monotonic()
        while self.running:
            if not win.roblox_focused():
                start = time.monotonic()
                time.sleep(.05)
                continue
            keys = tuple(key for key in MOVEMENT if win.held(key))
            now = time.monotonic()
            if keys != previous:
                elapsed = now-start
                if elapsed >= .04:
                    self.actions.append({"keys": list(previous), "duration": round(elapsed, 3)}
                                        if previous else {"wait": round(elapsed, 3)})
                previous, start = keys, now
            pressed = bool(win.user32.GetAsyncKeyState(0x01) & 0x8000)
            if pressed and not left_down:
                elapsed = now-start
                if elapsed >= .04:
                    self.actions.append({"keys": list(previous), "duration": round(elapsed, 3)}
                                        if previous else {"wait": round(elapsed, 3)})
                start = now
                rect = win.roblox_rect()
                if rect:
                    point = win.wintypes.POINT()
                    win.user32.GetCursorPos(win.ctypes.byref(point))
                    x = (point.x-rect[0])/(rect[2]-rect[0])
                    y = (point.y-rect[1])/(rect[3]-rect[1])
                    if 0 <= x <= 1 and 0 <= y <= 1:
                        self.actions.append({"click": [round(x, 4), round(y, 4)]})
            left_down = pressed
            time.sleep(.025)
        now = time.monotonic()
        if now-start >= .04:
            self.actions.append({"keys": list(previous), "duration": round(now-start, 3)}
                                if previous else {"wait": round(now-start, 3)})
        self.log(f"Đã ghi {len(self.actions)} thao tác")


def reverse_route(route: list[dict]) -> list[dict]:
    back = []
    for action in reversed(route):
        keys = action.get("keys", [])
        if not any(key in keys for key in ("w", "s")):
            continue
        opposite = [("s" if key == "w" else "w" if key == "s" else key)
                    for key in keys if key in ("w", "a", "s", "d")]
        back.append({"keys": opposite, "duration": action["duration"]})
    return back


class Bot:
    def __init__(self, data: dict, log: Callable[[str], None], changed: Callable[[], None]) -> None:
        self.data, self.log, self.changed = data, log, changed
        self.stop_event = threading.Event()
        self.paused = threading.Event()
        self.thread: threading.Thread | None = None
        self.ocr = Ocr(data.get("ocr_path", ""))
        self.state = "Đã dừng"
        self.last_frame: np.ndarray | None = None
        self.last_discovery = 0.0
        self.last_meteor_scan = 0.0
        self.last_depth_scan = 0.0
        self.cached_depth: int | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        vehicle = self.data["vehicles"].get(self.data["selected_vehicle"], {})
        if not self.data["selected_ores"]:
            raise ValueError("Hãy chọn ít nhất một loại quặng")
        if not self.ocr.available:
            raise ValueError("Chưa có Tesseract OCR; đặt đường dẫn trong cấu hình")
        if not vehicle.get("route") or not vehicle.get("unload_macro"):
            raise ValueError("Xe này cần ghi tuyến và thao tác xả trước")
        if vehicle.get("kind") == "haul" and not vehicle.get("pickaxe_macro"):
            raise ValueError("Xe chở quặng cần ghi thao tác đào cuốc")
        if not win.roblox_rect():
            raise ValueError("Không tìm thấy Roblox")
        self.stop_event.clear()
        self.paused.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.paused.clear()
        win.release_all()

    def toggle_pause(self) -> None:
        if self.paused.is_set():
            self.paused.clear()
            self.log("Tiếp tục")
        else:
            self.paused.set()
            win.release_all()
            self.log("Tạm dừng")

    def _set_state(self, name: str) -> None:
        self.state = name
        self.log(name)

    def _check(self) -> None:
        if self.stop_event.is_set():
            raise InterruptedError()
        while self.paused.is_set():
            win.release_all()
            if self.stop_event.wait(.1):
                raise InterruptedError()
        if not win.roblox_focused():
            self.paused.set()
            win.release_all()
            self.log("Roblox mất focus; bấm F8 trong Roblox để tiếp tục")
            while self.paused.is_set():
                if self.stop_event.wait(.1):
                    raise InterruptedError()
            if not win.roblox_focused():
                self.paused.set()
                raise RuntimeError("Roblox vẫn chưa được chọn")

    def _play(self, actions: list[dict], trace: list[dict] | None = None) -> None:
        for action in actions:
            self._check()
            if "click" in action:
                win.click_rel(*action["click"])
            elif "wait" in action:
                if self.stop_event.wait(min(float(action["wait"]), 20)):
                    raise InterruptedError()
            elif "keys" in action:
                win.drive(action["keys"], min(float(action["duration"]), 20), self.stop_event)
                if trace is not None:
                    trace.append(action)

    def _move(self, keys: list[str], duration: float, trace: list[dict]) -> None:
        self._check()
        action = {"keys": keys, "duration": duration}
        win.drive(keys, duration, self.stop_event)
        trace.append(action)

    def _stalled(self, before: np.ndarray, after: np.ndarray) -> bool:
        a = cv2.resize(before, (160, 90))
        b = cv2.resize(after, (160, 90))
        # Ignore HUD, which can change while the car is motionless.
        difference = cv2.absdiff(a[13:70], b[13:70]).mean()
        return difference < 2.5

    def _recover(self, trace: list[dict], count: int) -> None:
        if count >= int(self.data.get("max_retries", 3)):
            raise RuntimeError("Xe bị kẹt sau ba lần thử")
        self.log(f"Thử thoát kẹt {count+1}")
        self._move(["s"], .8, trace)
        self._move(["w", "a" if count % 2 == 0 else "d"], .7, trace)

    def _discover_ore(self, frame: np.ndarray) -> str | None:
        if time.monotonic() - self.last_discovery < 8:
            return None
        self.last_discovery = time.monotonic()
        name = ore_name(self.ocr.read(frame))
        if not name:
            return None
        rect = win.roblox_rect()
        point = win.wintypes.POINT()
        win.user32.GetCursorPos(win.ctypes.byref(point))
        if rect:
            x, y = point.x-rect[0], point.y-rect[1]
            if 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]:
                is_new = add_ore(self.data, name, lab_sample(frame, x, y))
                save(self.data)
                if is_new:
                    self.log(f"Phát hiện quặng mới: {name} (chưa chọn)")
                    self.changed()
        return name

    def _mine(self, vehicle: dict) -> tuple[list[dict], bool]:
        trace: list[dict] = []
        retries = 0
        no_target = 0
        last_meteor = 0.0
        self._set_state("Đang tìm và đào quặng")
        while not self.stop_event.is_set():
            self._check()
            frame = win.screenshot()
            visible_name = self._discover_ore(frame)
            if vehicle_full(frame, self.ocr):
                self.log("Xe đầy")
                return trace, False
            if time.monotonic()-self.last_depth_scan > 3:
                self.last_depth_scan = time.monotonic()
                self.cached_depth = depth_meters(frame, self.ocr)
            depth = self.cached_depth
            if depth == 0 and len(trace) > 10:
                self.log("Mỏ sập, đã trở lại cửa mỏ")
                return trace, True
            if (self.data.get("c4_macro") and
                time.monotonic()-last_meteor > 60 and
                time.monotonic()-self.last_meteor_scan > 8):
                self.last_meteor_scan = time.monotonic()
                hits = meteor_matches(frame, self.data.get("meteor_samples", []))
                if hits and hits[0]["score"] >= 14:
                    self._set_state("Phá thiên thạch")
                    c4_actions = [action.copy() for action in self.data["c4_macro"]]
                    for action in c4_actions:
                        if "click" in action:
                            action["click"] = [hits[0]["x"]/frame.shape[1],
                                               hits[0]["y"]/frame.shape[0]]
                            break
                    self._play(c4_actions)
                    last_meteor = time.monotonic()
                    self._set_state("Đang tìm và đào quặng")
                    continue
            candidates = ore_candidates(frame, self.data["ores"], self.data["selected_ores"])
            if visible_name and visible_name not in self.data["selected_ores"]:
                candidates = []
            if candidates:
                target = candidates[0]
                x_ratio = target["x"]/frame.shape[1]
                steer = ["a"] if x_ratio < .43 else ["d"] if x_ratio > .57 else []
                keys = ["w"] + steer
                before = frame
                self._move(keys, .45, trace)
                after = win.screenshot()
                if self._stalled(before, after):
                    self._recover(trace, retries)
                    retries += 1
                else:
                    retries, no_target = 0, 0
                if vehicle.get("kind") == "haul":
                    self._set_state("Đào cuốc và chất lên xe")
                    self._play(vehicle["pickaxe_macro"])
                    self._set_state("Đang tìm và đào quặng")
            else:
                no_target += 1
                # Only explore along known open floor. A newly seen ore must be selected to become a target.
                before = frame
                self._move(["w", "a" if no_target % 8 < 4 else "d"], .35, trace)
                if self._stalled(before, win.screenshot()):
                    self._recover(trace, retries)
                    retries += 1
                else:
                    retries = 0
                if no_target >= 80:
                    raise RuntimeError("Không tìm thấy quặng đã chọn; dừng để tránh đi lạc")
        raise InterruptedError()

    def _return_to_factory(self, vehicle: dict, trace: list[dict], teleported: bool) -> None:
        self._set_state("Quay về nhà máy")
        if not teleported:
            try:
                self._play(reverse_route(trace))
            except RuntimeError:
                self.log("Không quay lại được; chờ mỏ sập và dịch chuyển lên cửa mỏ")
                while not self.stop_event.wait(2):
                    self._check()
                    if depth_meters(win.screenshot(), self.ocr) == 0:
                        break
        self._play(reverse_route(vehicle["route"]))

    def _unload(self, vehicle: dict) -> None:
        self._set_state("Xả quặng")
        capacity = vehicle.get("capacity") or 36
        bag_capacity = max(1, int(vehicle.get("bag_capacity") or 36))
        rounds = max(1, math.ceil(capacity / bag_capacity))
        for index in range(rounds):
            self._check()
            self.log(f"Lượt xả {index+1}/{rounds}")
            self._play(vehicle["unload_macro"])
        text = self.ocr.read(win.screenshot())
        if re.search(r"VEHICLE FULL", text, re.I):
            raise RuntimeError("Xe vẫn báo đầy sau khi xả")

    def _run(self) -> None:
        try:
            vehicle = self.data["vehicles"][self.data["selected_vehicle"]]
            while not self.stop_event.is_set():
                self._set_state("Đi tới mỏ")
                self._play(vehicle["route"])
                trace, teleported = self._mine(vehicle)
                self._return_to_factory(vehicle, trace, teleported)
                self._unload(vehicle)
                self.log("Hoàn thành một chuyến")
        except InterruptedError:
            self.log("Đã dừng")
        except Exception as exc:
            self.log(f"Lỗi: {exc}")
        finally:
            win.release_all()
            self.state = "Đã dừng"
            self.changed()
