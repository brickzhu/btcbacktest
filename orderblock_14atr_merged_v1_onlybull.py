#!/usr/bin/env python3
"""
订单块回测 - K线合并法 V1（原始版本）
==========================================
特点：只识别看涨信号，收益夸张（+579,050%）

此版本作为参考保留，不做修改。

合并规则（原始）：只合并同向K线，不考虑包含关系
看跌定义（原始）：k1['low'] 导致几乎无法形成看跌订单块
参数：FVG/ATR ≥ 60%，回踩时限 3天
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
FVG_ATR_PCT_MIN = 60
RETEST_LIMIT = 72  # 3天
RR_RATIOS = [2, 3]
FEE_RATE = 0.0004
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
        if not data:
            break
        all_data.extend(data)
        current_start = data[-1][0] + 3600000
        if len(data) < 1500:
            break
    
    print(f"   ✅ 共获取 {len(all_data)} 根K线")
    
    df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + pd.Timedelta(hours=8)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]


def calculate_atr(df, period=14):
    tr = pd.concat([df['high'] - df['low'], 
                    abs(df['high'] - df['close'].shift(1)), 
                    abs(df['low'] - df['close'].shift(1))], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def merge_klines_v1(df):
    """
    原始合并逻辑：只合并同向K线（不考虑包含关系）
    """
    merged = []
    i = 0
    n = len(df)
    
    while i < n:
        row = df.iloc[i]
        direction = 'up' if row['close'] > row['open'] else 'down'
        
        start_idx = i
        merged_open = row['open']
        merged_high = row['high']
        merged_low = row['low']
        merged_close = row['close']
        
        j = i + 1
        while j < n:
            next_row = df.iloc[j]
            next_direction = 'up' if next_row['close'] > next_row['open'] else 'down'
            
            if next_direction == direction:
                merged_high = max(merged_high, next_row['high'])
                merged_low = min(merged_low, next_row['low'])
                merged_close = next_row['close']
                j += 1
            else:
                break
        
        merged.append({
            'start_idx': start_idx,
            'end_idx': j - 1,
            'timestamp': df.iloc[start_idx]['timestamp'],
            'open': merged_open,
            'high': merged_high,
            'low': merged_low,
            'close': merged_close,
            'direction': direction
        })
        
        i = j
    
    return merged


def identify_order_blocks_merged_v1(df, merged_klines):
    """
    原始订单块识别：看跌用 k1['low'] 导致几乎无法形成
    """
    atr = calculate_atr(df, ATR_PERIOD)
    order_blocks = []
    
    for i in range(1, len(merged_klines) - 1):
        k1 = merged_klines[i - 1]
        k2 = merged_klines[i]
        
        k1_end_idx = k1['end_idx']
        if k1_end_idx >= len(atr):
            continue
        current_atr = atr.iloc[k1_end_idx]
        if pd.isna(current_atr):
            continue
        
        # 看涨订单块：k1下跌，k2上涨突破
        if k1['direction'] == 'down' and k2['direction'] == 'up':
            if k2['close'] > k1['high']:
                fvg_size = k2['close'] - k1['high']
                if fvg_size >= 100:
                    k2_body = abs(k2['close'] - k2['open'])
                    fvg_atr_pct = (fvg_size / current_atr * 100)
                    pass_atr = (k2_body >= current_atr * ATR_MULTIPLIER) and (fvg_atr_pct >= FVG_ATR_PCT_MIN)
                    
                    entry_price = k1['high']
                    stop_loss = k1['close']
                    
                    order_blocks.append({
                        'type': 'bullish',
                        'start_idx': k1['start_idx'],
                        'end_idx': k2['end_idx'],
                        'timestamp': k1['timestamp'],
                        'entry_price': entry_price,
                        'stop_loss': stop_loss,
                        'fvg_size': fvg_size,
                        'atr': current_atr,
                        'k2_body': k2_body,
                        'fvg_atr_pct': fvg_atr_pct,
                        'pass_atr': pass_atr
                    })
        
        # 看跌订单块（原始定义，导致几乎无法形成）
        if k1['direction'] == 'up' and k2['direction'] == 'down':
            if k2['close'] < k1['low']:  # 原始：用 k1['low']
                fvg_size = k1['low'] - k2['close']
                if fvg_size >= 100:
                    k2_body = abs(k2['close'] - k2['open'])
                    fvg_atr_pct = (fvg_size / current_atr * 100)
                    pass_atr = (k2_body >= current_atr * ATR_MULTIPLIER) and (fvg_atr_pct >= FVG_ATR_PCT_MIN)
                    
                    entry_price = k1['low']
                    stop_loss = k1['close']
                    
                    order_blocks.append({
                        'type': 'bearish',
                        'start_idx': k1['start_idx'],
                        'end_idx': k2['end_idx'],
                        'timestamp': k1['timestamp'],
                        'entry_price': entry_price,
                        'stop_loss': stop_loss,
                        'fvg_size': fvg_size,
                        'atr': current_atr,
                        'k2_body': k2_body,
                        'fvg_atr_pct': fvg_atr_pct,
                        'pass_atr': pass_atr
                    })
    
    return order_blocks


def simulate_trades(df, order_blocks, rr_ratio, leverage=10):
    trades = []
    last_exit_idx = -1
    
    for ob in order_blocks:
        ob_idx = ob['end_idx']
        ob_type = ob['type']
        entry_price = ob['entry_price']
        stop_loss = ob['stop_loss']
        risk = abs(entry_price - stop_loss)
        take_profit = entry_price + (risk * rr_ratio) if ob_type == 'bullish' else entry_price - (risk * rr_ratio)
        
        if MAX_LOSS_PCT is not None:
            price_move_pct = MAX_LOSS_PCT / leverage / 100
            hard_stop = entry_price * (1 - price_move_pct) if ob_type == 'bullish' else entry_price * (1 + price_move_pct)
        else:
            hard_stop = None
        
        search_start = max(ob_idx + 1, last_exit_idx + 1)
        entered = False
        entry_idx = None
        for i in range(search_start, min(ob_idx + 1 + RETEST_LIMIT, len(df))):
            if df.iloc[i]['low'] <= entry_price <= df.iloc[i]['high']:
                entered = True
                entry_idx = i
                break
        
        if not entered:
            continue
        
        entry_candle = df.iloc[entry_idx]
        if ob_type == 'bullish':
            actual_sl = min(stop_loss, hard_stop) if hard_stop else stop_loss
            sl_hit = entry_candle['low'] <= actual_sl
            tp_hit = entry_candle['high'] >= take_profit
        else:
            actual_sl = max(stop_loss, hard_stop) if hard_stop else stop_loss
            sl_hit = entry_candle['high'] >= actual_sl
            tp_hit = entry_candle['low'] <= take_profit
        
        if sl_hit and tp_hit:
            result = 'win' if (ob_type == 'bullish' and entry_candle['close'] >= entry_price) or (ob_type == 'bearish' and entry_candle['close'] <= entry_price) else 'loss'
            exit_price = take_profit if result == 'win' else actual_sl
            exit_idx = entry_idx
        elif sl_hit:
            result, exit_price, exit_idx = 'loss', actual_sl, entry_idx
        elif tp_hit:
            result, exit_price, exit_idx = 'win', take_profit, entry_idx
        else:
            result, exit_price, exit_idx = None, None, None
            for i in range(entry_idx + 1, len(df)):
                candle = df.iloc[i]
                if ob_type == 'bullish':
                    actual_sl = min(stop_loss, hard_stop) if hard_stop else stop_loss
                    if candle['low'] <= actual_sl:
                        result, exit_price, exit_idx = 'loss', actual_sl, i
                        break
                    if candle['high'] >= take_profit:
                        result, exit_price, exit_idx = 'win', take_profit, i
                        break
                else:
                    actual_sl = max(stop_loss, hard_stop) if hard_stop else stop_loss
                    if candle['high'] >= actual_sl:
                        result, exit_price, exit_idx = 'loss', actual_sl, i
                        break
                    if candle['low'] <= take_profit:
                        result, exit_price, exit_idx = 'win', take_profit, i
                        break
            
            if result is None:
                exit_price = df.iloc[-1]['close']
                exit_idx = len(df) - 1
                result = 'win' if (ob_type == 'bullish' and exit_price > entry_price) or (ob_type == 'bearish' and exit_price < entry_price) else 'loss'
        
        last_exit_idx = exit_idx
        
        pnl_pct = ((exit_price - entry_price) / entry_price if ob_type == 'bullish' else (entry_price - exit_price) / entry_price) - FEE_RATE * 2
        risk_pct = risk / entry_price * 100
        
        if RISK_PCT_MAX is not None and risk_pct > RISK_PCT_MAX:
            continue
        
        trades.append({
            'timestamp': ob['timestamp'],
            'type': ob_type,
            'result': result,
            'pnl_pct': pnl_pct,
            'pnl_pct_10x': pnl_pct * leverage,
            'risk_pct': risk_pct,
            'fvg_atr_pct': ob['fvg_atr_pct'],
        })
    
    return trades


# 主程序
print("=" * 80)
print("📊 订单块回测 - K线合并法 V1（原始版本，只看涨）")
print("=" * 80)
print(f"\n⚠️ 此版本作为参考保留，不做修改")
print(f"\n特点：")
print(f"  - 合并逻辑：只合并同向K线（无包含关系）")
print(f"  - 看跌定义：用 k1['low'] 导致几乎无法形成看跌订单块")
print(f"  - 结果：只识别看涨信号，收益夸张（+579,050%）")
print()
print(f"入场规则: FVG 100% (k1边缘)")
print(f"止损规则: k1.close")
print(f"ATR周期: 14 | ATR倍数: 1.5x | FVG/ATR最小: {FVG_ATR_PCT_MIN}%")
print(f"回踩时限: {RETEST_LIMIT}小时（{RETEST_LIMIT//24}天）")
print(f"仓位限制: 同一时间只持有一笔，平仓后才能开新仓")
print(f"周期: 1小时 | 杠杆: 10x")
print()

df = fetch_klines(SYMBOL, INTERVAL, START_DATE, END_DATE)
print(f"BTC: ${df.iloc[0]['open']:,.0f} → ${df.iloc[-1]['close']:,.0f}")

merged_klines = merge_klines_v1(df)
print(f"\n🔄 合并K线...")
print(f"   原始K线: {len(df)} 根")
print(f"   合并后: {len(merged_klines)} 根")

order_blocks = identify_order_blocks_merged_v1(df, merged_klines)
bullish = [ob for ob in order_blocks if ob['type'] == 'bullish' and ob['pass_atr']]
bearish = [ob for ob in order_blocks if ob['type'] == 'bearish' and ob['pass_atr']]

print(f"\n看涨订单块(通过筛选): {len(bullish)} 笔")
print(f"看跌订单块(通过筛选): {len(bearish)} 笔")

all_trades = sorted(simulate_trades(df, bullish + bearish, 2), key=lambda x: x['timestamp'])
df_trades = pd.DataFrame(all_trades)
df_trades['timestamp'] = pd.to_datetime(df_trades['timestamp'])

bull_trades = len(df_trades[df_trades['type'] == 'bullish'])
bear_trades = len(df_trades[df_trades['type'] == 'bearish'])

print(f"\n实际交易:")
print(f"  看涨: {bull_trades} 笔")
print(f"  看跌: {bear_trades} 笔")

wins = len(df_trades[df_trades['result'] == 'win'])
pnl_10x = (1 + df_trades['pnl_pct_10x']).prod() - 1

print(f"\n{'='*60}")
print(f"三年收益（10x杠杆）: {pnl_10x*100:+,.0f}%")
print(f"胜率: {wins/len(df_trades)*100:.1f}%")
print(f"{'='*60}")

df_trades.to_csv('/root/.openclaw/workspace/orderblock_merged_v1_trades.csv', index=False)
print(f"\n📁 交易记录: orderblock_merged_v1_trades.csv")