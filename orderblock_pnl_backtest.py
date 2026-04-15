#!/usr/bin/env python3
"""
订单块交易回测 - 收益率计算
入场：FVG 50%
止损：k1.low（看涨）/ k1.high（看跌）
止盈：按盈亏比 1:2, 1:3, 1:5, 1:6
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime

# ============================================================
# 配置
# ============================================================

SYMBOL = "BTCUSDT"
INTERVAL = "1h"

# 交易参数
RETEST_LIMIT = 168  # 回踩时限（小时）
RR_RATIOS = [2, 3, 5, 6]  # 盈亏比
FEE_RATE = 0.0006  # 手续费 0.06%

# 筛选条件（可选）
ENABLE_FILTER = False
FILTER_K2_BODY_RATIO_MAX = 20
FILTER_FVG_RATIO_MIN = 0.5
FILTER_VOL_CHANGE_MIN = 0.8

# ============================================================
# 数据获取
# ============================================================

def fetch_klines(symbol, interval, start_date, end_date):
    """获取K线数据"""
    url = "https://api.binance.com/api/v3/klines"
    
    start_time = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_time = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)
    
    all_data = []
    current_start = start_time
    
    print(f"📥 获取 {symbol} {interval} 数据...")
    print(f"   时间范围: {start_date} ~ {end_date}")
    
    while current_start < end_time:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_time,
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
        
        print(f"   已获取 {len(all_data)} 根K线...", end='\r')
    
    print(f"   ✅ 共获取 {len(all_data)} 根K线")
    
    df = pd.DataFrame(all_data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])
    
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + pd.Timedelta(hours=8)
    
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    return df

# ============================================================
# 订单块识别
# ============================================================

def identify_order_blocks(df):
    """识别订单块"""
    
    order_blocks = []
    
    for i in range(2, len(df) - 1):
        k1 = df.iloc[i-2]
        k2 = df.iloc[i-1]
        k3 = df.iloc[i]
        
        # === 看涨订单块 ===
        if k1['close'] < k1['open']:
            if k2['close'] > k1['high']:
                if k1['high'] < k3['low']:
                    fvg_size = k3['low'] - k1['high']
                    
                    if fvg_size >= 100:
                        k1_body = abs(k1['close'] - k1['open'])
                        k2_body = abs(k2['close'] - k2['open'])
                        k1_range = k1['high'] - k1['low']
                        vol_change = (k2['volume'] - k1['volume']) / k1['volume'] if k1['volume'] > 0 else 0
                        
                        order_blocks.append({
                            'type': 'bullish',
                            'index': i - 2,
                            'timestamp': k1['timestamp'],
                            'k1_high': k1['high'],
                            'k1_low': k1['low'],
                            'k3_low': k3['low'],
                            'fvg_size': fvg_size,
                            'entry_price': (k1['high'] + k3['low']) / 2,  # FVG 50%
                            'stop_loss': k1['low'],
                            'k2_body_k1_body': k2_body / k1_body if k1_body > 0 else 0,
                            'fvg_size_k1_range': fvg_size / k1_range if k1_range > 0 else 0,
                            'vol_change_1_2': vol_change,
                        })
        
        # === 看跌订单块 ===
        if k1['close'] > k1['open']:
            if k2['close'] < k1['low']:
                if k1['low'] > k3['high']:
                    fvg_size = k1['low'] - k3['high']
                    
                    if fvg_size >= 100:
                        k1_body = abs(k1['close'] - k1['open'])
                        k2_body = abs(k2['close'] - k2['open'])
                        k1_range = k1['high'] - k1['low']
                        vol_change = (k2['volume'] - k1['volume']) / k1['volume'] if k1['volume'] > 0 else 0
                        
                        order_blocks.append({
                            'type': 'bearish',
                            'index': i - 2,
                            'timestamp': k1['timestamp'],
                            'k1_high': k1['high'],
                            'k1_low': k1['low'],
                            'k3_high': k3['high'],
                            'fvg_size': fvg_size,
                            'entry_price': (k1['low'] + k3['high']) / 2,  # FVG 50%
                            'stop_loss': k1['high'],
                            'k2_body_k1_body': k2_body / k1_body if k1_body > 0 else 0,
                            'fvg_size_k1_range': fvg_size / k1_range if k1_range > 0 else 0,
                            'vol_change_1_2': vol_change,
                        })
    
    return order_blocks

# ============================================================
# 交易模拟
# ============================================================

def simulate_trades(df, order_blocks, rr_ratio, retest_limit=168, fee_rate=0.0006):
    """模拟交易"""
    
    trades = []
    
    for ob in order_blocks:
        ob_idx = ob['index']
        ob_type = ob['type']
        
        entry_price = ob['entry_price']
        stop_loss = ob['stop_loss']
        risk = abs(entry_price - stop_loss)
        
        # 计算止盈
        if ob_type == 'bullish':
            take_profit = entry_price + (risk * rr_ratio)
        else:
            take_profit = entry_price - (risk * rr_ratio)
        
        # 搜索回踩入场
        start_idx = ob_idx + 3
        end_idx = min(start_idx + retest_limit, len(df))
        
        entered = False
        entry_idx = None
        
        for i in range(start_idx, end_idx):
            candle = df.iloc[i]
            
            # 检查是否触及入场价
            if candle['low'] <= entry_price <= candle['high']:
                entered = True
                entry_idx = i
                break
        
        if not entered:
            continue
        
        # 模拟交易结果
        result = None
        exit_price = None
        
        for i in range(entry_idx + 1, len(df)):
            candle = df.iloc[i]
            
            if ob_type == 'bullish':
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
            if ob_type == 'bullish':
                result = 'win' if exit_price > entry_price else 'loss'
            else:
                result = 'win' if exit_price < entry_price else 'loss'
        
        # 计算 PnL
        if ob_type == 'bullish':
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
        
        pnl_pct -= fee_rate * 2
        
        trades.append({
            'timestamp': ob['timestamp'],
            'type': ob_type,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'exit_price': exit_price,
            'result': result,
            'pnl_pct': pnl_pct,
            'rr_ratio': rr_ratio,
        })
    
    return trades

# ============================================================
# 统计
# ============================================================

def calculate_stats(trades, rr_ratio, title=""):
    """计算统计数据"""
    
    if not trades:
        return None
    
    df_trades = pd.DataFrame(trades)
    
    wins = df_trades[df_trades['result'] == 'win']
    losses = df_trades[df_trades['result'] == 'loss']
    
    total = len(trades)
    win_count = len(wins)
    win_rate = win_count / total * 100 if total > 0 else 0
    
    total_pnl = df_trades['pnl_pct'].sum() * 100
    
    # 最大回撤
    cumulative = (1 + df_trades['pnl_pct']).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = drawdown.min() * 100 if len(drawdown) > 0 else 0
    
    return {
        'rr_ratio': rr_ratio,
        'total_trades': total,
        'win_count': win_count,
        'loss_count': len(losses),
        'win_rate': round(win_rate, 1),
        'total_pnl_pct': round(total_pnl, 2),
        'max_drawdown_pct': round(max_drawdown, 2),
        'avg_pnl_pct': round(df_trades['pnl_pct'].mean() * 100, 4),
    }

# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 70)
    print("📊 订单块交易回测 - 收益率计算")
    print("=" * 70)
    print(f"\n入场条件: FVG 50%")
    print(f"止损: k1.low（看涨）/ k1.high（看跌）")
    print(f"盈亏比: {RR_RATIOS}")
    print(f"回踩时限: {RETEST_LIMIT}h")
    print(f"手续费: {FEE_RATE * 100}%")
    
    if ENABLE_FILTER:
        print(f"\n筛选条件:")
        print(f"  k2实体/k1实体 < {FILTER_K2_BODY_RATIO_MAX}")
        print(f"  FVG/k1振幅 > {FILTER_FVG_RATIO_MIN}")
        print(f"  成交量变化 > {FILTER_VOL_CHANGE_MIN * 100}%")
    print()
    
    # 获取数据
    df = fetch_klines(SYMBOL, INTERVAL, "2024-01-01", "2026-01-01")
    print(f"📅 数据范围: {df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]}")
    print()
    
    # 识别订单块
    print("🔍 识别订单块...")
    order_blocks = identify_order_blocks(df)
    print(f"✅ 找到 {len(order_blocks)} 个订单块")
    print(f"   看涨: {sum(1 for ob in order_blocks if ob['type'] == 'bullish')}")
    print(f"   看跌: {sum(1 for ob in order_blocks if ob['type'] == 'bearish')}")
    print()
    
    # 应用筛选
    if ENABLE_FILTER:
        print("🔍 应用筛选条件...")
        order_blocks = [ob for ob in order_blocks if 
                       ob['k2_body_k1_body'] < FILTER_K2_BODY_RATIO_MAX and
                       ob['fvg_size_k1_range'] > FILTER_FVG_RATIO_MIN and
                       ob['vol_change_1_2'] > FILTER_VOL_CHANGE_MIN]
        print(f"✅ 筛选后 {len(order_blocks)} 个订单块")
        print(f"   看涨: {sum(1 for ob in order_blocks if ob['type'] == 'bullish')}")
        print(f"   看跌: {sum(1 for ob in order_blocks if ob['type'] == 'bearish')}")
        print()
    
    # 分开看涨看跌
    bullish_obs = [ob for ob in order_blocks if ob['type'] == 'bullish']
    bearish_obs = [ob for ob in order_blocks if ob['type'] == 'bearish']
    
    # 测试不同盈亏比
    print("=" * 70)
    print("📊 回测结果")
    print("=" * 70)
    
    for ob_type, obs in [('看涨', bullish_obs), ('看跌', bearish_obs)]:
        if not obs:
            continue
        
        print(f"\n{'='*50}")
        print(f"📈 {ob_type}订单块")
        print(f"{'='*50}")
        
        print(f"\n{'盈亏比':<8} {'交易数':<8} {'胜率':<10} {'总收益':<12} {'最大回撤':<12}")
        print("-" * 50)
        
        for rr in RR_RATIOS:
            trades = simulate_trades(df, obs, rr, RETEST_LIMIT, FEE_RATE)
            stats = calculate_stats(trades, rr)
            
            if stats:
                print(f"1:{rr:<7} {stats['total_trades']:<8} {stats['win_rate']}%{'':<5} {stats['total_pnl_pct']}%{'':<6} {stats['max_drawdown_pct']}%")
    
    # 综合测试（看涨 + 看跌）
    print(f"\n{'='*50}")
    print("📊 综合结果（看涨+看跌）")
    print(f"{'='*50}")
    
    print(f"\n{'盈亏比':<8} {'交易数':<8} {'胜率':<10} {'总收益':<12} {'最大回撤':<12}")
    print("-" * 50)
    
    for rr in RR_RATIOS:
        all_trades = []
        
        for obs in [bullish_obs, bearish_obs]:
            trades = simulate_trades(df, obs, rr, RETEST_LIMIT, FEE_RATE)
            all_trades.extend(trades)
        
        stats = calculate_stats(all_trades, rr)
        
        if stats:
            print(f"1:{rr:<7} {stats['total_trades']:<8} {stats['win_rate']}%{'':<5} {stats['total_pnl_pct']}%{'':<6} {stats['max_drawdown_pct']}%")
    
    print("\n" + "=" * 70)
    print("📊 说明")
    print("=" * 70)
    print("- 总收益 = 所有交易盈亏百分比之和")
    print("- 最大回撤 = 账户净值从最高点到最低点的最大跌幅")
    print("- 手续费已扣除（每笔交易 0.12%）")

if __name__ == "__main__":
    main()
