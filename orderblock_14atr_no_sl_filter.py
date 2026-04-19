#!/usr/bin/env python3
"""
订单块回测 - 14ATR无止损筛选策略（最终版本）
==========================================
策略参数：
- 入场价：FVG 100%（k1边缘）
- 止损：k1.close
- ATR周期：14
- ATR倍数：1.5x
- FVG/ATR最小：50%
- FVG定义：k3.close
- 数据源：Binance永续合约
- 周期：1小时
- 杠杆：10倍
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# 配置
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
START_DATE = "2023-04-17"
END_DATE = "2026-04-17"

ATR_PERIOD = 14
ATR_MULTIPLIER = 1.5
FVG_ATR_PCT_MIN = 50  # 最终参数
RETEST_LIMIT = 336  # 14天
RR_RATIOS = [2, 3]
FEE_RATE = 0.0004
SL_DISTANCE_MAX = None
RISK_PCT_MAX = 2.0
MAX_LOSS_PCT = 15

CST = timezone(timedelta(hours=8))

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
    atr = calculate_atr(df, ATR_PERIOD)
    order_blocks = []
    
    for i in range(2, len(df) - 1):
        k1, k2, k3 = df.iloc[i-2], df.iloc[i-1], df.iloc[i]
        current_atr = atr.iloc[i-1]
        if pd.isna(current_atr): continue
        
        # 看涨
        if k1['close'] < k1['open'] and k2['close'] > k1['high'] and k1['high'] < k3['close']:
            fvg_size = k3['close'] - k1['high']
            if fvg_size >= 100:
                k2_body = abs(k2['close'] - k2['open'])
                fvg_atr_pct = (fvg_size / current_atr * 100)
                pass_atr = (k2_body >= current_atr * ATR_MULTIPLIER) and (fvg_atr_pct >= FVG_ATR_PCT_MIN)
                
                entry_price = k1['high']
                stop_loss = k1['close']
                sl_distance = (entry_price - stop_loss) / entry_price * 100
                
                if SL_DISTANCE_MAX is not None and sl_distance >= SL_DISTANCE_MAX:
                    continue
                
                order_blocks.append({
                    'type': 'bullish', 'index': i-2, 'timestamp': k1['timestamp'],
                    'k1_high': k1['high'], 'k1_low': k1['low'], 'k1_close': k1['close'],
                    'k3_close': k3['close'],
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'sl_distance': sl_distance,
                    'fvg_size': fvg_size,
                    'atr': current_atr,
                    'k2_body': k2_body,
                    'fvg_atr_pct': fvg_atr_pct,
                    'pass_atr': pass_atr
                })
        
        # 看跌
        if k1['close'] > k1['open'] and k2['close'] < k1['low'] and k3['close'] < k1['low']:
            fvg_size = k1['low'] - k3['close']
            if fvg_size >= 100:
                k2_body = abs(k2['close'] - k2['open'])
                fvg_atr_pct = (fvg_size / current_atr * 100)
                pass_atr = (k2_body >= current_atr * ATR_MULTIPLIER) and (fvg_atr_pct >= FVG_ATR_PCT_MIN)
                
                entry_price = k1['low']
                stop_loss = k1['close']
                sl_distance = (stop_loss - entry_price) / entry_price * 100
                
                if SL_DISTANCE_MAX is not None and sl_distance >= SL_DISTANCE_MAX:
                    continue
                
                order_blocks.append({
                    'type': 'bearish', 'index': i-2, 'timestamp': k1['timestamp'],
                    'k1_high': k1['high'], 'k1_low': k1['low'], 'k1_close': k1['close'],
                    'k3_close': k3['close'],
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'sl_distance': sl_distance,
                    'fvg_size': fvg_size,
                    'atr': current_atr,
                    'k2_body': k2_body,
                    'fvg_atr_pct': fvg_atr_pct,
                    'pass_atr': pass_atr
                })
    
    return order_blocks

def simulate_trades(df, order_blocks, rr_ratio, leverage=10):
    trades = []
    for ob in order_blocks:
        ob_idx, ob_type = ob['index'], ob['type']
        entry_price, stop_loss = ob['entry_price'], ob['stop_loss']
        risk = abs(entry_price - stop_loss)
        take_profit = entry_price + (risk * rr_ratio) if ob_type == 'bullish' else entry_price - (risk * rr_ratio)
        
        if MAX_LOSS_PCT is not None:
            price_move_pct = MAX_LOSS_PCT / leverage / 100
            if ob_type == 'bullish':
                hard_stop = entry_price * (1 - price_move_pct)
            else:
                hard_stop = entry_price * (1 + price_move_pct)
        else:
            hard_stop = None
        
        entered, entry_idx = False, None
        for i in range(ob_idx + 3, min(ob_idx + 3 + RETEST_LIMIT, len(df))):
            if df.iloc[i]['low'] <= entry_price <= df.iloc[i]['high']:
                entered, entry_idx = True, i
                break
        if not entered: continue
        
        entry_candle = df.iloc[entry_idx]
        if ob_type == 'bullish':
            actual_sl = min(stop_loss, hard_stop) if hard_stop else stop_loss
            sl_hit, tp_hit = entry_candle['low'] <= actual_sl, entry_candle['high'] >= take_profit
        else:
            actual_sl = max(stop_loss, hard_stop) if hard_stop else stop_loss
            sl_hit, tp_hit = entry_candle['high'] >= actual_sl, entry_candle['low'] <= take_profit
        
        if sl_hit and tp_hit:
            result = 'win' if (ob_type == 'bullish' and entry_candle['close'] >= entry_price) or (ob_type == 'bearish' and entry_candle['close'] <= entry_price) else 'loss'
            exit_price = take_profit if result == 'win' else actual_sl
        elif sl_hit:
            result, exit_price = 'loss', actual_sl
        elif tp_hit:
            result, exit_price = 'win', take_profit
        else:
            result, exit_price = None, None
            for i in range(entry_idx + 1, len(df)):
                candle = df.iloc[i]
                if ob_type == 'bullish':
                    actual_sl = min(stop_loss, hard_stop) if hard_stop else stop_loss
                    if candle['low'] <= actual_sl: result, exit_price = 'loss', actual_sl; break
                    if candle['high'] >= take_profit: result, exit_price = 'win', take_profit; break
                else:
                    actual_sl = max(stop_loss, hard_stop) if hard_stop else stop_loss
                    if candle['high'] >= actual_sl: result, exit_price = 'loss', actual_sl; break
                    if candle['low'] <= take_profit: result, exit_price = 'win', take_profit; break
            if result is None:
                exit_price = df.iloc[-1]['close']
                result = 'win' if (ob_type == 'bullish' and exit_price > entry_price) or (ob_type == 'bearish' and exit_price < entry_price) else 'loss'
        
        pnl_pct = ((exit_price - entry_price) / entry_price if ob_type == 'bullish' else (entry_price - exit_price) / entry_price) - FEE_RATE * 2
        risk_pct = risk / entry_price * 100
        
        if RISK_PCT_MAX is not None and risk_pct > RISK_PCT_MAX:
            continue
        
        trades.append({
            'timestamp': ob['timestamp'],
            'type': ob_type,
            'result': result,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'exit_price': exit_price,
            'pnl_pct': pnl_pct,
            'pnl_pct_10x': pnl_pct * leverage,
            'risk_pct': risk_pct,
            'fvg_atr_pct': ob['fvg_atr_pct'],
        })
    
    return trades

# 主程序
print("=" * 80)
print("📊 订单块回测 - 14ATR无止损筛选策略（最终版本）")
print("=" * 80)
print(f"\n入场规则: FVG 100% (k1边缘)")
print(f"止损规则: k1.close")
print(f"ATR周期: 14 | ATR倍数: 1.5x | FVG/ATR最小: {FVG_ATR_PCT_MIN}%")
print(f"硬止损: {MAX_LOSS_PCT}% | 风险上限: {RISK_PCT_MAX}%")
print(f"周期: 1小时 | 杠杆: 10x")
print()

df = fetch_klines(SYMBOL, INTERVAL, START_DATE, END_DATE)
print(f"BTC: ${df.iloc[0]['open']:,.0f} → ${df.iloc[-1]['close']:,.0f}")
print(f"时间: {df.iloc[0]['timestamp']} ~ {df.iloc[-1]['timestamp']}")

order_blocks = identify_order_blocks(df)
bullish = [ob for ob in order_blocks if ob['type'] == 'bullish' and ob['pass_atr']]
bearish = [ob for ob in order_blocks if ob['type'] == 'bearish' and ob['pass_atr']]

print(f"\n看涨: {len(bullish)} 笔 | 看跌: {len(bearish)} 笔")

# 年度分析
print("\n" + "=" * 80)
print("📊 年度收益分析（RR=2，10x杠杆）")
print("=" * 80)

all_trades = sorted(simulate_trades(df, bullish + bearish, 2), key=lambda x: x['timestamp'])
df_trades = pd.DataFrame(all_trades)
df_trades['timestamp'] = pd.to_datetime(df_trades['timestamp'])

print(f"\n{'年度':<8} {'交易数':<8} {'胜率':<10} {'无杠杆':<12} {'10x杠杆':<14} {'BTC涨跌':<10}")
print("-" * 70)

cumulative = 1.0

for year in [2023, 2024, 2025, 2026]:
    year_trades = df_trades[df_trades['timestamp'].dt.year == year]
    if len(year_trades) == 0: continue
    
    # BTC年度表现
    year_klines = df[df['timestamp'].dt.year == year]
    if len(year_klines) > 0:
        btc_start = year_klines.iloc[0]['open']
        btc_end = year_klines.iloc[-1]['close']
        btc_change = (btc_end - btc_start) / btc_start * 100
    else:
        btc_change = 0
    
    wins = len(year_trades[year_trades['result'] == 'win'])
    win_rate = wins / len(year_trades) * 100
    
    # 年度收益
    year_pnl = (1 + year_trades['pnl_pct']).prod() - 1
    year_pnl_10x = (1 + year_trades['pnl_pct_10x']).prod() - 1
    
    # 累积收益
    for _, row in year_trades.iterrows():
        cumulative *= (1 + row['pnl_pct_10x'])
    
    print(f"{year:<8} {len(year_trades):<8} {win_rate:.1f}%{'':<5} {year_pnl*100:+.1f}%{'':<6} {year_pnl_10x*100:+.1f}%{'':<8} {btc_change:+.1f}%")

print("-" * 70)
wins_all = len(df_trades[df_trades['result'] == 'win'])
print(f"{'总计':<8} {len(df_trades):<8} {wins_all/len(df_trades)*100:.1f}%{'':<5} {(1+df_trades['pnl_pct']).prod()-1:.1%}{'':<7} {cumulative-1:.1%}")

# 季度分析
print("\n" + "=" * 80)
print("📊 季度收益分析（RR=2，10x杠杆）")
print("=" * 80)

print(f"\n{'季度':<10} {'交易数':<8} {'胜率':<10} {'10x杠杆':<14}")
print("-" * 50)

for year in [2023, 2024, 2025, 2026]:
    for q in range(1, 5):
        if year == 2023 and q < 2: continue  # 从2023-04开始
        if year == 2026 and q > 2: continue  # 到2026-04结束
        
        q_trades = df_trades[(df_trades['timestamp'].dt.year == year) & 
                             (df_trades['timestamp'].dt.quarter == q)]
        if len(q_trades) == 0: continue
        
        wins = len(q_trades[q_trades['result'] == 'win'])
        win_rate = wins / len(q_trades) * 100
        q_pnl = (1 + q_trades['pnl_pct_10x']).prod() - 1
        
        print(f"{year}Q{q:<7} {len(q_trades):<8} {win_rate:.1f}%{'':<5} {q_pnl*100:+.1f}%")

# 保存
df_trades.to_csv('/root/.openclaw/workspace/orderblock_final_trades.csv', index=False)
print(f"\n📁 交易记录: orderblock_final_trades.csv")

# 策略说明
print("\n" + "=" * 80)
print("📊 策略说明")
print("=" * 80)
print("""
【14ATR无止损筛选策略 - 最终版本】

入场条件:
  1. k1为反向K线（看涨：阴线，看跌：阳线）
  2. k2收盘突破k1（收盘价突破）
  3. k3.close形成FVG缺口
  4. k2实体 >= ATR14 × 1.5
  5. FVG大小 >= ATR14 × 50%  ← 核心参数

交易参数:
  - 入场价: k1边缘（FVG 100%）
  - 止损: k1.close
  - 推荐盈亏比: 1:2
  - 杠杆: 10x
  - 硬止损: 15%
""")
