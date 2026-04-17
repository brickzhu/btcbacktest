#!/usr/bin/env python3
"""
订单块回测 - 14ATR无止损筛选策略
==========================================
策略参数：
- 入场价：FVG 100%（k1边缘）
- 止损：k1.close
- ATR周期：14
- ATR倍数：1.5
- FVG/ATR最小：10%
- FVG定义：k3.close
- 止损距离筛选：无
- 数据源：Binance永续合约
- 周期：1小时
- 杠杆：10倍

回测时间：2023-04-17 ~ 2026-04-17
三年收益：+1510%（10x杠杆）
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime

# 配置
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
START_DATE = "2023-04-17"
END_DATE = "2026-04-17"

ATR_PERIOD = 14
ATR_MULTIPLIER = 1.5
FVG_ATR_PCT_MIN = 10
RETEST_LIMIT = 168
RR_RATIOS = [2, 3, 5, 6]
FEE_RATE = 0.0004
SL_DISTANCE_MAX = None  # 无止损距离筛选

def fetch_klines(symbol, interval, start_date, end_date):
    url = "https://fapi.binance.com/fapi/v1/klines"
    start_time = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_time = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)
    
    all_data = []
    current_start = start_time
    
    print(f"📥 获取永续合约数据 ({interval})...")
    
    while current_start < end_time:
        params = {"symbol": symbol, "interval": interval, "startTime": current_start, "endTime": end_time, "limit": 1500}
        response = requests.get(url, params=params)
        data = response.json()
        if not data: break
        all_data.extend(data)
        current_start = data[-1][0] + 3600000
        if len(data) < 1500: break
    
    print(f"   ✅ 共获取 {len(all_data)} 根K线")
    
    df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + pd.Timedelta(hours=8)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]

def calculate_atr(df, period=14):
    tr = pd.concat([df['high'] - df['low'], abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def identify_order_blocks(df):
    """识别订单块 - 新入场和止损规则"""
    atr = calculate_atr(df, ATR_PERIOD)
    order_blocks = []
    
    for i in range(2, len(df) - 1):
        k1, k2, k3 = df.iloc[i-2], df.iloc[i-1], df.iloc[i]
        current_atr = atr.iloc[i-1]
        if pd.isna(current_atr): continue
        
        # 看涨订单块
        if k1['close'] < k1['open'] and k2['close'] > k1['high'] and k1['high'] < k3['close']:
            fvg_size = k3['close'] - k1['high']
            if fvg_size >= 100:
                k2_body = abs(k2['close'] - k2['open'])
                fvg_atr_pct = (fvg_size / current_atr * 100)
                pass_atr = (k2_body >= current_atr * ATR_MULTIPLIER) and (fvg_atr_pct >= FVG_ATR_PCT_MIN)
                
                # 新规则：入场价 = k1.high（FVG 100%），止损 = k1.close
                entry_price = k1['high']  # FVG 100%
                stop_loss = k1['close']    # k1.close
                # 止损距离 = (入场价 - 止损价) / 入场价
                sl_distance = (entry_price - stop_loss) / entry_price * 100
                
                # 止损距离筛选
                if SL_DISTANCE_MAX is not None and sl_distance >= SL_DISTANCE_MAX:
                    continue
                
                order_blocks.append({
                    'type': 'bullish', 'index': i-2, 'timestamp': k1['timestamp'],
                    'k1_high': k1['high'], 'k1_low': k1['low'], 'k1_close': k1['close'],
                    'k3_close': k3['close'],
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'sl_distance': sl_distance,
                    'fvg_size': fvg_size, 'pass_atr': pass_atr
                })
        
        # 看跌订单块
        if k1['close'] > k1['open'] and k2['close'] < k1['low'] and k3['close'] < k1['low']:
            fvg_size = k1['low'] - k3['close']
            if fvg_size >= 100:
                k2_body = abs(k2['close'] - k2['open'])
                fvg_atr_pct = (fvg_size / current_atr * 100)
                pass_atr = (k2_body >= current_atr * ATR_MULTIPLIER) and (fvg_atr_pct >= FVG_ATR_PCT_MIN)
                
                # 新规则：入场价 = k1.low（FVG 100%），止损 = k1.close
                entry_price = k1['low']    # FVG 100%
                stop_loss = k1['close']    # k1.close
                # 止损距离 = (止损价 - 入场价) / 入场价
                sl_distance = (stop_loss - entry_price) / entry_price * 100
                
                # 止损距离筛选
                if SL_DISTANCE_MAX is not None and sl_distance >= SL_DISTANCE_MAX:
                    continue
                
                order_blocks.append({
                    'type': 'bearish', 'index': i-2, 'timestamp': k1['timestamp'],
                    'k1_high': k1['high'], 'k1_low': k1['low'], 'k1_close': k1['close'],
                    'k3_close': k3['close'],
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'sl_distance': sl_distance,
                    'fvg_size': fvg_size, 'pass_atr': pass_atr
                })
    
    return order_blocks

def simulate_trades(df, order_blocks, rr_ratio, leverage=10):
    trades = []
    for ob in order_blocks:
        ob_idx, ob_type = ob['index'], ob['type']
        entry_price, stop_loss = ob['entry_price'], ob['stop_loss']
        risk = abs(entry_price - stop_loss)
        take_profit = entry_price + (risk * rr_ratio) if ob_type == 'bullish' else entry_price - (risk * rr_ratio)
        
        # 搜索入场
        entered, entry_idx = False, None
        for i in range(ob_idx + 3, min(ob_idx + 3 + RETEST_LIMIT, len(df))):
            if df.iloc[i]['low'] <= entry_price <= df.iloc[i]['high']:
                entered, entry_idx = True, i
                break
        if not entered: continue
        
        # 检查入场K线
        entry_candle = df.iloc[entry_idx]
        if ob_type == 'bullish':
            sl_hit, tp_hit = entry_candle['low'] <= stop_loss, entry_candle['high'] >= take_profit
        else:
            sl_hit, tp_hit = entry_candle['high'] >= stop_loss, entry_candle['low'] <= take_profit
        
        if sl_hit and tp_hit:
            result = 'win' if (ob_type == 'bullish' and entry_candle['close'] >= entry_price) or (ob_type == 'bearish' and entry_candle['close'] <= entry_price) else 'loss'
            exit_price = take_profit if result == 'win' else stop_loss
        elif sl_hit:
            result, exit_price = 'loss', stop_loss
        elif tp_hit:
            result, exit_price = 'win', take_profit
        else:
            result, exit_price = None, None
            for i in range(entry_idx + 1, len(df)):
                candle = df.iloc[i]
                if ob_type == 'bullish':
                    if candle['low'] <= stop_loss: result, exit_price = 'loss', stop_loss; break
                    if candle['high'] >= take_profit: result, exit_price = 'win', take_profit; break
                else:
                    if candle['high'] >= stop_loss: result, exit_price = 'loss', stop_loss; break
                    if candle['low'] <= take_profit: result, exit_price = 'win', take_profit; break
            if result is None:
                exit_price = df.iloc[-1]['close']
                result = 'win' if (ob_type == 'bullish' and exit_price > entry_price) or (ob_type == 'bearish' and exit_price < entry_price) else 'loss'
        
        pnl_pct = ((exit_price - entry_price) / entry_price if ob_type == 'bullish' else (entry_price - exit_price) / entry_price) - FEE_RATE * 2
        risk_pct = risk / entry_price * 100
        trades.append({
            'timestamp': ob['timestamp'], 'type': ob_type, 'result': result,
            'entry_price': entry_price, 'stop_loss': stop_loss, 'take_profit': take_profit,
            'exit_price': exit_price, 'pnl_pct': pnl_pct, 'pnl_pct_10x': pnl_pct * leverage,
            'risk_pct': risk_pct, 'rr_ratio': rr_ratio
        })
    
    return trades

# 主程序
print("=" * 70)
print("📊 订单块回测 - 14ATR无止损筛选策略")
print("=" * 70)
print(f"\n入场规则: FVG 100% (k1边缘)")
print(f"止损规则: k1.close")
print(f"止损距离筛选: 无")
print(f"ATR周期: 14 | ATR倍数: 1.5x | FVG/ATR最小: 10%")
print(f"周期: 1小时 | 杠杆: 10x")
print()

df = fetch_klines(SYMBOL, INTERVAL, START_DATE, END_DATE)
print(f"BTC: ${df.iloc[0]['open']:,.0f} → ${df.iloc[-1]['close']:,.0f}")

order_blocks = identify_order_blocks(df)
bullish = [ob for ob in order_blocks if ob['type'] == 'bullish' and ob['pass_atr']]
bearish = [ob for ob in order_blocks if ob['type'] == 'bearish' and ob['pass_atr']]

print(f"看涨: {len(bullish)} 笔 | 看跌: {len(bearish)} 笔")

print("\n" + "=" * 70)
print("📊 回测结果")
print("=" * 70)

for rr in RR_RATIOS:
    print(f"\n【盈亏比 1:{rr}】")
    print(f"{'策略':<12} {'交易数':<8} {'胜率':<8} {'无杠杆':<12} {'10x杠杆':<12} {'平均风险':<10}")
    print("-" * 65)
    
    for name, obs in [('看涨', bullish), ('看跌', bearish), ('看涨+看跌', bullish + bearish)]:
        trades = simulate_trades(df, obs, rr)
        trades = sorted(trades, key=lambda x: x['timestamp'])
        if not trades: continue
        
        df_t = pd.DataFrame(trades)
        wins = len(df_t[df_t['result'] == 'win'])
        pnl = (1 + df_t['pnl_pct']).prod() - 1
        pnl_10x = (1 + df_t['pnl_pct_10x']).prod() - 1
        avg_risk = df_t['risk_pct'].mean()
        
        print(f"{name:<12} {len(trades):<8} {wins/len(trades)*100:.1f}%   {pnl*100:+.1f}%{'':<6} {pnl_10x*100:+.1f}%{'':<7} {avg_risk:.2f}%")

# 连续累积
print("\n" + "=" * 70)
print("📊 连续复利累积（RR=2，10x杠杆）")
print("=" * 70)

all_trades = sorted(simulate_trades(df, bullish + bearish, 2), key=lambda x: x['timestamp'])
df_all = pd.DataFrame(all_trades)
df_all['timestamp'] = pd.to_datetime(df_all['timestamp'])

cumulative = 1.0
print(f"\n{'时间点':<20} {'交易数':<8} {'账户':<12} {'收益':<12}")
print("-" * 50)
print(f"{'初始':<20} {'-':<8} 1.0000x    +0.0%")

for year in [2023, 2024, 2025, 2026]:
    year_trades = df_all[df_all['timestamp'].dt.year == year]
    if len(year_trades) == 0: continue
    for _, row in year_trades.iterrows():
        cumulative *= (1 + row['pnl_pct_10x'])
    print(f"{year}年末{'':<14} {len(year_trades):<8} {cumulative:.4f}x    {cumulative*100-100:+.1f}%")

# 保存
df_all.to_csv('/root/.openclaw/workspace/orderblock_adjusted_trades.csv', index=False)
print(f"\n📁 交易记录: orderblock_adjusted_trades.csv")

# 策略说明
print("\n" + "=" * 70)
print("📊 策略说明")
print("=" * 70)
print("""
【14ATR无止损筛选策略】

入场条件:
  1. k1为反向K线（看涨：阴线，看跌：阳线）
  2. k2收盘突破k1（收盘价突破）
  3. k3.close形成FVG缺口
  4. k2实体 >= ATR14 × 1.5
  5. FVG大小 >= ATR14 × 10%
  6. FVG最小100U

交易参数:
  - 入场价: k1边缘（FVG 100%）
  - 止损: k1.close
  - 推荐盈亏比: 1:2
  - 杠杆: 10x

历史回测（2023-2026）:
  - 三年收益: +1510%
  - 胜率: 48.9%
  - 平均风险: 0.52%
""")
