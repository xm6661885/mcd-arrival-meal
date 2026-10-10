# MCP 集成说明

## MCP Server

- 麦当劳中国 MCP Server（`mcd-mcp`），`https://mcp.mcd.cn`，Streamable HTTP
- 鉴权：`Authorization: Bearer ${MCD_MCP_TOKEN}`
- 客户端：`scripts/mcd_mcp.py`（标准库实现的 `initialize` → `notifications/initialized` → `tools/call`）

## 使用的 Tool

| Tool | 用途 |
|---|---|
| `query-nearby-stores` | 用车站/机场名搜索门店，读取 `reservation`、`reservationTimeOptions`、营业时间 |
| `query-meals` | 带 `reservationDate`，获取取餐时段对应的菜单（早餐、午餐、夜市菜单不同） |
| `calculate-price` | 预约时间下的官方实付，以及可选取餐方式 `takeWayList` |
| `create-order` | 预约订单（`orderType=1`, `beType=1`, `reservationDate`, `takeWayCode`） |
| `query-order` | 支付状态、取餐码 `pickupCode`、晚点时判断订单阶段 |
| `cancel-order` | 未支付且晚点时取消（`cancelReasonCode=5`） |

## 调用流程

```
到达时间 + 步行分钟 = 目标取餐时间
        ▼
query-nearby-stores(keyword=车站) → 过滤 reservation=true
        ▼
解析 reservationOptionText → 目标时间落在哪个时段？不在就顺延到下一时段开头
        ▼
query-meals(reservationDate) → 匹配餐品 / 推荐替代
        ▼
calculate-price(reservationDate) → 展示价格和取餐方式
        ▼ 用户确认
create-order → 支付 → query-order 查取餐码
        ▼ 晚点
query-order → 待支付：cancel-order 后重新规划；已支付：提示联系门店
```

## 业务价值

- 把"到站时间"翻译成门店能接受的预约时间，自动避开早餐和午餐切换的空档（实测广州南站 10:15~10:44 不可预约）。
- 时段菜单不同：早上到站不会推荐早餐时段不卖的东西。
- 同一车站多家门店价格不同，实测同一套餐相差 ¥2。
- 晚点的处理路径很清楚：下单、取消都要用户确认。
