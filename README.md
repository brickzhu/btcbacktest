# BTC Order Block Backtest

BTC 订单块（Order Block）回测框架，基于 Binance 永续合约 1h K线数据。

## 策略

### 全天候策略 ⭐（推荐）
`orderblock_14atr_no_sl_filter.py`

| 参数 | 值 |
|------|-----|
| K线 | 原始1h（无合并） |
| 结构 | k1反向 → k2突破 → k3.close确认FVG |
| 入场价 | k1边缘（FVG 100%） |
| 止损 | k1.close |
| ATR | 14周期，1.5x倍数 |
| FVG/ATR | ≥ 50% |
| 回踩时限 | 336小时（14天） |
| 盈亏比 | 1:2 |
| 杠杆 | 10x |
| 硬止损 | 15% |
| 方向 | 多空双向 |

**特点：** 六年回测（2021-2026）无一年亏损，熊市(2022)仍盈利。

### 牛市策略
`orderblock_14atr_merged_v1_onlybull.py`

合并K线 + 只做多。牛市爆发力极强，但熊市/横盘会亏损。

### 合并K线策略
`orderblock_14atr_merged.py`

合并K线版本，多空双向。

## 数据源

- Binance 永续合约 API (`fapi.binance.com`)
- 时区：UTC+8（北京时间）

## 运行

```bash
pip install requests pandas numpy
python3 orderblock_14atr_no_sl_filter.py
```

输出回测结果到终端，交易明细保存到 CSV。
