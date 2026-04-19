#!/usr/bin/env python3
"""
订单块回测 - K线合并法
==========================================
策略参数：
- 入场价：FVG 100%（k1边缘）
- 止损：k1.close
- ATR周期：14
- ATR倍数：1.5x
- FVG/ATR最小：50%
- FVG定义：k2.close
- K线合并：连续同向K线合并，直到反向确认
- 数据源：Binance永续合约
- 周期：1小时
- 杠杆：10倍

合并规则：
  看涨订单块：
    - k1：连续下跌K线合并，直到出现上涨K线
    - k2：连续上涨K线合并，直到出现下跌K线确认
    - 入场价 = k1.high，止损 = k1.close
  
  看跌订单块：
    - k1：连续上涨K线合并，直到出现下跌K线
    - k2：连续下跌K线合并，直到出现上涨K线确认
    - 入场价 = k1.low，止损 = k1.close
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


def merge_klines(df):
    """
    合并K线规则：
    1. 包含关系：下一根K线被当前合并K线完全包含 → 合并，方向不变
    2. 同向延续：下一根K线方向相同 → 合并
    3. 反向且不被包含 → 结束当前合并，开始新的
    
    返回合并后的K线列表
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
            next_high = next_row['high']
            next_low = next_row['low']
            
            # 规则1：包含关系（下一根被当前合并K线完全包含）
            is_contained = (next_high <= merged_high) and (next_low >= merged_low)
            
            # 规则2：同向
            is_same_direction = (next_direction == direction)
            
            if is_contained or is_same_direction:
                # 合并
                merged_high = max(merged_high, next_high)
                merged_low = min(merged_low, next_low)
                merged_close = next_row['close']
                # 包含关系时方向不变，同向时方向也不变
                j += 1
            else:
                # 反向且不被包含 → 结束
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


def identify_order_blocks_merged(df, merged_klines):
    """
    从合并后的K线中识别订单块
    """
    atr = calculate_atr(df, ATR_PERIOD)
    order_blocks = []
    
    for i in range(1, len(merged_klines) - 2):
        k1 = merged_klines[i - 1]
        k2 = merged_klines[i]
        k3 = merged_klines[i + 1]  # k3 = k2之后第一根反向K线（合并后自然就是反向）
        
        # 获取k1结束时的ATR
        k1_end_idx = k1['end_idx']
        if k1_end_idx >= len(atr):
            continue
        current_atr = atr.iloc[k1_end_idx]
        if pd.isna(current_atr):
            continue
        
        # 看涨订单块：k1下跌 → k2上涨突破 → k3下跌确认
        if k1['direction'] == 'down' and k2['direction'] == 'up' and k3['direction'] == 'down':
            # k2收盘突破k1.high，且k3.low仍在k1.high上方（FVG未被填补）
            if k2['close'] > k1['high'] and k3['low'] > k1['high']:
                fvg_size = k3['low'] - k1['high']  # FVG = k3.low ~ k1.high
                if fvg_size >= 100:
                    k2_body = abs(k2['close'] - k2['open'])
                    fvg_atr_pct = (fvg_size / current_atr * 100)
                    pass_atr = (k2_body >= current_atr * ATR_MULTIPLIER) and (fvg_atr_pct >= FVG_ATR_PCT_MIN)
                    
                    entry_price = k1['high']
                    stop_loss = k1['close']
                    sl_distance = (entry_price - stop_loss) / entry_price * 100
                    
                    order_blocks.append({
                        'type': 'bullish',
                        'start_idx': k1['start_idx'],
                        'end_idx': k3['end_idx'],  # 确认点移到k3结束
                        'timestamp': k1['timestamp'],
                        'k1_high': k1['high'],
                        'k1_low': k1['low'],
                        'k1_close': k1['close'],
                        'k3_ref': k3['low'],
                        'entry_price': entry_price,
                        'stop_loss': stop_loss,
                        'fvg_size': fvg_size,
                        'atr': current_atr,
                        'k2_body': k2_body,
                        'fvg_atr_pct': fvg_atr_pct,
                        'pass_atr': pass_atr
                    })
        
        # 看跌订单块：k1上涨 → k2下跌突破 → k3上涨确认
        if k1['direction'] == 'up' and k2['direction'] == 'down' and k3['direction'] == 'up':
            # k2收盘突破k1.low，且k3.high仍在k1.low下方（FVG未被填补）
            if k2['close'] < k1['low'] and k3['high'] < k1['low']:
                fvg_size = k1['low'] - k3['high']  # FVG = k1.low ~ k3.high
                if fvg_size >= 100:
                    k2_body = abs(k2['close'] - k2['open'])
                    fvg_atr_pct = (fvg_size / current_atr * 100)
                    pass_atr = (k2_body >= current_atr * ATR_MULTIPLIER) and (fvg_atr_pct >= FVG_ATR_PCT_MIN)
                    
                    entry_price = k1['low']
                    stop_loss = k1['close']
                    sl_distance = (stop_loss - entry_price) / entry_price * 100
                    
                    order_blocks.append({
                        'type': 'bearish',
                        'start_idx': k1['start_idx'],
                        'end_idx': k3['end_idx'],  # 确认点移到k3结束
                        'timestamp': k1['timestamp'],
                        'k1_high': k1['high'],
                        'k1_low': k1['low'],
                        'k1_close': k1['close'],
                        'k3_ref': k3['high'],
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
    """
    模拟交易 - 同一时间只持有一笔仓位
    平仓后才能开下一笔
    """
    trades = []
    last_exit_idx = -1  # 上一笔平仓的K线索引
    
    for ob in order_blocks:
        ob_idx = ob['end_idx']  # 订单块确认后的索引
        ob_type = ob['type']
        entry_price = ob['entry_price']
        stop_loss = ob['stop_loss']
        risk = abs(entry_price - stop_loss)
        take_profit = entry_price + (risk * rr_ratio) if ob_type == 'bullish' else entry_price - (risk * rr_ratio)
        
        # 硬止损
        if MAX_LOSS_PCT is not None:
            price_move_pct = MAX_LOSS_PCT / leverage / 100
            if ob_type == 'bullish':
                hard_stop = entry_price * (1 - price_move_pct)
            else:
                hard_stop = entry_price * (1 + price_move_pct)
        else:
            hard_stop = None
        
        # 搜索入场（从订单块确认后开始，且必须在上笔平仓之后）
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
        
        # 检查入场K线
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
            result = 'win' if (ob_type == 'bullish' and entry_candle['close'] >= entry_price) or \
                           (ob_type == 'bearish' and entry_candle['close'] <= entry_price) else 'loss'
            exit_price = take_profit if result == 'win' else actual_sl
            exit_idx = entry_idx
        elif sl_hit:
            result, exit_price = 'loss', actual_sl
            exit_idx = entry_idx
        elif tp_hit:
            result, exit_price = 'win', take_profit
            exit_idx = entry_idx
        else:
            result, exit_price = None, None
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
                result = 'win' if (ob_type == 'bullish' and exit_price > entry_price) or \
                              (ob_type == 'bearish' and exit_price < entry_price) else 'loss'
        
        # 更新最后平仓索引
        last_exit_idx = exit_idx
        
        pnl_pct = ((exit_price - entry_price) / entry_price if ob_type == 'bullish' else 
                   (entry_price - exit_price) / entry_price) - FEE_RATE * 2
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
print("📊 订单块回测 - K线合并法")
print("=" * 80)
print(f"\n入场规则: FVG 100% (k1边缘)")
print(f"止损规则: k1.close")
print(f"ATR周期: 14 | ATR倍数: 1.5x | FVG/ATR最小: {FVG_ATR_PCT_MIN}%")
print(f"K线合并: 连续同向K线合并，直到反向确认")
print(f"仓位限制: 同一时间只持有一笔，平仓后才能开新仓")
print(f"周期: 1小时 | 杠杆: 10x")
print()

df = fetch_klines(SYMBOL, INTERVAL, START_DATE, END_DATE)
print(f"BTC: ${df.iloc[0]['open']:,.0f} → ${df.iloc[-1]['close']:,.0f}")

# 合并K线
print("\n🔄 合并K线...")
merged_klines = merge_klines(df)
print(f"   原始K线: {len(df)} 根")
print(f"   合并后: {len(merged_klines)} 根")

# 识别订单块
order_blocks = identify_order_blocks_merged(df, merged_klines)
bullish = [ob for ob in order_blocks if ob['type'] == 'bullish' and ob['pass_atr']]
bearish = [ob for ob in order_blocks if ob['type'] == 'bearish' and ob['pass_atr']]

print(f"\n看涨: {len(bullish)} 笔 | 看跌: {len(bearish)} 笔")

# 年度分析
print("\n" + "=" * 80)
print("📊 年度收益分析（RR=2，10x杠杆）")
print("=" * 80)

# 按时间排序订单块，避免先处理所有 bullish 导致 bearish 无法入场
all_ob = sorted(bullish + bearish, key=lambda x: x['timestamp'])
all_trades = simulate_trades(df, all_ob, 2)
all_trades = sorted(all_trades, key=lambda x: x['timestamp'])
df_trades = pd.DataFrame(all_trades)
df_trades['timestamp'] = pd.to_datetime(df_trades['timestamp'])

print(f"\n{'年度':<8} {'交易数':<8} {'胜率':<10} {'无杠杆':<12} {'10x杠杆':<14}")
print("-" * 55)

cumulative = 1.0

for year in [2023, 2024, 2025, 2026]:
    year_trades = df_trades[df_trades['timestamp'].dt.year == year]
    if len(year_trades) == 0:
        continue
    
    wins = len(year_trades[year_trades['result'] == 'win'])
    win_rate = wins / len(year_trades) * 100
    year_pnl = (1 + year_trades['pnl_pct']).prod() - 1
    year_pnl_10x = (1 + year_trades['pnl_pct_10x']).prod() - 1
    
    for _, row in year_trades.iterrows():
        cumulative *= (1 + row['pnl_pct_10x'])
    
    print(f"{year:<8} {len(year_trades):<8} {win_rate:.1f}%{'':<5} {year_pnl*100:+.1f}%{'':<6} {year_pnl_10x*100:+.1f}%")

print("-" * 55)
wins_all = len(df_trades[df_trades['result'] == 'win'])
print(f"{'总计':<8} {len(df_trades):<8} {wins_all/len(df_trades)*100:.1f}%{'':<5} {(1+df_trades['pnl_pct']).prod()-1:.1%}{'':<7} {cumulative-1:.1%}")

# 保存
df_trades.to_csv('/root/.openclaw/workspace/orderblock_merged_trades.csv', index=False)
print(f"\n📁 交易记录: orderblock_merged_trades.csv")

# 对比原策略
print("\n" + "=" * 80)
print("📊 对比：原策略 vs 合并法")
print("=" * 80)
print(f"\n{'策略':<20} {'交易数':<10} {'胜率':<10} {'三年收益':<15}")
print("-" * 55)
print(f"{'原策略(14ATR)':<20} 248        77.4%     +12541.5%")
print(f"{'合并法':<20} {len(df_trades):<10} {wins_all/len(df_trades)*100:.1f}%{'':<5} {cumulative-1:.1%}")
