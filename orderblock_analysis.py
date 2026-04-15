#!/usr/bin/env python3
"""
订单块结构分析
1. 找出所有订单块结构
2. 检查后续N根K线内是否创新高/新低
3. 分析起始三根K线的线性关系
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime
import json

# ============================================================
# 配置
# ============================================================

SYMBOL = "BTCUSDT"
INTERVAL = "1h"
DAYS = 365  # 一年

# 订单块识别参数
FVG_MIN_SIZE_USD = 100  # FVG 最小尺寸（美元）

# ============================================================
# 数据获取
# ============================================================

def fetch_klines(symbol, interval, days):
    """从 Binance 获取K线数据"""
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
    
    # 转换北京时间
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + pd.Timedelta(hours=8)
    df['timestamp_utc'] = pd.to_datetime(df['timestamp'], unit='ms') if 'timestamp_utc' not in df.columns else df['timestamp'] - pd.Timedelta(hours=8)
    
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    print(f"✅ 获取 {len(df)} 根K线")
    print(f"📅 时间范围: {df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]}")
    
    return df

# ============================================================
# 订单块识别
# ============================================================

def identify_all_order_blocks(df, fvg_min_size=100):
    """
    识别所有订单块结构
    
    返回每个订单块的详细信息，包括三根K线的线性特征
    """
    
    order_blocks = []
    
    for i in range(2, len(df) - 1):  # 留最后一根不做起点
        k1 = df.iloc[i-2]  # 第一根
        k2 = df.iloc[i-1]  # 第二根（突破）
        k3 = df.iloc[i]    # 第三根
        
        # === 看涨订单块 ===
        # k1 下跌，k2 收盘突破 k1.high，存在 FVG (k1.high < k3.low)
        if k1['close'] < k1['open']:  # k1 是下跌
            if k2['close'] > k1['high']:  # 突破
                if k1['high'] < k3['low']:  # FVG 存在
                    fvg_size = k3['low'] - k1['high']
                    
                    if fvg_size >= fvg_min_size:
                        # 计算三根K线的线性特征
                        ob = calculate_kline_features(k1, k2, k3, 'bullish', i-2, df)
                        order_blocks.append(ob)
        
        # === 看跌订单块 ===
        # k1 上涨，k2 收盘跌破 k1.low，存在 FVG (k1.low > k3.high)
        if k1['close'] > k1['open']:  # k1 是上涨
            if k2['close'] < k1['low']:  # 突破
                if k1['low'] > k3['high']:  # FVG 存在
                    fvg_size = k1['low'] - k3['high']
                    
                    if fvg_size >= fvg_min_size:
                        ob = calculate_kline_features(k1, k2, k3, 'bearish', i-2, df)
                        order_blocks.append(ob)
    
    return order_blocks

def calculate_kline_features(k1, k2, k3, ob_type, index, df):
    """计算三根K线的线性特征"""
    
    # K线实体
    k1_body = abs(k1['close'] - k1['open'])
    k2_body = abs(k2['close'] - k2['open'])
    k3_body = abs(k3['close'] - k3['open'])
    
    # K线振幅
    k1_range = k1['high'] - k1['low']
    k2_range = k2['high'] - k2['low']
    k3_range = k3['high'] - k3['low']
    
    # 上下影线
    k1_upper_wick = k1['high'] - max(k1['open'], k1['close'])
    k1_lower_wick = min(k1['open'], k1['close']) - k1['low']
    k2_upper_wick = k2['high'] - max(k2['open'], k2['close'])
    k2_lower_wick = min(k2['open'], k2['close']) - k2['low']
    k3_upper_wick = k3['high'] - max(k3['open'], k3['close'])
    k3_lower_wick = min(k3['open'], k3['close']) - k3['low']
    
    # FVG
    if ob_type == 'bullish':
        fvg_high = k3['low']
        fvg_low = k1['high']
        fvg_size = fvg_high - fvg_low
    else:
        fvg_high = k1['low']
        fvg_low = k3['high']
        fvg_size = fvg_high - fvg_low
    
    # 三根K线收盘价的线性关系（斜率）
    prices = [k1['close'], k2['close'], k3['close']]
    x = np.array([0, 1, 2])
    slope = np.polyfit(x, prices, 1)[0]
    
    # 三根K线最低/最高价的线性关系
    if ob_type == 'bullish':
        lows = [k1['low'], k2['low'], k3['low']]
        low_slope = np.polyfit(x, lows, 1)[0]
        high_slope = None
    else:
        highs = [k1['high'], k2['high'], k3['high']]
        high_slope = np.polyfit(x, highs, 1)[0]
        low_slope = None
    
    # 成交量变化
    vol_change_1_2 = (k2['volume'] - k1['volume']) / k1['volume'] if k1['volume'] > 0 else 0
    vol_change_2_3 = (k3['volume'] - k2['volume']) / k2['volume'] if k2['volume'] > 0 else 0
    
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
        'k1_upper_wick': k1_upper_wick,
        'k1_lower_wick': k1_lower_wick,
        'k1_volume': k1['volume'],
        
        'k2_open': k2['open'],
        'k2_high': k2['high'],
        'k2_low': k2['low'],
        'k2_close': k2['close'],
        'k2_body': k2_body,
        'k2_range': k2_range,
        'k2_upper_wick': k2_upper_wick,
        'k2_lower_wick': k2_lower_wick,
        'k2_volume': k2['volume'],
        
        'k3_open': k3['open'],
        'k3_high': k3['high'],
        'k3_low': k3['low'],
        'k3_close': k3['close'],
        'k3_body': k3_body,
        'k3_range': k3_range,
        'k3_upper_wick': k3_upper_wick,
        'k3_lower_wick': k3_lower_wick,
        'k3_volume': k3['volume'],
        
        # FVG
        'fvg_high': fvg_high,
        'fvg_low': fvg_low,
        'fvg_size': fvg_size,
        
        # 线性特征
        'close_slope': slope,
        'low_slope': low_slope if ob_type == 'bullish' else None,
        'high_slope': high_slope if ob_type == 'bearish' else None,
        
        # 成交量变化
        'vol_change_1_2': vol_change_1_2,
        'vol_change_2_3': vol_change_2_3,
        
        # 比率
        'k2_body_k1_body': k2_body / k1_body if k1_body > 0 else 0,
        'k2_range_k1_range': k2_range / k1_range if k1_range > 0 else 0,
        'fvg_size_k1_range': fvg_size / k1_range if k1_range > 0 else 0,
    }

# ============================================================
# 后续走势分析
# ============================================================

def analyze_future_moves(df, order_blocks, lookahead_periods=[24, 48, 72, 96, 120, 168]):
    """
    分析订单块形成后的走势
    
    lookahead_periods: 检查未来多少根K线内是否创新高/新低
    """
    
    results = []
    
    for ob in order_blocks:
        ob_idx = ob['index']
        ob_type = ob['type']
        
        # 订单块形成时的参考价格
        if ob_type == 'bullish':
            reference_low = ob['k1_low']
            reference_high = ob['k3_high']
        else:
            reference_low = ob['k3_low']
            reference_high = ob['k1_high']
        
        result = ob.copy()
        
        for periods in lookahead_periods:
            end_idx = min(ob_idx + 2 + periods, len(df))  # +2 因为订单块从 k3 结束后开始
            future_df = df.iloc[ob_idx + 3:end_idx]  # 从 k3 之后开始
            
            if len(future_df) == 0:
                result[f'new_high_{periods}h'] = None
                result[f'new_low_{periods}h'] = None
                result[f'max_high_{periods}h'] = None
                result[f'min_low_{periods}h'] = None
                result[f'max_gain_{periods}h'] = None
                result[f'max_loss_{periods}h'] = None
                continue
            
            # 未来最高价和最低价
            future_max_high = future_df['high'].max()
            future_min_low = future_df['low'].min()
            
            # 是否创新高/新低
            if ob_type == 'bullish':
                new_high = future_max_high > reference_high
                new_low = future_min_low < reference_low
            else:
                new_high = future_max_high > reference_high
                new_low = future_min_low < reference_low
            
            # 最大涨幅/跌幅（从订单块高点开始计算）
            if ob_type == 'bullish':
                max_gain = (future_max_high - ob['fvg_low']) / ob['fvg_low'] * 100
                max_loss = (ob['fvg_high'] - future_min_low) / ob['fvg_high'] * 100
            else:
                max_gain = (ob['fvg_low'] - future_min_low) / ob['fvg_low'] * 100
                max_loss = (future_max_high - ob['fvg_high']) / ob['fvg_high'] * 100
            
            result[f'new_high_{periods}h'] = new_high
            result[f'new_low_{periods}h'] = new_low
            result[f'max_high_{periods}h'] = future_max_high
            result[f'min_low_{periods}h'] = future_min_low
            result[f'max_gain_{periods}h'] = max_gain
            result[f'max_loss_{periods}h'] = max_loss
        
        results.append(result)
    
    return results

# ============================================================
# 统计分析
# ============================================================

def calculate_statistics(results, lookahead_periods=[24, 48, 72, 96, 120, 168]):
    """计算统计数据"""
    
    df = pd.DataFrame(results)
    
    print("\n" + "=" * 80)
    print("📊 订单块统计分析")
    print("=" * 80)
    
    # 按类型分组
    for ob_type in ['bullish', 'bearish']:
        type_df = df[df['type'] == ob_type]
        
        if len(type_df) == 0:
            continue
        
        print(f"\n{'='*40}")
        print(f"📈 {'看涨订单块' if ob_type == 'bullish' else '看跌订单块'}")
        print(f"{'='*40}")
        print(f"总数量: {len(type_df)}")
        
        print(f"\n{'后续表现':^80}")
        print("-" * 80)
        print(f"{'时间窗口':<12} {'创新高%':<12} {'创新低%':<12} {'平均最大涨幅':<16} {'平均最大跌幅':<16}")
        print("-" * 80)
        
        for periods in lookahead_periods:
            col_new_high = f'new_high_{periods}h'
            col_new_low = f'new_low_{periods}h'
            col_max_gain = f'max_gain_{periods}h'
            col_max_loss = f'max_loss_{periods}h'
            
            if col_new_high not in type_df.columns:
                continue
            
            valid = type_df[type_df[col_new_high].notna()]
            
            if len(valid) == 0:
                continue
            
            new_high_pct = valid[col_new_high].sum() / len(valid) * 100
            new_low_pct = valid[col_new_low].sum() / len(valid) * 100
            avg_gain = valid[col_max_gain].mean()
            avg_loss = valid[col_max_loss].mean()
            
            print(f"{periods}h ({periods//24}天){'':<4} {new_high_pct:>8.1f}%{new_low_pct:>12.1f}%{avg_gain:>14.2f}%{avg_loss:>16.2f}%")
        
        # 三根K线线性特征分析
        print(f"\n{'三根K线特征':^80}")
        print("-" * 80)
        
        # 只看创新高的案例
        for periods in [24, 72, 168]:
            col_new_high = f'new_high_{periods}h'
            if col_new_high not in type_df.columns:
                continue
            
            success = type_df[type_df[col_new_high] == True]
            fail = type_df[type_df[col_new_high] == False]
            
            if len(success) > 0 and len(fail) > 0:
                print(f"\n{periods}h内创新高 vs 未创新高:")
                print(f"  成功案例数: {len(success)}, 失败案例数: {len(fail)}")
                print(f"  | 指标 | 成功 | 失败 |")
                print(f"  |------|------|------|")
                print(f"  | k2实体/k1实体 | {success['k2_body_k1_body'].mean():.2f} | {fail['k2_body_k1_body'].mean():.2f} |")
                print(f"  | k2振幅/k1振幅 | {success['k2_range_k1_range'].mean():.2f} | {fail['k2_range_k1_range'].mean():.2f} |")
                print(f"  | FVG大小/k1振幅 | {success['fvg_size_k1_range'].mean():.2f} | {fail['fvg_size_k1_range'].mean():.2f} |")
                print(f"  | 收盘价斜率 | {success['close_slope'].mean():.2f} | {fail['close_slope'].mean():.2f} |")
                print(f"  | k1→k2成交量变化 | {success['vol_change_1_2'].mean()*100:.1f}% | {fail['vol_change_1_2'].mean()*100:.1f}% |")
    
    return df

# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 80)
    print("📊 订单块结构分析系统")
    print("=" * 80)
    print()
    
    # 获取数据
    df = fetch_klines(SYMBOL, INTERVAL, DAYS)
    print()
    
    # 识别所有订单块
    print("🔍 识别订单块结构...")
    order_blocks = identify_all_order_blocks(df, FVG_MIN_SIZE_USD)
    print(f"✅ 找到 {len(order_blocks)} 个订单块")
    print(f"   看涨: {sum(1 for ob in order_blocks if ob['type'] == 'bullish')}")
    print(f"   看跌: {sum(1 for ob in order_blocks if ob['type'] == 'bearish')}")
    print()
    
    # 分析后续走势
    print("📈 分析后续走势...")
    results = analyze_future_moves(df, order_blocks)
    print()
    
    # 统计分析
    results_df = calculate_statistics(results)
    
    # 保存详细结果
    output_file = "/root/.openclaw/workspace/orderblock_analysis.csv"
    results_df.to_csv(output_file, index=False)
    print(f"\n📁 详细结果已保存: {output_file}")

if __name__ == "__main__":
    main()
