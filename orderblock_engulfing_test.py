#!/usr/bin/env python3
"""
Order Block 回测 - 吞没确认测试
只测试 engulfing 方式，对比之前的结果
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime

# 配置
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
DAYS = 365
RETEST_LIMIT = 48
FEE_RATE = 0.0006

def fetch_klines(symbol, interval, days):
    """获取K线数据"""
    url = "https://api.binance.com/api/v3/klines"
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    
    all_data = []
    current_start = start_time
    
    print(f"📥 获取 {symbol} {interval} 数据，最近 {days} 天...")
    
    while current_start < end_time:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "limit": 1000
        }
        response = requests.get(url, params=params)
        data = response.json()
        if not data:
            break
        all_data.extend(data)
        current_start = data[-1][0] + 60000
        if len(data) < 1000:
            break
    
    df = pd.DataFrame(all_data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    df.set_index('timestamp', inplace=True)
    
    print(f"✅ 获取 {len(df)} 根K线")
    return df

def calculate_atr(df, period=14):
    """计算ATR"""
    high = df['high']
    low = df['low']
    close = df['close'].shift(1)
    tr = pd.concat([high - low, abs(high - close), abs(low - close)], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def identify_order_blocks_engulfing(df):
    """识别订单块 - 吞没确认方式"""
    atr = calculate_atr(df)
    order_blocks = []
    
    for i in range(2, len(df)):
        k1 = df.iloc[i-2]  # 第1根K线 (反向)
        k2 = df.iloc[i-1]  # 第2根K线 (突破)
        k3 = df.iloc[i]    # 当前K线
        
        # 看涨订单块
        if k1['close'] < k1['open']:  # 第1根下跌
            if k2['close'] > k1['high'] and k2['low'] < k1['low']:  # 吞没
                if k1['high'] < k3['low']:  # FVG
                    fvg_size = k3['low'] - k1['high']
                    if fvg_size > 0:
                        order_blocks.append({
                            'type': 'bullish',
                            'index': i - 2,
                            'timestamp': df.index[i-2],
                            'ob_high': k1['high'],
                            'ob_low': k1['low'],
                            'fvg_high': k3['low'],
                            'fvg_low': k1['high'],
                            'fvg_size': fvg_size,
                            'entry_price': (k1['high'] + k3['low']) / 2,
                            'stop_loss': k1['low'],
                            'atr': atr.iloc[i-1]
                        })
        
        # 看跌订单块
        if k1['close'] > k1['open']:  # 第1根上涨
            if k2['close'] < k1['low'] and k2['high'] > k1['high']:  # 吞没
                if k1['low'] > k3['high']:  # FVG
                    fvg_size = k1['low'] - k3['high']
                    if fvg_size > 0:
                        order_blocks.append({
                            'type': 'bearish',
                            'index': i - 2,
                            'timestamp': df.index[i-2],
                            'ob_high': k1['high'],
                            'ob_low': k1['low'],
                            'fvg_high': k1['low'],
                            'fvg_low': k3['high'],
                            'fvg_size': fvg_size,
                            'entry_price': (k1['low'] + k3['high']) / 2,
                            'stop_loss': k1['high'],
                            'atr': atr.iloc[i-1]
                        })
    
    return order_blocks

def simulate_trades(df, order_blocks, rr_ratio=3.0):
    """模拟交易"""
    trades = []
    
    for ob in order_blocks:
        start_idx = ob['index'] + 3
        end_idx = min(start_idx + RETEST_LIMIT, len(df))
        
        entry_price = ob['entry_price']
        stop_loss = ob['stop_loss']
        risk = abs(entry_price - stop_loss)
        
        if ob['type'] == 'bullish':
            take_profit = entry_price + (risk * rr_ratio)
        else:
            take_profit = entry_price - (risk * rr_ratio)
        
        # 检查回踩
        entered = False
        entry_idx = None
        
        for i in range(start_idx, end_idx):
            candle = df.iloc[i]
            if candle['low'] <= entry_price <= candle['high']:
                entered = True
                entry_idx = i
                break
        
        if not entered:
            continue
        
        # 检查结果
        result = None
        exit_price = None
        
        for i in range(entry_idx + 1, len(df)):
            candle = df.iloc[i]
            
            if ob['type'] == 'bullish':
                if candle['low'] <= stop_loss:
                    result = 'loss'
                    exit_price = stop_loss
                    break
                if candle['high'] >= take_profit:
                    result = 'win'
                    exit_price = take_profit
                    break
            else:
                if candle['high'] >= stop_loss:
                    result = 'loss'
                    exit_price = stop_loss
                    break
                if candle['low'] <= take_profit:
                    result = 'win'
                    exit_price = take_profit
                    break
        
        if result is None:
            exit_price = df.iloc[-1]['close']
            if ob['type'] == 'bullish':
                result = 'win' if exit_price > entry_price else 'loss'
            else:
                result = 'win' if exit_price < entry_price else 'loss'
        
        # 计算PnL
        if ob['type'] == 'bullish':
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
        
        pnl_pct -= FEE_RATE * 2
        
        trades.append({
            'timestamp': ob['timestamp'],
            'type': ob['type'],
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'exit_price': exit_price,
            'result': result,
            'pnl_pct': pnl_pct,
            'rr_ratio': rr_ratio
        })
    
    return trades

def calculate_stats(trades):
    """计算统计"""
    if not trades:
        return None
    
    df_trades = pd.DataFrame(trades)
    wins = df_trades[df_trades['result'] == 'win']
    losses = df_trades[df_trades['result'] == 'loss']
    
    total = len(trades)
    win_count = len(wins)
    win_rate = win_count / total * 100 if total > 0 else 0
    
    avg_win = wins['pnl_pct'].mean() if len(wins) > 0 else 0
    avg_loss = abs(losses['pnl_pct'].mean()) if len(losses) > 0 else 0
    
    total_pnl = df_trades['pnl_pct'].sum() * 100
    
    cumulative = (1 + df_trades['pnl_pct']).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    max_dd = drawdown.min() * 100 if len(drawdown) > 0 else 0
    
    actual_rr = avg_win / avg_loss if avg_loss > 0 else 0
    
    return {
        'total_trades': total,
        'win_count': win_count,
        'loss_count': len(losses),
        'win_rate': round(win_rate, 2),
        'avg_win_pct': round(avg_win * 100, 4),
        'avg_loss_pct': round(avg_loss * 100, 4),
        'actual_rr': round(actual_rr, 2),
        'total_pnl_pct': round(total_pnl, 2),
        'max_drawdown_pct': round(max_dd, 2)
    }

def main():
    print("=" * 60)
    print("📊 Order Block 回测 - 吞没确认 (Engulfing)")
    print("=" * 60)
    print()
    
    df = fetch_klines(SYMBOL, INTERVAL, DAYS)
    print(f"\n📅 数据范围: {df.index[0]} ~ {df.index[-1]}")
    
    # 识别订单块
    print("\n🔍 识别订单块 (吞没确认方式)...")
    ob_list = identify_order_blocks_engulfing(df)
    print(f"   找到 {len(ob_list)} 个订单块")
    
    # 测试不同盈亏比
    print("\n📊 测试不同盈亏比...")
    print("-" * 60)
    
    for rr in [2.0, 3.0, 4.0, 5.0]:
        trades = simulate_trades(df, ob_list, rr_ratio=rr)
        stats = calculate_stats(trades)
        
        if stats:
            print(f"\n盈亏比 1:{rr}")
            print(f"  交易次数: {stats['total_trades']}")
            print(f"  胜率: {stats['win_rate']}%")
            print(f"  实际盈亏比: {stats['actual_rr']}")
            print(f"  总收益: {stats['total_pnl_pct']}%")
            print(f"  最大回撤: {stats['max_drawdown_pct']}%")

if __name__ == "__main__":
    main()
