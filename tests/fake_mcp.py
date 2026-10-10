"""Offline stand-in for McdMCP used by tests. Responses mirror real mcp.mcd.cn shapes."""

from __future__ import annotations

NUTRITION = """[6]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  巨无霸,null,2146,513,27,26,42,961,171
  中薯条,null,1210,289,4,12,38,165,18
  麦香鱼,null,1359,325,16,13,35,556,99
  猪柳蛋麦满分,null,1618,387,23,21,25,846,243
  纯牛奶盒装,null,523,125,6,7,9,0,200
  可乐中杯,null,616,147,0,0,36,0,10"""

MENU = {
    "categories": [
        {"name": "人气热卖", "meals": [{"code": "900", "tags": []}, {"code": "100", "tags": []}]},
        {"name": "小食", "meals": [{"code": "4810", "tags": []}, {"code": "200", "tags": []}]},
        {"name": "饮品", "meals": [{"code": "300", "tags": []}, {"code": "400", "tags": []}]},
    ],
    "meals": {
        "900": {"name": "巨无霸三件套", "currentPrice": "36.5", "originalPrice": "45"},
        "100": {"name": "巨无霸", "currentPrice": "24.5", "originalPrice": "24.5"},
        "4810": {"name": "薯条", "currentPrice": "13.5", "originalPrice": "13.5"},
        "200": {"name": "麦香鱼", "currentPrice": "18", "originalPrice": "18"},
        "300": {"name": "纯牛奶(盒装)", "currentPrice": "9", "originalPrice": "9"},
        "400": {"name": "可乐", "currentPrice": "9.5", "originalPrice": "9.5"},
    },
}

BREAKFAST = {
    "categories": [{"name": "早餐", "meals": [{"code": "500", "tags": []}, {"code": "300", "tags": []}]}],
    "meals": {"500": {"name": "猪柳蛋麦满分", "currentPrice": "19", "originalPrice": "19"},
              "300": {"name": "纯牛奶(盒装)", "currentPrice": "9", "originalPrice": "9"}},
}

PRICES = {"900": 3650, "100": 2450, "4810": 1350, "200": 1800, "300": 900, "400": 950, "500": 1900}

SLOTS = "早餐(06:00至10:15)，午餐(10:44至14:15)，下午茶(14:44至16:45)，夜市(17:14至21:45)，宵夜(22:14至23:59)"


def store(code, name, distance, start="06:00", end="23:00", be_code=None):
    s = {"storeCode": code, "storeName": name, "address": name + "地址", "distance": distance,
         "businessStatus": True, "businessStartTime": start, "businessEndTime": end, "reservation": True,
         "reservationTimeOptions": [{"date": "2026-10-11", "today": True, "reservationOptionText": SLOTS},
                                    {"date": "2026-10-12", "today": False, "reservationOptionText": SLOTS}]}
    if be_code:
        s["beCode"] = be_code
    return s


class FakeMCP:
    def __init__(self, menus=None, orders=None, coupons=None):
        self.calls = []
        self.menus = menus or {}
        self.orders = orders or []
        self.coupons = coupons or {}

    def data(self, name, args=None):
        args = args or {}
        self.calls.append((name, args))
        if name == "list-nutrition-foods":
            return NUTRITION
        if name == "now-time-info":
            return {"formatted": "2026-10-11 08:00:00"}
        if name == "query-nearby-stores":
            return [store("1001", "A店", 100), store("1002", "B店", 300, "00:00", "23:59")]
        if name == "delivery-query-stores":
            return [store("1001", "A店", None, be_code="100102")]
        if name == "query-meals":
            menu = self.menus.get(args["storeCode"], MENU)
            res = args.get("reservationDate", "")
            if res and res.split(" ")[1] < "10:15":
                return BREAKFAST
            return menu
        if name == "query-store-coupons":
            return self.coupons.get(args["storeCode"], [])
        if name == "calculate-price":
            product = sum(PRICES[i["productCode"]] * i["quantity"] for i in args["items"])
            discount = 500 if any(i.get("couponId") for i in args["items"]) else 0
            delivery, packing = (600, 200) if args["orderType"] == 2 else (0, 0)
            return {"productPrice": product, "deliveryPrice": delivery, "packingPrice": packing,
                    "discount": discount, "price": product + delivery + packing - discount,
                    "takeWayList": [{"code": "eat-in", "title": "堂食"}, {"code": "take-in-store", "title": "外带"}]}
        if name == "order-list":
            return {"list": self.orders}
        if name == "query-order":
            return {"orderId": args["orderId"], "orderStatus": "1"}
        raise AssertionError(f"unexpected tool {name}")
