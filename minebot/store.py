from __future__ import annotations

import base64
import json
import threading
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "settings.json"
_SAVE_LOCK = threading.RLock()


def defaults() -> dict[str, Any]:
    reference = ROOT / "assets" / "meteor_reference.png"
    meteor_samples = [base64.b64encode(reference.read_bytes()).decode("ascii")] if reference.exists() else []
    return {
        "ores": {},
        "vehicles": {},
        "selected_ores": [],
        "selected_vehicle": "",
        "meteor_samples": meteor_samples,
        "c4_macro": [],
        "max_retries": 3,
        "ocr_path": "",
    }


def load() -> dict[str, Any]:
    data = defaults()
    if SETTINGS.exists():
        try:
            saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                data.update(saved)
        except (OSError, json.JSONDecodeError):
            pass
    if deduplicate_vehicles(data):
        save(data)
    return data


def deduplicate_vehicles(data: dict[str, Any]) -> bool:
    vehicles = data.get("vehicles", {})
    groups: dict[str, list[str]] = {}
    for name in vehicles:
        groups.setdefault(name.casefold(), []).append(name)
    changed = False
    for names in groups.values():
        if len(names) < 2:
            continue
        keep = next((name for name in names if name[:1].isupper()), names[0])
        for duplicate in names:
            if duplicate == keep:
                continue
            old = vehicles.pop(duplicate)
            for key in ("route", "unload_macro", "pickaxe_macro"):
                if not vehicles[keep].get(key) and old.get(key):
                    vehicles[keep][key] = old[key]
            if data.get("selected_vehicle") == duplicate:
                data["selected_vehicle"] = keep
            changed = True
    return changed


def save(data: dict[str, Any]) -> None:
    with _SAVE_LOCK:
        temporary = SETTINGS.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(SETTINGS)


def add_ore(data: dict[str, Any], name: str, sample: list[float]) -> bool:
    name = " ".join(name.strip().split())
    if not name:
        return False
    is_new = name not in data["ores"]
    entry = data["ores"].setdefault(name, {"samples": []})
    if not any(sum((float(a)-float(b))**2 for a, b in zip(previous, sample)) < 64
               for previous in entry["samples"]):
        entry["samples"].append(sample)
    entry["samples"] = entry["samples"][-12:]
    return is_new


def add_vehicle(data: dict[str, Any], name: str, capacity: int | None = None) -> bool:
    name = " ".join(name.strip().split())
    if not name:
        return False
    is_new = name not in data["vehicles"]
    entry = data["vehicles"].setdefault(name, {
        "capacity": None,
        "kind": "drill",
        "route": [],
        "unload_macro": [],
        "calibrated": False,
    })
    if capacity is not None:
        entry["capacity"] = capacity
    return is_new
