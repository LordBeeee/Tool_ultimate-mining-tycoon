import unittest
import base64
from pathlib import Path

import numpy as np

from minebot.engine import reverse_route
from minebot.store import add_ore, add_vehicle, deduplicate_vehicles, defaults
from minebot.vision import lab_sample, meteor_matches, ore_candidates, ore_name, same_vehicle_name, spawn_card, suggest_vehicle_name, vehicle_full


class FakeOcr:
    def __init__(self, text):
        self.text = text
        self.available = True

    def read(self, image, psm=11):
        return self.text


class CoreTests(unittest.TestCase):
    def test_ore_filter_and_new_ore_unchecked(self):
        frame = np.zeros((300, 480, 3), dtype=np.uint8)
        frame[65:105, 50:95] = [0, 255, 0]
        frame[65:105, 155:200] = [0, 0, 255]
        frame[65:105, 260:305] = [255, 255, 0]
        data = defaults()
        for name, x in (("Green Ore", 70), ("Blue Ore", 175), ("Yellow Ore", 280)):
            self.assertTrue(add_ore(data, name, lab_sample(frame, x, 80)))
        data["selected_ores"] = ["Green Ore", "Blue Ore"]
        found = ore_candidates(frame, data["ores"], data["selected_ores"])
        self.assertTrue(any(item["name"] == "Green Ore" for item in found))
        self.assertTrue(any(item["name"] == "Blue Ore" for item in found))
        self.assertFalse(any(item["name"] == "Yellow Ore" for item in found))
        self.assertNotIn("Yellow Ore", data["selected_ores"])

    def test_spawn_menu_parser(self):
        image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        name, capacity, enabled = spawn_card(image, FakeOcr(
            "Super Crawler\nSpeed: 5.3   Capacity: 180\nSpawn"))
        self.assertEqual((name, capacity, enabled), ("Super Crawler", 180, True))
        _, _, enabled = spawn_card(image, FakeOcr("Super Crawler\nCapacity: 180\nLocked"))
        self.assertFalse(enabled)
        self.assertEqual(spawn_card(image, FakeOcr("Cash $100\nPlace Ore Here")),
                         (None, None, False))
        self.assertTrue(same_vehicle_name("exa-Dertll", "Exa-Drill"))
        self.assertFalse(same_vehicle_name("ree Deri", "Exa-Drill"))
        self.assertEqual(suggest_vehicle_name("Power Britt", 48), "Power Drill")
        self.assertEqual(suggest_vehicle_name("exa-Dertll", 120), "Exa-Drill")
        self.assertEqual(suggest_vehicle_name("vracibike", 8), "Quadbike")
        self.assertEqual(suggest_vehicle_name("RES a iis", 8), "Quadbike")
        self.assertEqual(suggest_vehicle_name(None, 8), "Quadbike")
        self.assertEqual(suggest_vehicle_name("Power Britt", 180,
                         {"Another 180": {"capacity": 180}}), "Power Britt")

    def test_route_reversal(self):
        route = [{"keys": ["w", "a"], "duration": 1.2},
                 {"keys": ["w"], "duration": 2}, {"click": [.5, .5]}]
        self.assertEqual(reverse_route(route), [
            {"keys": ["s"], "duration": 2},
            {"keys": ["s", "a"], "duration": 1.2},
        ])

    def test_vehicle_full_visual_cue(self):
        frame = np.zeros((300, 480, 3), dtype=np.uint8)
        frame[130:137, 180:300] = [180, 0, 0]
        self.assertTrue(vehicle_full(frame, FakeOcr("VEHICLE FULL")))
        self.assertFalse(vehicle_full(frame, FakeOcr("")))

    def test_labels_and_vehicle_defaults(self):
        self.assertEqual(ore_name("Molybdenum Ore"), "Molybdenum Ore")
        self.assertIsNone(ore_name("Place Ore Here!"))
        self.assertIsNone(ore_name(None))
        data = defaults()
        add_vehicle(data, "Super Crawler", 180)
        self.assertEqual(data["vehicles"]["Super Crawler"]["capacity"], 180)

    def test_duplicate_vehicle_names_are_merged(self):
        data = defaults()
        add_vehicle(data, "exa-Drill", 120)
        add_vehicle(data, "Exa-Drill", 120)
        data["selected_vehicle"] = "exa-Drill"
        self.assertTrue(deduplicate_vehicles(data))
        self.assertEqual(list(data["vehicles"]), ["Exa-Drill"])
        self.assertEqual(data["selected_vehicle"], "Exa-Drill")

    def test_meteor_reference_from_supplied_video(self):
        from PIL import Image
        path = Path(__file__).resolve().parents[1] / "assets" / "meteor_reference.png"
        image = np.asarray(Image.open(path).convert("RGB"))
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        self.assertTrue(meteor_matches(image, [encoded]))


if __name__ == "__main__":
    unittest.main()
