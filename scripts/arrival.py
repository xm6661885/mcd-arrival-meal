#!/usr/bin/env python3
"""麦麦落地补给：按到站/落地时间，在车站或机场门店预约取餐，下车就能拿。

子命令：
  plan    找到达地门店 → 计算可预约时段 → 按预约时段菜单算价
  order   用户确认后创建预约订单（必须带 --confirm）
  status  查询订单状态（支付、取餐码）
  delay   晚点了：检查订单状态，给出改约建议（未支付可取消重下）
  cancel  取消订单（必须带 --confirm）

示例：
  python3 scripts/arrival.py plan --city 广州市 --keyword 广州南站 --arrive "2026-10-11 12:20" --item 巨无霸三件套
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcd_mcp import (MCPError, McdMCP, add_minutes, fen_to_yuan, find_stores,  # noqa: E402
                     menu_items, next_slot, parse_cart, resolve_item, store_args)

STATUS = {"1": "待支付", "2": "配餐中（已支付）", "4": "配送中", "6": "已完成",
          "7": "已取消", "8": "已评价", "10": "餐厅确认配餐中"}


def plan(client: McdMCP, city: str, keyword: str, arrive: str, walk: int,
         cart: list[tuple[str, int]], limit: int) -> dict:
    """Pick-up time = arrival + walking minutes; find the first reservable slot at or after it."""
    target = add_minutes(arrive, walk)
    stores = [s for s in find_stores(client, "pickup", city=city, keyword=keyword)
              if s.get("reservation")][:limit]
    options, skipped = [], []
    for s in stores:
        slot = next_slot(s, target)
        if not slot:
            skipped.append({"storeName": s["storeName"], "reason": "到达时段没有可预约时间"})
            continue
        wait = _minutes_between(target, slot["at"])
        args = store_args(s, slot["at"])
        try:
            menu = menu_items(client.data("query-meals", args))
        except MCPError as exc:
            skipped.append({"storeName": s["storeName"], "reason": str(exc)})
            continue
        entry = {"storeCode": s["storeCode"], "storeName": s["storeName"], "address": s.get("address"),
                 "distance": s.get("distance"), "pickupAt": slot["at"], "slot": slot["name"],
                 "waitMinutes": wait, "hours": f"{s.get('businessStartTime')}-{s.get('businessEndTime')}"}
        if cart:
            items, missing = [], []
            for name, qty in cart:
                hit = resolve_item(menu, name)
                (items.append({"productCode": hit["code"], "quantity": qty, "_name": hit["name"]})
                 if hit else missing.append(name))
            if missing:
                entry["missing"] = missing
                entry["suggest"] = [m["name"] for m in _featured(menu)][:5]
            else:
                req = {**args, "items": [{"productCode": i["productCode"], "quantity": i["quantity"]} for i in items]}
                try:
                    price = client.data("calculate-price", req)
                    entry.update({"items": [f"{i['_name']}×{i['quantity']}" for i in items],
                                  "total": fen_to_yuan(price.get("price")),
                                  "takeWays": price.get("takeWayList") or [], "request": req})
                except MCPError as exc:
                    entry["priceError"] = str(exc)
        else:
            entry["suggest"] = [f"{m['name']} ¥{m['price']}" for m in _featured(menu)][:6]
        options.append(entry)
    options.sort(key=lambda e: (e["waitMinutes"], e.get("distance") or 0))
    return {"arrive": arrive, "readyFrom": target, "options": options, "skipped": skipped}


def _featured(menu: list[dict]) -> list[dict]:
    """Featured items of a time-slot menu; breakfast menus have no 人气热卖 category, so fall back to order."""
    hot = [m for m in menu if m["category"] in ("人气热卖", "精选单人餐")]
    return hot or [m for m in menu if m["price"] > 0]


def _minutes_between(a: str, b: str) -> int:
    from mcd_mcp import parse_time
    return int((parse_time(b) - parse_time(a)).total_seconds() // 60)


def render_plan(p: dict) -> str:
    lines = [f"到达 {p['arrive']}，按步行时间预计 {p['readyFrom']} 可到门店。", ""]
    if not p["options"]:
        lines.append("附近门店都没有合适的预约时段。")
    for i, o in enumerate(p["options"], 1):
        head = f"{i}. {o['storeName']}（{o['distance']}m，营业 {o['hours']}）"
        lines.append(head)
        wait = f"，到店后需等 {o['waitMinutes']} 分钟" if o["waitMinutes"] > 0 else ""
        lines.append(f"   预约取餐：{o['pickupAt']}（{o['slot']}时段{wait}）")
        if o.get("total") is not None:
            ways = "/".join(t.get("title", "") for t in o["takeWays"])
            lines.append(f"   {'、'.join(o['items'])} 实付 ¥{o['total']:.2f}（取餐方式：{ways}）")
        if o.get("missing"):
            lines.append(f"   该时段菜单没有：{'、'.join(o['missing'])}；可选：{'、'.join(o['suggest'])}")
        elif o.get("suggest") and o.get("total") is None:
            lines.append(f"   推荐：{'、'.join(o['suggest'])}")
        if o.get("priceError"):
            lines.append(f"   算价失败：{o['priceError']}")
    for s in p["skipped"]:
        lines.append(f"- 跳过 {s['storeName']}：{s['reason']}")
    lines.append("")
    lines.append("确认门店、餐品和取餐方式后，用 order 子命令带 --confirm 下单。")
    return "\n".join(lines)


def create(client: McdMCP, store_code: str, pickup_at: str, cart, take_way: str | None) -> dict:
    args = {"storeCode": store_code, "beType": 1, "orderType": 1, "reservationDate": pickup_at}
    menu = menu_items(client.data("query-meals", args))
    items = []
    for name, qty in cart:
        hit = resolve_item(menu, name)
        if not hit:
            raise MCPError(f"预约时段菜单没有：{name}")
        items.append({"productCode": hit["code"], "quantity": qty})
    price = client.data("calculate-price", {**args, "items": items})
    ways = [t["code"] for t in price.get("takeWayList") or []]
    code = take_way or next((w for w in ways if w != "eat-in"), ways[0] if ways else None)
    if code not in ways:
        raise MCPError(f"取餐方式 {code} 不可用，可选：{ways}")
    return client.data("create-order", {**args, "items": items, "takeWayCode": code})


def delay_advice(client: McdMCP, order_id: str, new_arrive: str, walk: int) -> str:
    d = client.data("query-order", {"orderId": order_id})
    status = str(d.get("orderStatus") or d.get("status") or "")
    label = STATUS.get(status, status)
    ready = add_minutes(new_arrive, walk)
    lines = [f"订单 {order_id} 当前状态：{label}；新的到店时间约 {ready}。"]
    if status == "1":
        lines.append("还没支付：建议取消（原因选 5=送达时间选错了）后，用 plan 按新时间重新预约。")
    elif status in ("2", "10"):
        lines.append("已支付且门店在备餐：MCP 不支持改约，请在麦当劳 App 联系门店，或到店后凭取餐码取餐。")
    elif status in ("6", "8"):
        lines.append("订单已完成，餐品可能已出餐，请尽快到店或联系门店。")
    elif status == "7":
        lines.append("订单已取消，可直接按新时间重新 plan。")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="麦麦落地补给：车站/机场到达即取餐")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--city", required=True)
    p.add_argument("--keyword", required=True, help="车站/机场名，如 广州南站、白云机场")
    p.add_argument("--arrive", required=True, help="到达时间 yyyy-MM-dd HH:mm")
    p.add_argument("--walk", type=int, default=10, help="下车到门店步行分钟数，默认 10")
    p.add_argument("--item", action="append", default=[], help="餐品，可写 名称:数量")
    p.add_argument("--limit", type=int, default=4)
    p.add_argument("--json", action="store_true")
    o = sub.add_parser("order")
    o.add_argument("--store", required=True, help="storeCode")
    o.add_argument("--pickup-at", required=True, help="预约取餐时间 yyyy-MM-dd HH:mm")
    o.add_argument("--item", action="append", required=True)
    o.add_argument("--take-way", help="取餐方式 code，默认非堂食的第一项")
    o.add_argument("--confirm", action="store_true", help="用户已确认，真正下单")
    s = sub.add_parser("status")
    s.add_argument("--order", required=True)
    dl = sub.add_parser("delay")
    dl.add_argument("--order", required=True)
    dl.add_argument("--arrive", required=True, help="新的到达时间")
    dl.add_argument("--walk", type=int, default=10)
    c = sub.add_parser("cancel")
    c.add_argument("--order", required=True)
    c.add_argument("--reason", default="5", help="取消原因 code，默认 5=送达时间选错了")
    c.add_argument("--confirm", action="store_true")
    a = ap.parse_args(argv)
    if getattr(a, "confirm", None) is False:
        # Orders and cancellations change the account: refuse before touching the network.
        print("未带 --confirm：请先向用户确认门店、时间、餐品与价格后再执行。", file=sys.stderr)
        return 2
    try:
        client = McdMCP(client_name="mcd-arrival-meal")
        if a.cmd == "plan":
            r = plan(client, a.city, a.keyword, a.arrive, a.walk, parse_cart(a.item), a.limit)
            print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else render_plan(r))
        elif a.cmd == "order":
            print(json.dumps(create(client, a.store, a.pickup_at, parse_cart(a.item), a.take_way),
                             ensure_ascii=False, indent=2))
        elif a.cmd == "status":
            d = client.data("query-order", {"orderId": a.order})
            d["orderStatusText"] = STATUS.get(str(d.get("orderStatus")), d.get("orderStatus"))
            print(json.dumps(d, ensure_ascii=False, indent=2))
        elif a.cmd == "delay":
            print(delay_advice(client, a.order, a.arrive, a.walk))
        elif a.cmd == "cancel":
            print(json.dumps(client.data("cancel-order", {"orderId": a.order, "cancelReasonCode": a.reason}),
                             ensure_ascii=False, indent=2))
    except MCPError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
