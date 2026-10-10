import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from fake_mcp import FakeMCP  # noqa: E402
import mcd_mcp  # noqa: E402
class LibTest(unittest.TestCase):
    def test_parse_table(self):
        from fake_mcp import NUTRITION
        rows = mcd_mcp.parse_table(NUTRITION)
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["energyKcal"], 513)
        self.assertIsNone(rows[0]["nutritionDescription"])

    def test_slots(self):
        s = mcd_mcp.parse_slots("夜市(00:00至00:29,17:30至23:59)，早餐(05:30至10:59)")
        self.assertEqual([x["name"] for x in s], ["夜市", "夜市", "早餐"])
        st = {"reservationTimeOptions": [{"date": "2026-10-11", "reservationOptionText": "早餐(06:14至10:15)，午餐(10:44至14:15)"}]}
        self.assertEqual(mcd_mcp.next_slot(st, "2026-10-11 10:30")["at"], "2026-10-11 10:44")
        self.assertIsNone(mcd_mcp.next_slot(st, "2026-10-11 20:00"))

    def test_resolve_item(self):
        from fake_mcp import MENU
        menu = mcd_mcp.menu_items(MENU)
        self.assertEqual(mcd_mcp.resolve_item(menu, "巨无霸")["code"], "100")
        self.assertEqual(mcd_mcp.resolve_item(menu, "中薯条")["code"], "4810")
        self.assertEqual(mcd_mcp.resolve_item(menu, "4810")["code"], "4810")
        self.assertIsNone(mcd_mcp.resolve_item(menu, "麦旋风"))

    def test_order_args(self):
        self.assertNotIn("beCode", mcd_mcp.order_args("1", 1, "x"))
        self.assertEqual(mcd_mcp.order_args("1", 2, "x")["orderType"], 2)


if __name__ == "__main__":
    unittest.main()