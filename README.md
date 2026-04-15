# BTC 订单块策略回测

订单块（Order Block）交易策略的回测与分析代码。

## 📁 文件说明

| 文件 | 说明 |
|------|------|
| `orderblock_backtest.py` | 网格搜索回测，测试ATR/实体/吞没确认等多种参数组合 |
| `orderblock_analysis.py` | 订单块结构分析，识别三根K线特征 |
| `orderblock_filter_backtest.py` | 新结论筛选回测（k2实体/k1实体, FVG/k1振幅, 成交量变化） |
| `orderblock_pnl_backtest.py` | 收益率计算回测，计算总收益和最大回撤 |
| `orderblock_strategy_compare.py` | 策略对比回测（新结论筛选 vs ATR筛选） |
| `orderblock_engulfing_test.py` | 吞没确认测试 |

## 📊 输出结果

| 文件 | 说明 |
|------|------|
| `orderblock_results.csv` | 网格搜索详细结果 |
| `orderblock_filter_results.csv` | 筛选回测详细结果 |
| `orderblock_output.txt` | 回测输出日志 |

## 📈 核心结论

### 最优策略

**看涨订单块 + ATR筛选 + 盈亏比1:6**

- k1 是下跌K线
- k2 收盘突破 k1.high
- k2实体 >= ATR × 1.5
- FVG/ATR >= 10%
- 入场：FVG 50%
- 止损：k1.low
- 止盈：盈亏比 1:6

### 过去一年回测结果

| 指标 | 数值 |
|------|------|
| 总收益 | +53.97% |
| 最大回撤 | -10.41% |
| 胜率 | 34.2% |
| 交易次数 | 38 |

### 关键发现

1. **看涨订单块明显优于看跌订单块**
   - 看涨：+53.97%
   - 看跌：亏损

2. **ATR筛选优于固定比率筛选**
   - ATR是动态阈值，自适应市场波动
   - 固定比率容易误判

3. **盈亏比1:6效果最佳**
   - 高盈亏比弥补低胜率
   - 最大回撤可控

## 🛠️ 使用方法

```bash
# 安装依赖
pip install pandas numpy requests

# 运行回测
python orderblock_strategy_compare.py
```

## ⚠️ 注意事项

- 回测基于历史数据，不代表未来收益
- 实际交易需考虑滑点、流动性等因素
- 请根据自身风险承受能力调整仓位

## 📅 更新时间

2026-04-15
