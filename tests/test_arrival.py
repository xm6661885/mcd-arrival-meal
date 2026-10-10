import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from fake_mcp import FakeMCP  # noqa: E402
import mcd_mcp  # noqa: E402

import arrival  # noqa: E402


class ArrivalTest(unittest.TestCase):
    def test_waits_for_next_slot(self):
        p = arrival.plan(FakeMCP(), "广州市", "广州南站", "2026-10-11 10:25", 10, [("巨无霸", 1)], 2)
        first = p["options"][0]
        self.assertEqual(first["pickupAt"], "2026-10-11 10:44")
        self.assertEqual(first["waitMinutes"], 9)
        self.assertEqual(first["total"], 24.5)

    def test_breakfast_menu_missing_item(self):
        p = arrival.plan(FakeMCP(), "广州市", "广州南站", "2026-10-11 07:00", 10, [("巨无霸", 1)], 1)
        o = p["options"][0]
        self.assertEqual(o["slot"], "早餐")
        self.assertEqual(o["missing"], ["巨无霸"])
        self.assertTrue(o["suggest"])

    def test_create_requires_takeaway_code(self):
        fake = FakeMCP()
        fake.data = (lambda orig: (lambda n, a=None: {"orderId": "X"} if n == "create-order" else orig(n, a)))(fake.data)
        arrival.create(fake, "1001", "2026-10-11 12:00", [("巨无霸", 1)], None)

    def test_order_needs_confirm(self):
        self.assertEqual(arrival.main(["order", "--store", "1", "--pickup-at", "2026-10-11 12:00", "--item", "x"]), 2)


if __name__ == "__main__":
    unittest.main()