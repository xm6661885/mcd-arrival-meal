---
name: mcd-arrival-meal
description: 坐高铁/飞机的人按到站或落地时间，提前在车站、机场附近的麦当劳预约取餐，下车走到门店就能拿；晚点了帮忙判断是取消重订还是联系门店。当用户说"我几点到广州南站，帮我订份麦当劳""落地想吃麦当劳""下了高铁就要吃"或给出车次/航班到达时间时使用。
---

# 麦麦落地补给（mcd-arrival-meal）

## 需要的 MCP

麦当劳 MCP Server（`mcd-mcp`，`https://mcp.mcd.cn`）。可以搭配 12306、航旅或地图类 MCP 获取到达时间，没有的话让用户直接说到达时间。

## 工作流程

1. **收集信息**：到达城市、车站或机场名、到达时间（`yyyy-MM-dd HH:mm`）、下车走到门店大概要几分钟（默认 10 分钟，大站出站可以设 15~20 分钟），以及想吃什么（可选）。
2. **找门店**：`query-nearby-stores`（`searchType=2`，`city`，`keyword`=车站/机场名，`beType=1`）。只保留 `reservation=true` 的门店。
3. **算取餐时间**：取餐时间 = 到达时间 + 步行时间。从 `reservationTimeOptions[].reservationOptionText` 解析出可预约时段（如"早餐(06:14至10:15)，午餐(10:44至14:15)"）：
   - 取餐时间落在某个时段内，就用这个时间；
   - 落在两个时段的空档（比如 10:15~10:44 早午餐切换），就顺延到下一时段开始，并告诉用户要等几分钟；
   - 当天之后再没有可预约时段，就说明情况并换门店。
4. **按时段菜单选餐**：`query-meals` 带上 `reservationDate`，拿到的是那个时段的菜单（早餐时段没有巨无霸）。用户点的东西在该时段没有时，从菜单里推荐替代。
5. **算价**：`calculate-price`（带 `reservationDate`），展示实付和 `takeWayList`（堂食、外带、取餐柜等）。
6. **下单**：用户确认门店、取餐时间、餐品、金额和取餐方式后，再调用 `create-order`（`orderType=1`，`beType=1`，`reservationDate`，`takeWayCode`）。返回支付信息后提醒用户支付。
7. **到站前**：`query-order` 查状态和取餐码（`pickupCode`）。
8. **晚点了**：`query-order` 查当前状态：
   - `orderStatus=1` 待支付：建议 `cancel-order`（`cancelReasonCode=5` 送达时间选错了），然后按新的到达时间重新规划；
   - 已支付、备餐中：MCP 不支持改约，建议用户在麦当劳 App 里联系门店，或到店后凭取餐码取餐。

## 规则

- 车站门店通常只开放约 1 天内的预约，太早来问就提示用户到出发当天再来订。
- `create-order`、`cancel-order` 会改动账户，必须得到用户明确确认后才能调用。
- 价格只看 `calculate-price` 的返回（单位：分）。

## 辅助脚本

`scripts/arrival.py` 实现了以上流程：

```bash
python3 scripts/arrival.py plan --city 广州市 --keyword 广州南站 --arrive "2026-10-11 12:05" --walk 8 --item 麦辣鸡腿汉堡三件套
python3 scripts/arrival.py order --store 1400877 --pickup-at "2026-10-11 12:13" --item 麦辣鸡腿汉堡三件套 --confirm
python3 scripts/arrival.py status --order <orderId>
python3 scripts/arrival.py delay  --order <orderId> --arrive "2026-10-11 12:50"
python3 scripts/arrival.py cancel --order <orderId> --confirm
```
