#!/usr/bin/env python3
"""
Order Block 回测脚本 v1.0
测试订单块策略在 BTC/USDT 1H 上的表现
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

# ============================================================
# 配置
# ============================================================

SYMBOL = "BTCUSDT"
INTERVAL = "1h"
DAYS = 180  # 回测天数

# 固定参数
BREAKOUT_TYPE = "close"  # 收盘突破
RETEST_LIMIT = 48  # 回踩时限 (根数)

# 可调参数 (网格搜索)
PARAM_BODY_MULTIPLIER = [1.5, 2.0, 2.5, 3.0]  # 参数1A: 实体倍数
PARAM_ATR_MULTIPLIER = [1.0, 1.5, 2.0, 2.5]    # 参数1B: ATR倍数
PARAM_FVG_ATR_PCT = [10, 20, 30, 50]            # 参数3B: FVG/ATR百分比
PARAM_RR_RATIO = [2.0, 3.0, 4.0, 5.0]           # 参数5A: 盈亏比

# 手续费
FEE_RATE = 0.0006  # 0.06% (Binance 合约 Maker + Taker 平均)

# ============================================================
# 数据获取
# ============================================================

def fetch_klines(symbol, interval, days):
    """从 Binance 获取K线数据"""
    url = "https://api.binance.com/api/v3/klines"
    
    # 计算时间范围
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
        current_start = data[-1][0] + 60000  # 下一批
        
        if len(data) < 1000:
            break
    
    # 转换为 DataFrame
    df = pd.DataFrame(all_data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])
    
    # 类型转换
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    df.set_index('timestamp', inplace=True)
    
    print(f"✅ 获取 {len(df)} 根K线")
    
    return df

# ============================================================
# 技术指标
# ============================================================

def calculate_atr(df, period=14):
    """计算 ATR"""
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
    """计算平均K线实体大小"""
    body = abs(df['close'] - df['open'])
    avg_body = body.rolling(window=period).mean()
    return avg_body

# ============================================================
# 订单块识别
# ============================================================

def identify_order_blocks(df, body_multiplier=None, atr_multiplier=None, method='body'):
    """
    识别订单块
    
    参数:
    - df: K线数据
    - body_multiplier: 实体倍数 (method='body' 时使用)
    - atr_multiplier: ATR倍数 (method='atr' 时使用)
    - method: 'body' 或 'atr' 或 'engulfing'
    
    返回:
    - 订单块列表
    """
    
    atr = calculate_atr(df)
    avg_body = calculate_avg_body(df)
    
    order_blocks = []
    
    for i in range(2, len(df)):
        # 第1根K线 (反向K线)
        k1 = df.iloc[i-2]
        # 第2根K线 (突破K线)
        k2 = df.iloc[i-1]
        # 当前K线
        k3 = df.iloc[i]
        
        # === 看涨订单块 ===
        # 第1根必须是下跌K线
        if k1['close'] < k1['open']:
            # 检查第2根是否突破 (收盘突破)
            if k2['close'] > k1['high']:
                # 检查 FVG: k1.high < k3.low
                if k1['high'] < k3['low']:
                    # 计算 FVG 大小
                    fvg_size = k3['low'] - k1['high']
                    ob_high = k1['high']
                    ob_low = k1['low']
                    
                    # 检查第2根K线强度
                    body_size = abs(k2['close'] - k2['open'])
                    
                    valid = False
                    
                    if method == 'body':
                        # 实体倍数确认
                        threshold = avg_body.iloc[i-1] * body_multiplier
                        valid = body_size >= threshold
                    elif method == 'atr':
                        # ATR倍数确认
                        threshold = atr.iloc[i-1] * atr_multiplier
                        price_move = abs(k2['close'] - k2['open'])
                        valid = price_move >= threshold
                    elif method == 'engulfing':
                        # 吞没确认
                        valid = k2['close'] > k1['high'] and k2['low'] < k1['low']
                    
                    if valid and not pd.isna(fvg_size) and fvg_size > 0:
                        order_blocks.append({
                            'type': 'bullish',
                            'index': i - 2,
                            'timestamp': df.index[i-2],
                            'ob_high': ob_high,
                            'ob_low': ob_low,
                            'fvg_high': k3['low'],
                            'fvg_low': k1['high'],
                            'fvg_size': fvg_size,
                            'entry_price': (k1['high'] + k3['low']) / 2,  # FVG 50%
                            'stop_loss': k1['low'],
                            'atr': atr.iloc[i-1]
                        })
        
        # === 看跌订单块 ===
        # 第1根必须是上涨K线
        if k1['close'] > k1['open']:
            # 检查第2根是否突破 (收盘突破)
            if k2['close'] < k1['low']:
                # 检查 FVG: k1.low > k3.high
                if k1['low'] > k3['high']:
                    # 计算 FVG 大小
                    fvg_size = k1['low'] - k3['high']
                    ob_high = k1['high']
                    ob_low = k1['low']
                    
                    # 检查第2根K线强度
                    body_size = abs(k2['close'] - k2['open'])
                    
                    valid = False
                    
                    if method == 'body':
                        threshold = avg_body.iloc[i-1] * body_multiplier
                        valid = body_size >= threshold
                    elif method == 'atr':
                        threshold = atr.iloc[i-1] * atr_multiplier
                        price_move = abs(k2['close'] - k2['open'])
                        valid = price_move >= threshold
                    elif method == 'engulfing':
                        valid = k2['close'] < k1['low'] and k2['high'] > k1['high']
                    
                    if valid and not pd.isna(fvg_size) and fvg_size > 0:
                        order_blocks.append({
                            'type': 'bearish',
                            'index': i - 2,
                            'timestamp': df.index[i-2],
                            'ob_high': ob_high,
                            'ob_low': ob_low,
                            'fvg_high': k1['low'],
                            'fvg_low': k3['high'],
                            'fvg_size': fvg_size,
                            'entry_price': (k1['low'] + k3['high']) / 2,  # FVG 50%
                            'stop_loss': k1['high'],
                            'atr': atr.iloc[i-1]
                        })
    
    return order_blocks

# ============================================================
# 交易模拟
# ============================================================

def simulate_trades(df, order_blocks, retest_limit=48, rr_ratio=3.0, fee_rate=0.0006, fvg_atr_pct=None):
    """
    模拟交易
    
    参数:
    - df: K线数据
    - order_blocks: 订单块列表
    - retest_limit: 回踩时限 (根数)
    - rr_ratio: 盈亏比
    - fee_rate: 手续费率
    - fvg_atr_pct: FVG/ATR 最小百分比 (可选过滤)
    
    返回:
    - 交易列表
    """
    
    trades = []
    
    for ob in order_blocks:
        # FVG 过滤
        if fvg_atr_pct is not None and ob['atr'] > 0:
            fvg_pct = (ob['fvg_size'] / ob['atr']) * 100
            if fvg_pct < fvg_atr_pct:
                continue
        
        # 搜索回踩
        start_idx = ob['index'] + 3  # 从 FVG 形成后开始
        end_idx = min(start_idx + retest_limit, len(df))
        
        entry_price = ob['entry_price']
        stop_loss = ob['stop_loss']
        
        # 计算止盈
        risk = abs(entry_price - stop_loss)
        
        if ob['type'] == 'bullish':
            take_profit = entry_price + (risk * rr_ratio)
            direction = 'long'
        else:
            take_profit = entry_price - (risk * rr_ratio)
            direction = 'short'
        
        # 检查是否回踩入场
        entered = False
        entry_idx = None
        
        for i in range(start_idx, end_idx):
            candle = df.iloc[i]
            
            # 检查价格是否进入 FVG 区域
            if ob['fvg_low'] <= candle['low'] <= ob['fvg_high'] or \
               ob['fvg_low'] <= candle['high'] <= ob['fvg_high'] or \
               (candle['low'] <= ob['fvg_low'] and candle['high'] >= ob['fvg_high']):
                
                # 检查是否触及入场价 (FVG 50%)
                if ob['type'] == 'bullish':
                    if candle['low'] <= entry_price <= candle['high']:
                        entered = True
                        entry_idx = i
                        break
                else:  # bearish
                    if candle['low'] <= entry_price <= candle['high']:
                        entered = True
                        entry_idx = i
                        break
        
        if not entered:
            continue
        
        # 模拟交易结果
        # 从入场点开始检查止盈/止损
        result = None
        exit_price = None
        
        for i in range(entry_idx + 1, len(df)):
            candle = df.iloc[i]
            
            if ob['type'] == 'bullish':
                # 先检查止损
                if candle['low'] <= stop_loss:
                    result = 'loss'
                    exit_price = stop_loss
                    break
                # 再检查止盈
                if candle['high'] >= take_profit:
                    result = 'win'
                    exit_price = take_profit
                    break
            else:  # bearish
                # 先检查止损
                if candle['high'] >= stop_loss:
                    result = 'loss'
                    exit_price = stop_loss
                    break
                # 再检查止盈
                if candle['low'] <= take_profit:
                    result = 'win'
                    exit_price = take_profit
                    break
        
        # 如果到数据结束都没触发
        if result is None:
            # 用最后收盘价计算
            exit_price = df.iloc[-1]['close']
            if ob['type'] == 'bullish':
                result = 'win' if exit_price > entry_price else 'loss'
            else:
                result = 'win' if exit_price < entry_price else 'loss'
        
        # 计算 PnL
        if ob['type'] == 'bullish':
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
        
        # 扣除手续费
        pnl_pct -= fee_rate * 2  # 开仓 + 平仓
        
        trades.append({
            'timestamp': ob['timestamp'],
            'type': ob['type'],
            'direction': direction,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'exit_price': exit_price,
            'result': result,
            'pnl_pct': pnl_pct,
            'risk': risk,
            'rr_ratio': rr_ratio
        })
    
    return trades

# ============================================================
# 统计分析
# ============================================================

def calculate_stats(trades):
    """计算统计数据"""
    
    if not trades:
        return None
    
    df_trades = pd.DataFrame(trades)
    
    wins = df_trades[df_trades['result'] == 'win']
    losses = df_trades[df_trades['result'] == 'loss']
    
    total_trades = len(trades)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = win_count / total_trades * 100 if total_trades > 0 else 0
    
    avg_win = wins['pnl_pct'].mean() if len(wins) > 0 else 0
    avg_loss = abs(losses['pnl_pct'].mean()) if len(losses) > 0 else 0
    
    total_pnl = df_trades['pnl_pct'].sum() * 100  # 转为百分比
    
    # 计算最大回撤
    cumulative = (1 + df_trades['pnl_pct']).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = drawdown.min() * 100 if len(drawdown) > 0 else 0
    
    # 计算盈亏比
    actual_rr = avg_win / avg_loss if avg_loss > 0 else 0
    
    # 期望值
    expectancy = (win_rate/100 * avg_win) - ((100-win_rate)/100 * avg_loss)
    
    return {
        'total_trades': total_trades,
        'win_count': win_count,
        'loss_count': loss_count,
        'win_rate': round(win_rate, 2),
        'avg_win_pct': round(avg_win * 100, 4),
        'avg_loss_pct': round(avg_loss * 100, 4),
        'actual_rr': round(actual_rr, 2),
        'total_pnl_pct': round(total_pnl, 2),
        'max_drawdown_pct': round(max_drawdown, 2),
        'expectancy': round(expectancy * 100, 4)
    }

# ============================================================
# 网格搜索
# ============================================================

def grid_search(df, verbose=True):
    """网格搜索最优参数"""
    
    results = []
    
    # 参数组合
    for body_mult in PARAM_BODY_MULTIPLIER:
        for atr_mult in PARAM_ATR_MULTIPLIER:
            for fvg_pct in PARAM_FVG_ATR_PCT:
                for rr in PARAM_RR_RATIO:
                    
                    # 测试三种确认方式
                    for method in ['body', 'atr', 'engulfing']:
                        if method == 'body':
                            ob_list = identify_order_blocks(
                                df, 
                                body_multiplier=body_mult, 
                                method='body'
                            )
                        elif method == 'atr':
                            ob_list = identify_order_blocks(
                                df, 
                                atr_multiplier=atr_mult, 
                                method='atr'
                            )
                        else:  # engulfing
                            ob_list = identify_order_blocks(
                                df, 
                                method='engulfing'
                            )
                        
                        trades = simulate_trades(
                            df, 
                            ob_list, 
                            retest_limit=RETEST_LIMIT,
                            rr_ratio=rr,
                            fee_rate=FEE_RATE,
                            fvg_atr_pct=fvg_pct
                        )
                        
                        stats = calculate_stats(trades)
                        
                        if stats:
                            results.append({
                                'method': method,
                                'body_mult': body_mult if method == 'body' else None,
                                'atr_mult': atr_mult if method == 'atr' else None,
                                'fvg_atr_pct': fvg_pct,
                                'rr_ratio': rr,
                                **stats
                            })
    
    return pd.DataFrame(results)

# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 60)
    print("📊 Order Block 回测系统 v1.0")
    print("=" * 60)
    print()
    
    # 获取数据
    df = fetch_klines(SYMBOL, INTERVAL, DAYS)
    print()
    
    # 显示数据范围
    print(f"📅 数据范围: {df.index[0]} ~ {df.index[-1]}")
    print(f"📈 K线数量: {len(df)}")
    print()
    
    # 网格搜索
    print("🔍 开始网格搜索...")
    print(f"   参数组合数: {len(PARAM_BODY_MULTIPLIER) * len(PARAM_ATR_MULTIPLIER) * len(PARAM_FVG_ATR_PCT) * len(PARAM_RR_RATIO) * 3}")
    print()
    
    results_df = grid_search(df)
    
    # 排序
    results_df = results_df.sort_values('total_pnl_pct', ascending=False)
    
    # 显示 Top 10
    print("=" * 60)
    print("🏆 Top 10 参数组合 (按总收益排序)")
    print("=" * 60)
    
    top10 = results_df.head(10)
    
    for i, row in top10.iterrows():
        print(f"\n#{top10.index.get_loc(i) + 1}")
        print(f"  方法: {row['method'].upper()}")
        if row['method'] == 'body':
            print(f"  实体倍数: {row['body_mult']}x")
        elif row['method'] == 'atr':
            print(f"  ATR倍数: {row['atr_mult']}x")
        else:
            print(f"  确认方式: 吞没 (Engulfing)")
        print(f"  FVG/ATR%: {row['fvg_atr_pct']}%")
        print(f"  盈亏比: 1:{row['rr_ratio']}")
        print(f"  ---")
        print(f"  交易次数: {row['total_trades']}")
        print(f"  胜率: {row['win_rate']}%")
        print(f"  实际盈亏比: {row['actual_rr']}")
        print(f"  总收益: {row['total_pnl_pct']}%")
        print(f"  最大回撤: {row['max_drawdown_pct']}%")
    
    # 保存结果
    output_file = "/root/.openclaw/workspace/orderblock_results.csv"
    results_df.to_csv(output_file, index=False)
    print(f"\n📁 完整结果已保存: {output_file}")
    
    # 显示汇总
    print("\n" + "=" * 60)
    print("📊 汇总统计")
    print("=" * 60)
    print(f"测试参数组合: {len(results_df)}")
    print(f"盈利组合数: {len(results_df[results_df['total_pnl_pct'] > 0])}")
    print(f"最高收益: {results_df['total_pnl_pct'].max():.2f}%")
    print(f"平均收益: {results_df['total_pnl_pct'].mean():.2f}%")
    print(f"最高胜率: {results_df['win_rate'].max():.1f}%")

if __name__ == "__main__":
    main()
