#!/usr/bin/env python3
"""
订单块筛选策略对比回测
对比两种筛选策略在过去一年的表现：
1. 新结论筛选：k2实体/k1实体 < 20, FVG/k1振幅 > 0.5, 成交量变化 > 80%
2. ATR策略筛选：ATR 1.5x确认, FVG/ATR ≥ 10%
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ============================================================
# 配置
# ============================================================

SYMBOL = "BTCUSDT"
INTERVAL = "1h"

# 回测时间：过去一年
END_DATE = datetime.now().strftime("%Y-%m-%d")
START_DATE = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

# 交易参数
RETEST_LIMIT = 168
RR_RATIOS = [2, 3, 5, 6]
FEE_RATE = 0.0006

# 策略1：新结论筛选
STRATEGY1 = {
    'name': '新结论筛选',
    'k2_body_ratio_max': 20,
    'fvg_ratio_min': 0.5,
    'vol_change_min': 0.8,
}

# 策略2：ATR筛选
STRATEGY2 = {
    'name': 'ATR筛选',
    'atr_multiplier': 1.5,
    'fvg_atr_pct_min': 10,
}

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
# 技术指标
# ============================================================

def calculate_atr(df, period=14):
    """计算ATR"""
    high = df['high']
    low = df['low']
    close = df['close'].shift(1)
    
    tr1 = high - low
    tr2 = abs(high - close)
    tr3 = abs(low - close)
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    return atr

def calculate_avg_body(df, period=20):
    """计算平均实体"""
    body = abs(df['close'] - df['open'])
    return body.rolling(window=period).mean()

# ============================================================
# 订单块识别
# ============================================================

def identify_order_blocks(df):
    """识别所有订单块（带完整特征）"""
    
    atr = calculate_atr(df)
    avg_body = calculate_avg_body(df)
    
    order_blocks = []
    
    for i in range(2, len(df) - 1):
        k1 = df.iloc[i-2]
        k2 = df.iloc[i-1]
        k3 = df.iloc[i]
        
        current_atr = atr.iloc[i-1]
        
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
                        fvg_atr_pct = (fvg_size / current_atr * 100) if current_atr > 0 else 0
                        
                        order_blocks.append({
                            'type': 'bullish',
                            'index': i - 2,
                            'timestamp': k1['timestamp'],
                            'k1_high': k1['high'],
                            'k1_low': k1['low'],
                            'k3_low': k3['low'],
                            'fvg_size': fvg_size,
                            'entry_price': (k1['high'] + k3['low']) / 2,
                            'stop_loss': k1['low'],
                            'k2_body_k1_body': k2_body / k1_body if k1_body > 0 else 0,
                            'fvg_size_k1_range': fvg_size / k1_range if k1_range > 0 else 0,
                            'vol_change_1_2': vol_change,
                            'atr': current_atr,
                            'fvg_atr_pct': fvg_atr_pct,
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
                        fvg_atr_pct = (fvg_size / current_atr * 100) if current_atr > 0 else 0
                        
                        order_blocks.append({
                            'type': 'bearish',
                            'index': i - 2,
                            'timestamp': k1['timestamp'],
                            'k1_high': k1['high'],
                            'k1_low': k1['low'],
                            'k3_high': k3['high'],
                            'fvg_size': fvg_size,
                            'entry_price': (k1['low'] + k3['high']) / 2,
                            'stop_loss': k1['high'],
                            'k2_body_k1_body': k2_body / k1_body if k1_body > 0 else 0,
                            'fvg_size_k1_range': fvg_size / k1_range if k1_range > 0 else 0,
                            'vol_change_1_2': vol_change,
                            'atr': current_atr,
                            'fvg_atr_pct': fvg_atr_pct,
                        })
    
    return order_blocks

# ============================================================
# 筛选策略
# ============================================================

def filter_strategy1(order_blocks, params):
    """策略1：新结论筛选"""
    
    filtered = []
    for ob in order_blocks:
        cond1 = ob['k2_body_k1_body'] < params['k2_body_ratio_max']
        cond2 = ob['fvg_size_k1_range'] > params['fvg_ratio_min']
        cond3 = ob['vol_change_1_2'] > params['vol_change_min']
        
        if cond1 and cond2 and cond3:
            filtered.append(ob)
    
    return filtered

def filter_strategy2(order_blocks, df, params):
    """策略2：ATR筛选（需要检查k2实体是否满足ATR条件）"""
    
    avg_body = calculate_avg_body(df)
    
    filtered = []
    for ob in order_blocks:
        ob_idx = ob['index']
        k2 = df.iloc[ob_idx + 1]
        k2_body = abs(k2['close'] - k2['open'])
        
        # k2实体 >= ATR * 1.5
        atr_threshold = ob['atr'] * params['atr_multiplier']
        cond1 = k2_body >= atr_threshold
        
        # FVG/ATR >= 10%
        cond2 = ob['fvg_atr_pct'] >= params['fvg_atr_pct_min']
        
        if cond1 and cond2:
            filtered.append(ob)
    
    return filtered

# ============================================================
# 交易模拟
# ============================================================

def simulate_trades(df, order_blocks, rr_ratio):
    """模拟交易"""
    
    trades = []
    
    for ob in order_blocks:
        ob_idx = ob['index']
        ob_type = ob['type']
        
        entry_price = ob['entry_price']
        stop_loss = ob['stop_loss']
        risk = abs(entry_price - stop_loss)
        
        if ob_type == 'bullish':
            take_profit = entry_price + (risk * rr_ratio)
        else:
            take_profit = entry_price - (risk * rr_ratio)
        
        # 搜索回踩
        start_idx = ob_idx + 3
        end_idx = min(start_idx + RETEST_LIMIT, len(df))
        
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
        
        if ob_type == 'bullish':
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
        
        pnl_pct -= FEE_RATE * 2
        
        trades.append({
            'type': ob_type,
            'result': result,
            'pnl_pct': pnl_pct,
        })
    
    return trades

# ============================================================
# 统计
# ============================================================

def calculate_stats(trades, rr_ratio):
    """计算统计"""
    
    if not trades:
        return None
    
    df = pd.DataFrame(trades)
    
    wins = df[df['result'] == 'win']
    total = len(trades)
    win_rate = len(wins) / total * 100 if total > 0 else 0
    total_pnl = df['pnl_pct'].sum() * 100
    
    cumulative = (1 + df['pnl_pct']).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    max_dd = drawdown.min() * 100 if len(drawdown) > 0 else 0
    
    return {
        'rr': rr_ratio,
        'trades': total,
        'win_rate': round(win_rate, 1),
        'total_pnl': round(total_pnl, 2),
        'max_dd': round(max_dd, 2),
    }

# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 70)
    print("📊 订单块筛选策略对比回测")
    print("=" * 70)
    print(f"\n回测时间: {START_DATE} ~ {END_DATE}")
    print()
    
    # 获取数据
    df = fetch_klines(SYMBOL, INTERVAL, START_DATE, END_DATE)
    print(f"📅 数据范围: {df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]}")
    print()
    
    # 识别订单块
    print("🔍 识别订单块...")
    order_blocks = identify_order_blocks(df)
    print(f"✅ 找到 {len(order_blocks)} 个订单块")
    bullish = [ob for ob in order_blocks if ob['type'] == 'bullish']
    bearish = [ob for ob in order_blocks if ob['type'] == 'bearish']
    print(f"   看涨: {len(bullish)}, 看跌: {len(bearish)}")
    print()
    
    # 应用筛选
    print("🔍 应用筛选策略...")
    
    # 策略1：新结论筛选
    s1_all = filter_strategy1(order_blocks, STRATEGY1)
    s1_bullish = [ob for ob in s1_all if ob['type'] == 'bullish']
    s1_bearish = [ob for ob in s1_all if ob['type'] == 'bearish']
    
    # 策略2：ATR筛选
    s2_all = filter_strategy2(order_blocks, df, STRATEGY2)
    s2_bullish = [ob for ob in s2_all if ob['type'] == 'bullish']
    s2_bearish = [ob for ob in s2_all if ob['type'] == 'bearish']
    
    print(f"\n策略1（新结论筛选）: {len(s1_all)} 个订单块")
    print(f"   看涨: {len(s1_bullish)}, 看跌: {len(s1_bearish)}")
    
    print(f"\n策略2（ATR筛选）: {len(s2_all)} 个订单块")
    print(f"   看涨: {len(s2_bullish)}, 看跌: {len(s2_bearish)}")
    
    # 对比结果
    print("\n" + "=" * 70)
    print("📊 回测对比结果")
    print("=" * 70)
    
    for direction, obs_all, s1_obs, s2_obs in [
        ('看涨', bullish, s1_bullish, s2_bullish),
        ('看跌', bearish, s1_bearish, s2_bearish),
    ]:
        print(f"\n{'='*60}")
        print(f"📈 {direction}订单块")
        print(f"{'='*60}")
        
        for rr in RR_RATIOS:
            print(f"\n--- 盈亏比 1:{rr} ---")
            print(f"{'策略':<15} {'交易数':<8} {'胜率':<10} {'总收益':<12} {'最大回撤':<12}")
            print("-" * 60)
            
            # 全部样本
            trades = simulate_trades(df, obs_all, rr)
            stats = calculate_stats(trades, rr)
            if stats:
                print(f"{'全部样本':<15} {stats['trades']:<8} {stats['win_rate']}%{'':<5} {stats['total_pnl']}%{'':<6} {stats['max_dd']}%")
            
            # 策略1
            trades = simulate_trades(df, s1_obs, rr)
            stats = calculate_stats(trades, rr)
            if stats:
                print(f"{'新结论筛选':<15} {stats['trades']:<8} {stats['win_rate']}%{'':<5} {stats['total_pnl']}%{'':<6} {stats['max_dd']}%")
            
            # 策略2
            trades = simulate_trades(df, s2_obs, rr)
            stats = calculate_stats(trades, rr)
            if stats:
                print(f"{'ATR筛选':<15} {stats['trades']:<8} {stats['win_rate']}%{'':<5} {stats['total_pnl']}%{'':<6} {stats['max_dd']}%")
    
    # 综合对比
    print(f"\n{'='*60}")
    print("📊 综合结果（看涨+看跌）")
    print(f"{'='*60}")
    
    for rr in RR_RATIOS:
        print(f"\n--- 盈亏比 1:{rr} ---")
        print(f"{'策略':<15} {'交易数':<8} {'胜率':<10} {'总收益':<12} {'最大回撤':<12}")
        print("-" * 60)
        
        # 全部样本
        trades = simulate_trades(df, order_blocks, rr)
        stats = calculate_stats(trades, rr)
        if stats:
            print(f"{'全部样本':<15} {stats['trades']:<8} {stats['win_rate']}%{'':<5} {stats['total_pnl']}%{'':<6} {stats['max_dd']}%")
        
        # 策略1
        trades = simulate_trades(df, s1_all, rr)
        stats = calculate_stats(trades, rr)
        if stats:
            print(f"{'新结论筛选':<15} {stats['trades']:<8} {stats['win_rate']}%{'':<5} {stats['total_pnl']}%{'':<6} {stats['max_dd']}%")
        
        # 策略2
        trades = simulate_trades(df, s2_all, rr)
        stats = calculate_stats(trades, rr)
        if stats:
            print(f"{'ATR筛选':<15} {stats['trades']:<8} {stats['win_rate']}%{'':<5} {stats['total_pnl']}%{'':<6} {stats['max_dd']}%")

if __name__ == "__main__":
    main()
