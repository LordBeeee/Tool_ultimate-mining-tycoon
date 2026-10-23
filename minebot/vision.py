from __future__ import annotations

import base64
import csv
import io
import re
import shutil
import subprocess
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


ORE_LABEL = re.compile(r"([A-Z][A-Za-z0-9' -]{2,32}\s+Ore)\b", re.I)
CAPACITY = re.compile(r"Capacity\s*:?\s*(\d+)", re.I)
OBSERVED_VEHICLES = {8: "Quadbike", 48: "Power Drill", 120: "Exa-Drill", 180: "Super Crawler"}


class Ocr:
    def __init__(self, executable: str = "") -> None:
        candidates = [executable, shutil.which("tesseract"),
                      r"C:\Program Files\Tesseract-OCR\tesseract.exe"]
        self.executable = next((str(p) for p in candidates if p and Path(p).exists()), "")

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def read(self, image: np.ndarray, psm: int = 11) -> str:
        if not self.available:
            return ""
        image = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        with tempfile.TemporaryDirectory(prefix="umt-ocr-") as directory:
            source = Path(directory) / "image.png"
            Image.fromarray(image).save(source)
            result = subprocess.run(
                [self.executable, str(source), "stdout", "-l", "eng", "--psm", str(psm)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=10, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return (result.stdout or "").strip()

    def read_words(self, image: np.ndarray, psm: int = 6) -> tuple[str, float]:
        if not self.available:
            return "", 0.0
        image = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        with tempfile.TemporaryDirectory(prefix="umt-ocr-") as directory:
            source = Path(directory) / "image.png"
            Image.fromarray(image).save(source)
            result = subprocess.run(
                [self.executable, str(source), "stdout", "-l", "eng", "--psm", str(psm), "tsv"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=10, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        rows = csv.DictReader(io.StringIO(result.stdout or ""), delimiter="\t")
        words = []
        confidences = []
        for row in rows:
            word = (row.get("text") or "").strip()
            if not word:
                continue
            try:
                confidence = float(row.get("conf") or -1)
            except ValueError:
                continue
            if confidence >= 0:
                words.append(word)
                confidences.append(confidence)
        return " ".join(words), sum(confidences) / len(confidences) if confidences else 0.0


def ore_name(text: str | None) -> str | None:
    if not text:
        return None
    found = ORE_LABEL.search(text.replace("\n", " "))
    if not found:
        return None
    name = " ".join(found.group(1).split()).title()
    return None if name in {"Place Ore", "Take Ore", "Add Ore", "Ore Ore"} else name


def same_vehicle_name(read_name: str | None, *known_names: str) -> bool:
    if not read_name:
        return False
    read = re.sub(r"[^a-z0-9]", "", read_name.casefold())
    return any(SequenceMatcher(None, read,
               re.sub(r"[^a-z0-9]", "", known.casefold())).ratio() >= .82
               for known in known_names if known)


def suggest_vehicle_name(read_name: str | None, capacity: int | None,
                         vehicles: dict | None = None) -> str | None:
    if capacity is None:
        return read_name
    known = [(name, size) for size, name in OBSERVED_VEHICLES.items()]
    known.extend((name, entry.get("capacity")) for name, entry in (vehicles or {}).items())
    same_size = list(dict.fromkeys(name for name, size in known if size == capacity))
    # A capacity with one observed name is a useful suggestion. The UI still
    # asks the user to verify the visible card before adding it.
    if len({name.casefold() for name in same_size}) == 1:
        return same_size[0]
    if not read_name:
        return None
    first = re.split(r"[\s-]+", read_name.casefold())[0]
    for name, size in known:
        expected_first = re.split(r"[\s-]+", name.casefold())[0]
        if (size == capacity and
            (SequenceMatcher(None, first, expected_first).ratio() >= .8 or
             SequenceMatcher(None, re.sub(r"[^a-z0-9]", "", read_name.casefold()),
                             re.sub(r"[^a-z0-9]", "", name.casefold())).ratio() >= .55)):
            return name
    return read_name


def vehicle_title(image: np.ndarray, ocr: Ocr, capacity: int | None = None) -> str | None:
    if not hasattr(ocr, "read_words"):
        return None
    h, w = image.shape[:2]
    # The title sits above the first cyan stats bar. Haulers have fewer stats
    # than drills, so their title is about 50 pixels lower on a 1080p screen.
    y0, y1 = int(h * .78), int(h * .92)
    bar_area = cv2.cvtColor(image[y0:y1, int(w*.26):int(w*.40)],
                            cv2.COLOR_RGB2HSV)
    cyan = cv2.inRange(bar_area, (80, 80, 90), (105, 255, 255))
    row_counts = np.count_nonzero(cyan, axis=1)
    rows = np.flatnonzero(row_counts > cyan.shape[1] * .35)
    bar_y = y0 + int(rows[0]) if len(rows) else int(h * .80)
    candidates: list[tuple[float, str]] = []
    for top, bottom, x1, x2 in ((bar_y-70, bar_y-5, .428, .574),
                                 (bar_y-58, bar_y-8, .44, .56)):
        roi = image[max(0, top):min(h, bottom), int(w*x1):int(w*x2)]
        gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
        lettering = cv2.threshold(gray, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        lettering = cv2.copyMakeBorder(lettering, 10, 10, 15, 15,
                                        cv2.BORDER_CONSTANT, value=255)
        raw, confidence = ocr.read_words(
            cv2.cvtColor(lettering, cv2.COLOR_GRAY2RGB), psm=6)
        cleaned = re.sub(r"[^A-Za-z0-9 -]", "", raw).strip()
        if 3 <= len(cleaned) <= 35 and len(cleaned.split()) <= 3:
            candidates.append((confidence, cleaned))
        original = re.sub(r"[^A-Za-z0-9 -]", "", ocr.read(roi, psm=7)).strip()
        if 3 <= len(original) <= 35 and len(original.split()) <= 3:
            candidates.append((30.0, original))
    for _, candidate in candidates:
        suggested = suggest_vehicle_name(candidate, capacity)
        if capacity in OBSERVED_VEHICLES and suggested == OBSERVED_VEHICLES[capacity]:
            return suggested
    return max(candidates)[1] if candidates else None


def spawn_card(image: np.ndarray, ocr: Ocr) -> tuple[str | None, int | None, bool]:
    h, w = image.shape[:2]
    card = image[int(h * .70):int(h * .99), int(w * .22):int(w * .78)]
    # The card has white lettering on a blue gradient and a busy 3-D scene.
    # Masking bright low-saturation pixels lets Tesseract read the stats.
    hsv = cv2.cvtColor(card, cv2.COLOR_RGB2HSV)
    lettering = cv2.inRange(hsv, (0, 0, 175), (180, 90, 255))
    text = ocr.read(cv2.cvtColor(lettering, cv2.COLOR_GRAY2RGB), psm=11)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    capacity_match = CAPACITY.search(text)
    capacity = int(capacity_match.group(1)) if capacity_match else None
    can_spawn = bool(re.search(r"\bSpawn\b", text, re.I)) and not bool(
        re.search(r"\b(Locked|Buy|Purchase)\b", text, re.I))
    # Never treat arbitrary game text as a vehicle card.
    if capacity is None or not re.search(r"\b(Spawn|Locked|Buy|Purchase)\b", text, re.I):
        return None, None, False
    name = vehicle_title(image, ocr, capacity)
    stat_index = next((i for i, line in enumerate(lines)
                       if re.search(r"\b(Speed|Capacity)\b", line, re.I)), len(lines))
    if not name:
        for line in reversed(lines[max(0, stat_index-4):stat_index]):
            cleaned = re.sub(r"[^\w -]", "", line).strip()
            if (3 <= len(cleaned) <= 35 and
                not re.search(r"\b(Vehicle|Spawner|Back|Shop|Spawn|Buy)\b", cleaned, re.I)):
                name = cleaned
                break
    return name, capacity, can_spawn


def lab_sample(image: np.ndarray, x: int, y: int, radius: int = 7) -> list[float]:
    h, w = image.shape[:2]
    patch = image[max(0, y-radius):min(h, y+radius+1), max(0, x-radius):min(w, x+radius+1)]
    lab = cv2.cvtColor(patch, cv2.COLOR_RGB2LAB)
    cy, cx = min(radius, lab.shape[0]-1), min(radius, lab.shape[1]-1)
    center = np.median(lab[max(0,cy-2):cy+3, max(0,cx-2):cx+3].reshape(-1, 3), axis=0)
    pixels = lab.reshape(-1, 3)
    close = pixels[np.linalg.norm(pixels.astype(np.float32)-center, axis=1) < 28]
    return np.median(close if len(close) else pixels, axis=0).round(1).tolist()


def ore_candidates(image: np.ndarray, ores: dict, selected: list[str]) -> list[dict]:
    if not selected:
        return []
    h, w = image.shape[:2]
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB).astype(np.float32)
    results = []
    for name in selected:
        for sample in ores.get(name, {}).get("samples", []):
            delta = np.linalg.norm(lab - np.asarray(sample, dtype=np.float32), axis=2)
            mask = (delta < 23).astype(np.uint8) * 255
            # Ignore fixed game HUD, the vehicle body and the Windows taskbar.
            mask[:int(h*.12)] = 0
            mask[int(h*.82):] = 0
            mask[:, :int(w*.03)] = 0
            mask[:, int(w*.91):] = 0
            mask[int(h*.30):int(h*.82), int(w*.35):int(w*.65)] = 0
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            count, _, stats, centers = cv2.connectedComponentsWithStats(mask)
            for index in range(1, count):
                x, y, bw, bh, area = stats[index]
                if 35 <= area <= 25000 and 5 <= bw <= w*.3 and 5 <= bh <= h*.3:
                    cx, cy = centers[index]
                    distance = ((cx-w/2)/w)**2 + ((cy-h/2)/h)**2
                    results.append({"name": name, "x": float(cx), "y": float(cy),
                                    "area": int(area), "score": float(area**.5 / (1+8*distance))})
    return sorted(results, key=lambda item: item["score"], reverse=True)


def encode_patch(image: np.ndarray, x: int, y: int, radius: int = 100) -> str:
    h, w = image.shape[:2]
    patch = image[max(0,y-radius):min(h,y+radius), max(0,x-radius):min(w,x+radius)]
    ok, png = cv2.imencode(".png", cv2.cvtColor(patch, cv2.COLOR_RGB2BGR))
    return base64.b64encode(png).decode("ascii") if ok else ""


def meteor_matches(image: np.ndarray, samples: list[str]) -> list[dict]:
    if not samples:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    orb = cv2.ORB_create(nfeatures=4000, fastThreshold=7)
    keypoints, descriptors = orb.detectAndCompute(gray, None)
    if descriptors is None:
        return []
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    results = []
    for encoded in samples:
        raw = np.frombuffer(base64.b64decode(encoded), np.uint8)
        patch = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
        if patch is None:
            continue
        _, reference = orb.detectAndCompute(patch, None)
        if reference is None:
            continue
        pairs = matcher.knnMatch(reference, descriptors, k=2)
        good = [a for a, b in pairs if a.distance < .8*b.distance]
        if len(good) >= 14:
            xs = [keypoints[m.trainIdx].pt[0] for m in good]
            ys = [keypoints[m.trainIdx].pt[1] for m in good]
            results.append({"x": float(np.median(xs)), "y": float(np.median(ys)),
                            "score": len(good)})
    return sorted(results, key=lambda item: item["score"], reverse=True)


def vehicle_full(image: np.ndarray, ocr: Ocr) -> bool:
    h, w = image.shape[:2]
    area = image[int(h*.32):int(h*.64), int(w*.32):int(w*.68)]
    hsv = cv2.cvtColor(area, cv2.COLOR_RGB2HSV)
    red = (((hsv[:, :, 0] < 11) | (hsv[:, :, 0] > 170)) &
           (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 40)).astype(np.uint8)
    red = cv2.dilate(red, np.ones((3, 15), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(red)
    candidate = any(stats[i, cv2.CC_STAT_WIDTH] > w*.065 and
                    stats[i, cv2.CC_STAT_HEIGHT] < h*.06 and
                    stats[i, cv2.CC_STAT_AREA] > 140
                    for i in range(1, count))
    return candidate and ("VEHICLE FULL" in ocr.read(area).upper() if ocr.available else True)


def depth_meters(image: np.ndarray, ocr: Ocr) -> int | None:
    h, w = image.shape[:2]
    text = ocr.read(image[:int(h*.13), int(w*.55):int(w*.85)], psm=7)
    match = re.search(r"(\d{1,4})\s*m\b", text, re.I)
    return int(match.group(1)) if match else None


def cargo_amount(text: str) -> tuple[int, int] | None:
    match = re.search(r"\b(\d{1,4})\s*/\s*(\d{1,4})\b", text)
    return (int(match.group(1)), int(match.group(2))) if match else None
