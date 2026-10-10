"""Minimal McDonald's China MCP client (Streamable HTTP, JSON-RPC 2.0).

Standard library only. Configure with environment variables:
  MCD_MCP_TOKEN  required, the token from https://open.mcd.cn/mcp
  MCD_MCP_URL    optional, defaults to https://mcp.mcd.cn
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    pass


class McdMCP:
    def __init__(self, token: str | None = None, url: str | None = None,
                 timeout: float = 60, client_name: str = "mcd-skill"):
        self.token = token or os.environ.get("MCD_MCP_TOKEN", "")
        if not self.token:
            raise MCPError("缺少 MCD_MCP_TOKEN 环境变量，请在 https://open.mcd.cn/mcp 申请 Token")
        self.url = url or os.environ.get("MCD_MCP_URL") or DEFAULT_URL
        self.timeout = timeout
        self.client_name = client_name
        self._id = 0
        self._ready = False
        self._session: str | None = None

    def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        req = urllib.request.Request(self.url, json.dumps(payload, ensure_ascii=False).encode(),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                self._session = resp.headers.get("Mcp-Session-Id") or self._session
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise MCPError(f"MCP HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc
        except urllib.error.URLError as exc:
            raise MCPError(f"无法连接麦当劳 MCP: {exc.reason}") from exc
        if "id" not in payload and not raw.strip():
            return None
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            # Streamable HTTP may answer with SSE frames; take the first JSON data frame.
            for line in raw.splitlines():
                if line.startswith("data:"):
                    try:
                        msg = json.loads(line[5:].strip())
                        break
                    except json.JSONDecodeError:
                        continue
            else:
                raise MCPError(f"无法解析 MCP 响应: {raw[:300]}")
        if isinstance(msg, dict) and msg.get("error"):
            raise MCPError(str(msg["error"].get("message", msg["error"])))
        return msg

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        return (self._post(payload) or {}).get("result") or {}

    def initialize(self) -> None:
        if self._ready:
            return
        self._rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                 "clientInfo": {"name": self.client_name, "version": "1.0.0"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._ready = True

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        return self._rpc("tools/list", {}).get("tools") or []

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a tool and return the full response body (usually {success, code, data, ...})."""
        self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("isError"):
            raise MCPError(f"{name}: {_content_text(result)}")
        body = result.get("structuredContent")
        if body is None:
            text = _content_text(result)
            try:
                body = json.loads(text)
            except (TypeError, json.JSONDecodeError):
                body = text
        if isinstance(body, dict) and body.get("success") is False:
            raise MCPError(f"{name}: {body.get('message') or body}")
        return body

    def data(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a tool and return only its `data` field."""
        body = self.call(name, arguments)
        return body.get("data") if isinstance(body, dict) else body


def _content_text(result: dict[str, Any]) -> str:
    parts = [c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict)]
    return "\n".join(p for p in parts if p)


def fen_to_yuan(value: Any) -> float:
    """calculate-price returns cents (分); query-meals returns yuan strings."""
    return round((value or 0) / 100, 2)


def parse_table(text: str) -> list[dict[str, Any]]:
    """Parse the compact table format returned by list-nutrition-foods:

        [160]{productName,energyKcal,...}:
          猪柳麦满分,308,...
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return []
    m = re.match(r"^\[\d+\]\{(.+)\}:?$", lines[0])
    if not m:
        raise ValueError("unexpected table header: " + lines[0][:80])
    fields = m.group(1).split(",")
    rows = []
    for ln in lines[1:]:
        cells = ln.split(",")
        if len(cells) != len(fields):
            continue
        row: dict[str, Any] = {}
        for k, v in zip(fields, cells):
            if v == "null":
                row[k] = None
            else:
                try:
                    row[k] = float(v) if "." in v else int(v)
                except ValueError:
                    row[k] = v
        rows.append(row)
    return rows


def menu_items(meals_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten query-meals data into [{code, name, price, originalPrice, category, tags}]."""
    details = meals_data.get("meals") or {}
    out, seen = [], set()
    for cat in meals_data.get("categories") or []:
        cname = (cat.get("name") or "").replace("\n", "")
        for m in cat.get("meals") or []:
            code = m.get("code")
            d = details.get(code) or {}
            if not code or code in seen:
                continue
            seen.add(code)
            out.append({
                "code": code,
                "name": d.get("name", ""),
                "price": float(d.get("currentPrice") or 0),
                "originalPrice": float(d.get("originalPrice") or 0),
                "category": cname,
                "tags": m.get("tags") or [],
            })
    return out


# ---------------------------------------------------------------- shared helpers

_SLOT_RE = re.compile(r"([^\s(),，]+)\(([^)]*)\)")


def parse_slots(option_text: str) -> list[dict[str, str]]:
    """Parse reservationOptionText, e.g.
    '早餐(06:14至10:15)，夜市(00:00至00:29,17:30至23:59)'
    -> [{'name': '早餐', 'start': '06:14', 'end': '10:15'}, ...]"""
    slots = []
    for name, ranges in _SLOT_RE.findall(option_text or ""):
        for rng in ranges.split(","):
            if "至" in rng:
                start, end = (s.strip() for s in rng.split("至", 1))
                slots.append({"name": name, "start": start, "end": end})
    return slots


def store_slots(store: dict[str, Any]) -> list[dict[str, str]]:
    """All reservable slots of a store, each with its date."""
    out = []
    for opt in store.get("reservationTimeOptions") or []:
        for s in parse_slots(opt.get("reservationOptionText", "")):
            out.append({"date": opt.get("date", ""), **s})
    return out


def find_slot(store: dict[str, Any], when: str) -> dict[str, str] | None:
    """Return the slot that contains `when` ('yyyy-MM-dd HH:mm'), or None."""
    day, hm = when.split(" ")
    for s in store_slots(store):
        if s["date"] == day and s["start"] <= hm <= s["end"]:
            return s
    return None


def norm_name(name: str) -> str:
    return re.sub(r"[\s\"“”'‘’™®()（）【】\-]", "", name or "")


class Nutrition:
    """Lookup table built from list-nutrition-foods."""

    KEYS = ("energyKcal", "protein", "fat", "carbohydrate", "sodium")

    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = {norm_name(r["productName"]): r for r in rows if r.get("productName")}

    @classmethod
    def load(cls, client: "McdMCP") -> "Nutrition":
        return cls(parse_table(client.data("list-nutrition-foods")))

    def get(self, name: str) -> dict[str, Any] | None:
        return self.rows.get(norm_name(name))

    def combo(self, detail: dict[str, Any]) -> dict[str, Any]:
        """Sum nutrition of a query-meal-detail result using default choices.
        Returns {'total': {...}, 'parts': [...], 'unknown': [names]}."""
        total = {k: 0.0 for k in self.KEYS}
        parts, unknown = [], []
        rounds = detail.get("rounds") or []
        if not rounds:
            picks = [(detail.get("name", ""), 1)]
        else:
            picks = []
            for rnd in rounds:
                choices = rnd.get("choices") or []
                chosen = [c for c in choices if c.get("isDefault") == 1] or choices[:1]
                for c in chosen:
                    picks.append((c.get("name", ""), int(c.get("quantity") or rnd.get("quantity") or 1)))
        for name, qty in picks:
            row = self.get(name)
            if row is None:
                unknown.append(name)
                continue
            parts.append(name)
            for k in self.KEYS:
                total[k] += float(row.get(k) or 0) * qty
        return {"total": {k: round(v) for k, v in total.items()}, "parts": parts, "unknown": unknown}


def order_args(store_code: str, be_type: int, be_code: str | None = None,
               reservation: str | None = None) -> dict[str, Any]:
    """Common arguments for query-meals / query-store-coupons / calculate-price / create-order."""
    args: dict[str, Any] = {"storeCode": store_code, "beType": be_type,
                            "orderType": 2 if be_type in (2, 6) else 1}
    if be_code and be_type != 1:
        args["beCode"] = be_code
    if reservation:
        args["reservationDate"] = reservation
    return args


# ---------------------------------------------------------------- stores & time

from datetime import datetime, timedelta  # noqa: E402

TIME_FMT = "%Y-%m-%d %H:%M"
BE_TYPES = {"pickup": 1, "delivery": 2, "drive": 5}


def parse_time(text: str) -> datetime:
    return datetime.strptime(text.strip(), TIME_FMT)


def fmt_time(dt: datetime) -> str:
    return dt.strftime(TIME_FMT)


def add_minutes(when: str, minutes: int) -> str:
    return fmt_time(parse_time(when) + timedelta(minutes=minutes))


def find_stores(client: "McdMCP", mode: str = "pickup", city: str | None = None,
                keyword: str | None = None, address_id: str | None = None) -> list[dict[str, Any]]:
    """Stores for a fulfilment mode. pickup/drive search by city+keyword, delivery by addressId.
    Each store gets a `_beType` key so later calls can build arguments with order_args()."""
    be_type = BE_TYPES[mode]
    if mode == "delivery":
        if not address_id:
            raise MCPError("外送模式需要 addressId（来自 delivery-query-addresses）")
        stores = client.data("delivery-query-stores", {"addressId": address_id, "beType": be_type})
    else:
        if not (city and keyword):
            raise MCPError("到店模式需要城市和位置关键词")
        stores = client.data("query-nearby-stores", {"beType": be_type, "searchType": 2,
                                                     "city": city, "keyword": keyword})
    stores = stores or []
    for s in stores:
        s["_beType"] = be_type
    return stores


def store_args(store: dict[str, Any], reservation: str | None = None) -> dict[str, Any]:
    return order_args(store["storeCode"], store.get("_beType", 1), store.get("beCode"), reservation)


def next_slot(store: dict[str, Any], when: str) -> dict[str, str] | None:
    """The slot containing `when`, or else the earliest slot starting after it."""
    hit = find_slot(store, when)
    if hit:
        return {**hit, "at": when}
    later = sorted((f"{s['date']} {s['start']}", s) for s in store_slots(store)
                   if f"{s['date']} {s['start']}" > when)
    return {**later[0][1], "at": later[0][0]} if later else None


def is_24h(store: dict[str, Any]) -> bool:
    return store.get("businessStartTime") == "00:00" and store.get("businessEndTime") in ("23:59", "24:00")


def parse_cart(specs: list[str]) -> list[tuple[str, int]]:
    """['巨无霸', '中薯条:2'] -> [('巨无霸', 1), ('中薯条', 2)]"""
    out = []
    for spec in specs:
        name, _, qty = spec.rpartition(":") if ":" in spec else (spec, "", "1")
        out.append((name.strip(), max(1, int(qty or 1))))
    return out


def resolve_item(menu: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Match a user-given name or code against a flattened menu: code, exact name, then substring."""
    for m in menu:
        if m["code"] == name:
            return m
    key = norm_name(name)
    exact = [m for m in menu if norm_name(m["name"]) == key]
    if exact:
        return exact[0]
    partial = [m for m in menu if key and key in norm_name(m["name"])]
    if partial:
        return min(partial, key=lambda m: len(m["name"]))
    # The menu sometimes lists a generic name ("薯条") for what the user calls "中薯条".
    covering = [m for m in menu if len(norm_name(m["name"])) >= 2 and norm_name(m["name"]) in key]
    return max(covering, key=lambda m: len(m["name"])) if covering else None
