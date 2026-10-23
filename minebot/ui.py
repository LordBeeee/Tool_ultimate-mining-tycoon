from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import cv2
from PIL import Image, ImageTk

from . import win
from .engine import Bot, Recorder
from .store import ROOT, add_ore, add_vehicle, load, save
from .vision import Ocr, encode_patch, lab_sample, meteor_matches, ore_candidates, ore_name, same_vehicle_name, spawn_card, suggest_vehicle_name


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Ultimate Mining Tycoon • Auto Miner")
        self.root.geometry("880x660")
        self.data = load()
        self.ocr = Ocr(self.data.get("ocr_path", ""))
        self.bot = Bot(self.data, self.log, self.refresh)
        self.recorder = Recorder(self.log)
        self.recording_key = ""
        self.ore_vars: dict[str, tk.BooleanVar] = {}
        self.capture = None
        self.capture_mode = ""
        self.photo = None
        self.closed = False
        self.vehicle_var = tk.StringVar(value=self.data.get("selected_vehicle", ""))
        self.kind_var = tk.StringVar(value="drill")
        self.bag_var = tk.StringVar(value="36")
        self.ocr_var = tk.StringVar(value=self.data.get("ocr_path", ""))
        self.state_var = tk.StringVar(value="Sẵn sàng")
        self._make_ui()
        self.refresh()
        threading.Thread(target=self._hotkeys, daemon=True).start()
        threading.Thread(target=self._observe_ores, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _make_ui(self) -> None:
        header = ttk.Frame(self.root, padding=10)
        header.pack(fill="x")
        ttk.Label(header, text="Ultimate Mining Tycoon", font=("Segoe UI", 17, "bold")).pack(side="left")
        ttk.Label(header, textvariable=self.state_var).pack(side="right")

        body = ttk.Frame(self.root, padding=10)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)

        ores = ttk.LabelFrame(left, text="Quặng cần đào", padding=8)
        ores.pack(fill="both", expand=True)
        self.ore_box = ttk.Frame(ores)
        self.ore_box.pack(fill="both", expand=True)
        ttk.Button(ores, text="Học quặng từ màn hình • F7", command=lambda: self.open_capture("ore")).pack(fill="x", pady=3)
        ttk.Button(ores, text="Xem thử nhận diện", command=self.preview_detection).pack(fill="x", pady=3)
        ttk.Label(ores, text="Loại mới mặc định chưa chọn. Cần nhìn thấy tên quặng trong game.", wraplength=360).pack(anchor="w")

        vehicle = ttk.LabelFrame(right, text="Xe có thể Spawn", padding=8)
        vehicle.pack(fill="x")
        self.vehicle_combo = ttk.Combobox(vehicle, textvariable=self.vehicle_var, state="readonly")
        self.vehicle_combo.pack(fill="x")
        self.vehicle_combo.bind("<<ComboboxSelected>>", lambda _: self.select_vehicle())
        row = ttk.Frame(vehicle)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="Quét menu Spawn", command=self.scan_vehicles).pack(side="left", expand=True, fill="x")
        ttk.Button(row, text="Spawn xe đã chọn", command=self.spawn_vehicle).pack(side="left", expand=True, fill="x")
        ttk.Label(vehicle, text="Loại xe:").pack(anchor="w")
        kind = ttk.Combobox(vehicle, textvariable=self.kind_var, values=["drill", "haul"], state="readonly")
        kind.pack(fill="x")
        kind.bind("<<ComboboxSelected>>", lambda _: self.vehicle_settings())
        ttk.Label(vehicle, text="Sức chứa ba lô (mỗi lượt xả):").pack(anchor="w")
        bag = ttk.Entry(vehicle, textvariable=self.bag_var)
        bag.pack(fill="x")
        bag.bind("<FocusOut>", lambda _: self.vehicle_settings())

        calibration = ttk.LabelFrame(right, text="Hiệu chỉnh", padding=8)
        calibration.pack(fill="x", pady=8)
        ttk.Button(calibration, text="Ghi tuyến nhà máy → cửa mỏ", command=lambda: self.toggle_record("route")).pack(fill="x", pady=2)
        ttk.Button(calibration, text="Ghi một lượt xả quặng", command=lambda: self.toggle_record("unload_macro")).pack(fill="x", pady=2)
        ttk.Button(calibration, text="Ghi đào cuốc + chất lên xe", command=lambda: self.toggle_record("pickaxe_macro")).pack(fill="x", pady=2)
        ttk.Button(calibration, text="Ghi đặt và kích nổ C4", command=lambda: self.toggle_record("c4_macro")).pack(fill="x", pady=2)
        ttk.Button(calibration, text="Học thiên thạch từ màn hình • F6", command=lambda: self.open_capture("meteor")).pack(fill="x", pady=2)
        ttk.Label(calibration, text="Bấm nút ghi, thao tác trong Roblox, rồi bấm lại để lưu. Giữ nguyên góc camera.", wraplength=360).pack(anchor="w")

        controls = ttk.Frame(right)
        controls.pack(fill="x")
        ttk.Button(controls, text="▶ Chạy", command=self.start).pack(side="left", fill="x", expand=True)
        ttk.Button(controls, text="⏸ Tạm dừng F8", command=self.bot.toggle_pause).pack(side="left", fill="x", expand=True)
        ttk.Button(controls, text="■ Dừng F9", command=self.bot.stop).pack(side="left", fill="x", expand=True)
        ocr_row = ttk.Frame(right)
        ocr_row.pack(fill="x", pady=5)
        ttk.Entry(ocr_row, textvariable=self.ocr_var).pack(side="left", fill="x", expand=True)
        ttk.Button(ocr_row, text="Tesseract OCR…", command=self.choose_ocr).pack(side="left")

        bottom = ttk.LabelFrame(self.root, text="Nhật ký", padding=5)
        bottom.pack(fill="both", padx=10, pady=(0, 10))
        self.log_box = tk.Text(bottom, height=9, state="disabled", wrap="word")
        self.log_box.pack(fill="both")

    def log(self, message: str) -> None:
        logging.info(message)
        def insert() -> None:
            self.state_var.set(message)
            self.log_box.config(state="normal")
            self.log_box.insert("end", time.strftime("%H:%M:%S ") + message + "\n")
            self.log_box.see("end")
            self.log_box.config(state="disabled")
        self.root.after(0, insert)

    def refresh(self) -> None:
        def update() -> None:
            for child in self.ore_box.winfo_children():
                child.destroy()
            self.ore_vars = {}
            for name in sorted(self.data["ores"]):
                var = tk.BooleanVar(value=name in self.data["selected_ores"])
                self.ore_vars[name] = var
                ttk.Checkbutton(self.ore_box, text=name, variable=var,
                                command=self.select_ores).pack(anchor="w")
            if not self.ore_vars:
                ttk.Label(self.ore_box, text="Chưa học loại quặng nào").pack(anchor="w")
            self.vehicle_combo["values"] = sorted(self.data["vehicles"])
            current = self.data["vehicles"].get(self.data.get("selected_vehicle", ""), {})
            self.kind_var.set(current.get("kind", "drill"))
            self.bag_var.set(str(current.get("bag_capacity", 36)))
        self.root.after(0, update)

    def select_ores(self) -> None:
        self.data["selected_ores"] = [name for name, var in self.ore_vars.items() if var.get()]
        save(self.data)

    def select_vehicle(self) -> None:
        self.data["selected_vehicle"] = self.vehicle_var.get()
        save(self.data)
        self.refresh()

    def vehicle_settings(self) -> None:
        entry = self.data["vehicles"].get(self.vehicle_var.get())
        if entry is None:
            return
        entry["kind"] = self.kind_var.get()
        try:
            entry["bag_capacity"] = max(1, int(self.bag_var.get()))
        except ValueError:
            entry["bag_capacity"] = 36
        save(self.data)

    def _ocr_needed(self) -> bool:
        if self.ocr.available:
            return False
        messagebox.showerror("Thiếu OCR", "Cài Tesseract OCR (English), rồi mở lại ứng dụng. Xem README.md.")
        return True

    def choose_ocr(self) -> None:
        path = filedialog.askopenfilename(title="Chọn tesseract.exe", filetypes=[("Executable", "*.exe")])
        if not path:
            return
        self.ocr_var.set(path)
        self.data["ocr_path"] = path
        save(self.data)
        self.ocr = Ocr(path)
        self.bot.ocr = Ocr(path)
        self.log("Đã đặt đường dẫn Tesseract OCR")

    def scan_vehicles(self) -> None:
        if self._ocr_needed():
            return
        self.log("Đang quét menu Spawn; không điều khiển chuột cho tới khi hoàn tất")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _hide_for_game(self) -> None:
        done = threading.Event()
        def hide() -> None:
            self.root.withdraw()
            done.set()
        self.root.after(0, hide)
        if not done.wait(3):
            raise RuntimeError("Không thể thu nhỏ cửa sổ tool")

    def _show_after_game(self) -> None:
        def show() -> None:
            if not self.closed:
                self.root.deiconify()
                self.root.lift()
        self.root.after(0, show)

    def _scan_worker(self) -> None:
        try:
            (ROOT / "scan_debug.png").unlink(missing_ok=True)
            self._hide_for_game()
            if not win.focus_roblox():
                raise RuntimeError("Không đưa Roblox lên trước được")
            # Windows fades a withdrawn Tk window for several frames. Capturing
            # immediately records the translucent tool over the Roblox card.
            time.sleep(.6)
            seen: set[str] = set()
            added = 0
            for index in range(24):
                if not win.roblox_focused():
                    raise RuntimeError("Roblox mất focus trước khi chụp menu")
                for attempt in range(3):
                    frame = win.screenshot()
                    name, capacity, spawnable = spawn_card(frame, self.ocr)
                    if name or (spawnable and suggest_vehicle_name(None, capacity, self.data["vehicles"])):
                        break
                    time.sleep(.6)
                if not name and not (spawnable and suggest_vehicle_name(None, capacity, self.data["vehicles"])):
                    diagnostic = ROOT / "scan_debug.png"
                    Image.fromarray(frame).save(diagnostic)
                    raise RuntimeError(f"Không đọc được thẻ xe; đã lưu ảnh chụp tại {diagnostic}")
                if spawnable:
                    scan_name = name
                    suggestion = suggest_vehicle_name(name, capacity, self.data["vehicles"])
                    confirmed = self._confirm_vehicle(suggestion, capacity, scan_name)
                    if confirmed is None:
                        break
                    name = next((existing for existing in self.data["vehicles"]
                                 if existing.casefold() == confirmed.casefold()), confirmed)
                if name in seen:
                    break
                seen.add(name)
                if spawnable:
                    add_vehicle(self.data, name, capacity)
                    if scan_name:
                        self.data["vehicles"][name]["scan_name"] = scan_name
                    added += 1
                    if not self.data.get("selected_vehicle"):
                        self.data["selected_vehicle"] = name
                        self.root.after(0, lambda selected=name: self.vehicle_var.set(selected))
                    self.log(f"Xe: {name} (Capacity {capacity or '?'})")
                if not win.focus_roblox():
                    raise RuntimeError("Không đưa Roblox lên trước được")
                time.sleep(.6)
                win.click_rel(.70, .96)
                time.sleep(.35)
            save(self.data)
            self.refresh()
            if added:
                self.log(f"Đã thêm {added} xe có thể Spawn")
            else:
                self.log("Không có xe nào được thêm: thẻ hiện tại không có nút Spawn")
        except Exception as exc:
            self.log(f"Quét xe thất bại: {exc}")
        finally:
            self._show_after_game()

    def _confirm_vehicle(self, guess: str, capacity: int | None,
                         raw_name: str | None = None) -> str | None:
        done = threading.Event()
        answer: list[str | None] = [None]

        def ask() -> None:
            try:
                self.root.deiconify()
                self.root.lift()
                answer[0] = simpledialog.askstring(
                    "Xác nhận xe",
                    f"Tên xe đang hiện trong Roblox (Capacity {capacity or '?'}):\n"
                    f"OCR đọc: {raw_name or '?'} — hãy kiểm tra tên gợi ý.",
                    initialvalue=guess, parent=self.root)
            finally:
                self.root.withdraw()
                done.set()

        self.root.after(0, ask)
        done.wait()
        return answer[0].strip() if answer[0] and answer[0].strip() else None

    def spawn_vehicle(self) -> None:
        if self._ocr_needed():
            return
        threading.Thread(target=self._spawn_worker, daemon=True).start()

    def _spawn_worker(self) -> None:
        try:
            self._hide_for_game()
            target = self.vehicle_var.get()
            if not target:
                raise RuntimeError("Chưa chọn xe")
            vehicle = self.data["vehicles"].get(target, {})
            scan_name = vehicle.get("scan_name", target)
            expected_capacity = vehicle.get("capacity")
            if not win.focus_roblox():
                raise RuntimeError("Không đưa Roblox lên trước được")
            time.sleep(.6)
            for _ in range(24):
                name, capacity, spawnable = spawn_card(win.screenshot(), self.ocr)
                same_capacity = expected_capacity is not None and capacity == expected_capacity
                same_name = same_vehicle_name(name, target, scan_name)
                capacity_conflict = (expected_capacity is not None and capacity is not None
                                     and capacity != expected_capacity)
                if spawnable and (same_name or same_capacity) and not capacity_conflict:
                    verified = same_name and (expected_capacity is None or same_capacity)
                    if verified or self._confirm_spawn_target(target, name, capacity):
                        if not win.focus_roblox():
                            raise RuntimeError("Không đưa Roblox lên trước được")
                        time.sleep(.6)
                        win.click_rel(.50, .96)
                        self.log(f"Đã bấm Spawn: {target}")
                        return
                if not win.roblox_focused():
                    if not win.focus_roblox():
                        raise RuntimeError("Không đưa Roblox lên trước được")
                    time.sleep(.6)
                win.click_rel(.70, .96)
                time.sleep(.35)
            raise RuntimeError("Không tìm thấy xe trong menu hiện tại")
        except Exception as exc:
            self.log(f"Spawn xe thất bại: {exc}")
        finally:
            self._show_after_game()

    def _confirm_spawn_target(self, target: str, read_name: str | None,
                              capacity: int | None) -> bool:
        done = threading.Event()
        answer = [False]
        def ask() -> None:
            try:
                self.root.deiconify()
                self.root.lift()
                answer[0] = messagebox.askyesno(
                    "Xác nhận xe trước khi Spawn",
                    f"Xe đang hiện trong Roblox có phải {target} không?\n"
                    f"OCR đọc: {read_name or '?'}; Capacity: {capacity or '?'}",
                    parent=self.root)
            finally:
                self.root.withdraw()
                done.set()
        self.root.after(0, ask)
        done.wait()
        return answer[0]

    def toggle_record(self, key: str) -> None:
        if self.recorder.running:
            actions = self.recorder.stop()
            if self.recording_key == "c4_macro":
                self.data["c4_macro"] = actions
            else:
                vehicle = self.data["vehicles"].get(self.vehicle_var.get())
                if vehicle is not None:
                    vehicle[self.recording_key] = actions
                    vehicle["calibrated"] = bool(vehicle.get("route") and vehicle.get("unload_macro"))
            self.recording_key = ""
            save(self.data)
            self.log(f"Đã lưu {len(actions)} thao tác")
            return
        if key != "c4_macro" and not self.vehicle_var.get():
            messagebox.showerror("Chưa chọn xe", "Quét và chọn xe trước khi ghi")
            return
        self.recording_key = key
        self.recorder.start()
        self.log("Đang ghi. Chuyển sang Roblox và thao tác; bấm lại nút để lưu")

    def open_capture(self, mode: str) -> None:
        if mode == "ore" and self._ocr_needed():
            return
        try:
            self.capture = win.screenshot()
        except Exception as exc:
            messagebox.showerror("Không chụp được", str(exc))
            return
        self.capture_mode = mode
        window = tk.Toplevel(self.root)
        window.title("Bấm vào " + ("quặng" if mode == "ore" else "thiên thạch"))
        h, w = self.capture.shape[:2]
        scale = min(1100/w, 680/h, 1)
        image = Image.fromarray(self.capture).resize((int(w*scale), int(h*scale)))
        self.photo = ImageTk.PhotoImage(image)
        canvas = tk.Canvas(window, width=image.width, height=image.height)
        canvas.pack()
        canvas.create_image(0, 0, image=self.photo, anchor="nw")
        def pick(event) -> None:
            x, y = int(event.x/scale), int(event.y/scale)
            if mode == "ore":
                h, w = self.capture.shape[:2]
                region = self.capture[max(0,y-180):min(h,y+180), max(0,x-240):min(w,x+240)]
                guess = ore_name(self.ocr.read(region)) or ore_name(self.ocr.read(self.capture)) or ""
                name = simpledialog.askstring("Tên quặng", "Xác nhận tên quặng OCR đọc được:",
                                              initialvalue=guess, parent=window)
                if name:
                    is_new = add_ore(self.data, name, lab_sample(self.capture, x, y))
                    save(self.data)
                    self.refresh()
                    self.log(("Đã học loại mới: " if is_new else "Đã thêm mẫu: ") + name)
            else:
                self.data["meteor_samples"].append(encode_patch(self.capture, x, y))
                self.data["meteor_samples"] = self.data["meteor_samples"][-8:]
                save(self.data)
                self.log("Đã lưu mẫu thiên thạch")
            window.destroy()
        canvas.bind("<Button-1>", pick)

    def preview_detection(self) -> None:
        try:
            frame = win.screenshot()
        except Exception as exc:
            messagebox.showerror("Không chụp được", str(exc))
            return
        for candidate in ore_candidates(frame, self.data["ores"], self.data["selected_ores"])[:15]:
            x, y = int(candidate["x"]), int(candidate["y"])
            cv2.circle(frame, (x, y), 24, (0, 255, 0), 3)
            cv2.putText(frame, candidate["name"], (x+12, y-12), cv2.FONT_HERSHEY_SIMPLEX,
                        .6, (0, 255, 0), 2)
        for candidate in meteor_matches(frame, self.data.get("meteor_samples", []))[:5]:
            x, y = int(candidate["x"]), int(candidate["y"])
            cv2.circle(frame, (x, y), 28, (255, 0, 0), 3)
            cv2.putText(frame, "Meteor", (x+12, y-12), cv2.FONT_HERSHEY_SIMPLEX,
                        .6, (255, 0, 0), 2)
        window = tk.Toplevel(self.root)
        window.title("Nhận diện hiện tại • xanh: quặng • đỏ: thiên thạch")
        h, w = frame.shape[:2]
        scale = min(1100/w, 680/h, 1)
        image = Image.fromarray(frame).resize((int(w*scale), int(h*scale)))
        photo = ImageTk.PhotoImage(image)
        label = ttk.Label(window, image=photo)
        label.image = photo
        label.pack()

    def start(self) -> None:
        self.select_ores()
        self.vehicle_settings()
        try:
            if not win.focus_roblox():
                raise ValueError("Hãy mở Roblox")
            self.bot.start()
        except Exception as exc:
            messagebox.showerror("Chưa thể chạy", str(exc))

    def _hotkeys(self) -> None:
        last_f6 = last_f7 = last_f8 = last_f9 = False
        while not self.closed:
            f6 = bool(win.user32.GetAsyncKeyState(0x75) & 0x8000)
            f7 = bool(win.user32.GetAsyncKeyState(0x76) & 0x8000)
            f8 = bool(win.user32.GetAsyncKeyState(0x77) & 0x8000)
            f9 = bool(win.user32.GetAsyncKeyState(0x78) & 0x8000)
            if f6 and not last_f6 and win.roblox_focused():
                self.root.after(0, lambda: self.open_capture("meteor"))
            if f7 and not last_f7 and win.roblox_focused():
                self.root.after(0, lambda: self.open_capture("ore"))
            if f8 and not last_f8 and self.bot.thread and self.bot.thread.is_alive():
                self.bot.toggle_pause()
            if f9 and not last_f9:
                self.bot.stop()
            last_f6, last_f7, last_f8, last_f9 = f6, f7, f8, f9
            time.sleep(.08)

    def _observe_ores(self) -> None:
        while not self.closed:
            time.sleep(6)
            if not self.ocr.available or not win.roblox_focused():
                continue
            if self.bot.thread and self.bot.thread.is_alive():
                continue
            try:
                frame = win.screenshot()
                name = ore_name(self.ocr.read(frame))
                if not name:
                    continue
                rect = win.roblox_rect()
                point = win.wintypes.POINT()
                win.user32.GetCursorPos(win.ctypes.byref(point))
                if not rect:
                    continue
                x, y = point.x-rect[0], point.y-rect[1]
                if 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]:
                    is_new = add_ore(self.data, name, lab_sample(frame, x, y))
                    save(self.data)
                    if is_new:
                        self.log(f"Tự phát hiện quặng mới: {name} (chưa chọn)")
                        self.refresh()
            except Exception as exc:
                self.log(f"Không đọc được tên quặng: {exc}")

    def close(self) -> None:
        self.closed = True
        self.bot.stop()
        if self.recorder.running:
            self.recorder.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
