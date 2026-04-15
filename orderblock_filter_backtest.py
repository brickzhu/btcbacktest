#!/usr/bin/env python3
"""
订单块特征筛选回测
用2024-2025全年数据验证：
1. k2实体/k1实体 < 20
2. FVG大小/k1振幅 > 0.5
3. k1→k2成交量变化 > 80%
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

# 筛选条件阈值
FILTER_K2_BODY_RATIO_MAX = 20      # k2实体/k1实体 上限
FILTER_FVG_RATIO_MIN = 0.5         # FVG/k1振幅 下限
FILTER_VOL_CHANGE_MIN = 0.8        # k1→k2成交量变化 下限

# ============================================================
# 数据获取
# ============================================================

def fetch_klines(symbol, interval, start_date, end_date):
    """获取指定时间范围的K线数据"""
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
    
    # 北京时间
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + pd.Timedelta(hours=8)
    
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    return df

# ============================================================
# 订单块识别
# ============================================================

def identify_order_blocks(df):
    """识别所有订单块并计算特征"""
    
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
                        ob = create_ob_record(k1, k2, k3, 'bullish', i-2, df)
                        order_blocks.append(ob)
        
        # === 看跌订单块 ===
        if k1['close'] > k1['open']:
            if k2['close'] < k1['low']:
                if k1['low'] > k3['high']:
                    fvg_size = k1['low'] - k3['high']
                    
                    if fvg_size >= 100:
                        ob = create_ob_record(k1, k2, k3, 'bearish', i-2, df)
                        order_blocks.append(ob)
    
    return order_blocks

def create_ob_record(k1, k2, k3, ob_type, index, df):
    """创建订单块记录"""
    
    k1_body = abs(k1['close'] - k1['open'])
    k2_body = abs(k2['close'] - k2['open'])
    k1_range = k1['high'] - k1['low']
    
    if ob_type == 'bullish':
        fvg_size = k3['low'] - k1['high']
    else:
        fvg_size = k1['low'] - k3['high']
    
    vol_change = (k2['volume'] - k1['volume']) / k1['volume'] if k1['volume'] > 0 else 0
    
    return {
        'type': ob_type,
        'index': index,
        'timestamp': k1['timestamp'],
        
        # 三根K线数据
        'k1_open': k1['open'],
        'k1_high': k1['high'],
        'k1_low': k1['low'],
        'k1_close': k1['close'],
        'k1_body': k1_body,
        'k1_range': k1_range,
        'k1_volume': k1['volume'],
        
        'k2_open': k2['open'],
        'k2_high': k2['high'],
        'k2_low': k2['low'],
        'k2_close': k2['close'],
        'k2_body': k2_body,
        'k2_volume': k2['volume'],
        
        'k3_high': k3['high'],
        'k3_low': k3['low'],
        
        # 特征比率
        'k2_body_k1_body': k2_body / k1_body if k1_body > 0 else 0,
        'fvg_size_k1_range': fvg_size / k1_range if k1_range > 0 else 0,
        'vol_change_1_2': vol_change,
        
        # FVG
        'fvg_size': fvg_size,
    }

# ============================================================
# 后续走势分析
# ============================================================

def analyze_future(df, order_blocks, lookahead_periods=[24, 48, 72, 96, 120, 168]):
    """分析后续走势"""
    
    results = []
    
    for ob in order_blocks:
        ob_idx = ob['index']
        ob_type = ob['type']
        
        # 参考价格
        if ob_type == 'bullish':
            reference_high = ob['k3_high']
        else:
            reference_low = ob['k3_low']
        
        result = ob.copy()
        
        for periods in lookahead_periods:
            end_idx = min(ob_idx + 2 + periods, len(df))
            future_df = df.iloc[ob_idx + 3:end_idx]
            
            if len(future_df) == 0:
                result[f'new_high_{periods}h'] = None
                result[f'max_gain_{periods}h'] = None
                continue
            
            future_max_high = future_df['high'].max()
            future_min_low = future_df['low'].min()
            
            if ob_type == 'bullish':
                new_high = future_max_high > reference_high
                max_gain = (future_max_high - ob['k1_high']) / ob['k1_high'] * 100
            else:
                new_high = future_min_low < reference_low
                max_gain = (ob['k1_low'] - future_min_low) / ob['k1_low'] * 100
            
            result[f'new_high_{periods}h'] = new_high
            result[f'max_gain_{periods}h'] = max_gain
        
        results.append(result)
    
    return results

# ============================================================
# 筛选与统计
# ============================================================

def apply_filters(results):
    """应用筛选条件"""
    
    filtered = []
    
    for r in results:
        # 条件1: k2实体/k1实体 < 20
        cond1 = r['k2_body_k1_body'] < FILTER_K2_BODY_RATIO_MAX
        
        # 条件2: FVG/k1振幅 > 0.5
        cond2 = r['fvg_size_k1_range'] > FILTER_FVG_RATIO_MIN
        
        # 条件3: 成交量增长 > 80%
        cond3 = r['vol_change_1_2'] > FILTER_VOL_CHANGE_MIN
        
        r['pass_all'] = cond1 and cond2 and cond3
        r['pass_cond1'] = cond1
        r['pass_cond2'] = cond2
        r['pass_cond3'] = cond3
        
        filtered.append(r)
    
    return filtered

def calculate_stats(results, title=""):
    """计算统计"""
    
    df = pd.DataFrame(results)
    
    for ob_type in ['bullish', 'bearish']:
        type_df = df[df['type'] == ob_type]
        
        if len(type_df) == 0:
            continue
        
        print(f"\n{'='*60}")
        print(f"{'看涨订单块' if ob_type == 'bullish' else '看跌订单块'} {title}")
        print(f"{'='*60}")
        print(f"样本数量: {len(type_df)}")
        print(f"\n{'时间窗口':<12} {'创新高%':<12} {'平均涨幅':<12}")
        print("-" * 40)
        
        for periods in [24, 48, 72, 96, 120, 168]:
            col_new_high = f'new_high_{periods}h'
            col_max_gain = f'max_gain_{periods}h'
            
            valid = type_df[type_df[col_new_high].notna()]
            
            if len(valid) == 0:
                continue
            
            new_high_pct = valid[col_new_high].sum() / len(valid) * 100
            avg_gain = valid[col_max_gain].mean()
            
            print(f"{periods}h ({periods//24}天){'':<4} {new_high_pct:>8.1f}%{avg_gain:>12.2f}%")

# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 60)
    print("📊 订单块特征筛选回测")
    print("=" * 60)
    print(f"\n筛选条件:")
    print(f"  1. k2实体/k1实体 < {FILTER_K2_BODY_RATIO_MAX}")
    print(f"  2. FVG/k1振幅 > {FILTER_FVG_RATIO_MIN}")
    print(f"  3. k1→k2成交量变化 > {FILTER_VOL_CHANGE_MIN * 100}%")
    print()
    
    # 获取2024-2025全年数据
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
    
    # 分析后续走势
    print("📈 分析后续走势...")
    results = analyze_future(df, order_blocks)
    print()
    
    # 全部样本统计
    calculate_stats(results, "(全部样本)")
    
    # 应用筛选条件
    results_filtered = apply_filters(results)
    
    # 筛选后统计
    passed_all = [r for r in results_filtered if r['pass_all']]
    calculate_stats(passed_all, "(通过全部筛选)")
    
    # 各条件单独筛选
    print(f"\n{'='*60}")
    print("📊 单独条件筛选效果")
    print(f"{'='*60}")
    
    for cond_name, cond_key in [
        ("k2实体<20x", "pass_cond1"),
        ("FVG>0.5", "pass_cond2"),
        ("成交量>80%", "pass_cond3")
    ]:
        passed = [r for r in results_filtered if r[cond_key]]
        df_passed = pd.DataFrame(passed)
        
        bullish = df_passed[df_passed['type'] == 'bullish']
        
        if len(bullish) > 0:
            valid_72h = bullish[bullish['new_high_72h'].notna()]
            success_rate = valid_72h['new_high_72h'].sum() / len(valid_72h) * 100 if len(valid_72h) > 0 else 0
            print(f"\n{cond_name}: {len(passed)} 个订单块")
            print(f"  看涨 72h 创新高率: {success_rate:.1f}%")
    
    # 保存详细结果
    output_file = "/root/.openclaw/workspace/orderblock_filter_results.csv"
    pd.DataFrame(results_filtered).to_csv(output_file, index=False)
    print(f"\n📁 详细结果已保存: {output_file}")

if __name__ == "__main__":
    main()
