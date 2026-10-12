import time
import requests
import ccxt
import pandas as pd
import numpy as np

# ==================== Telegram Settings ====================
TELEGRAM_BOT_TOKEN = "8905595519:AAFE__F6ipYCokzZhBkLYSAfKldfNzFsP3g"
TELEGRAM_CHAT_ID = "923277207"

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram error: {e}")

# ==================== Binance Futures Settings ====================
exchange = ccxt.binance({
    'options': {'defaultType': 'future'},
    'enableRateLimit': True
})

TIMEFRAMES = ['1h', '4h']
TREND_TIMEFRAME = '1d' # فريم القياس للاتجاه العام (اليومي)
last_signals = {} # Memory to prevent duplicate signals

def fetch_data(symbol, timeframe):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception:
        return None

def calculate_indicators(df):
    df['fastEMA'] = df['close'].ewm(span=7, adjust=False).mean()
    df['slowEMA'] = df['close'].ewm(span=21, adjust=False).mean()
    
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = true_range.rolling(14).mean()
    return df

def get_daily_trend(symbol):
    """
    دالة لفحص الاتجاه العام على الفريم اليومي (1d)
    ترجع True لو الاتجاه صاعد، و False لو هابط
    """
    df = fetch_data(symbol, TREND_TIMEFRAME)
    if df is None or len(df) < 30:
        return None
    df = calculate_indicators(df)
    i = -2
    return df['fastEMA'].iloc[i] > df['slowEMA'].iloc[i]

def check_signals(is_first_run):
    print("[*] Scanning market and filtering low volume coins (Volume > 10M)...")
    try:
        exchange.load_markets()
        tickers = exchange.fetch_tickers()
        
        symbols = []
        for s in exchange.symbols:
            if '/USDT:USDT' in s and not any(x in s for x in ['UP/', 'DOWN/', 'BEAR/', 'BULL/']):
                ticker = tickers.get(s, {})
                quote_volume = ticker.get('quoteVolume', 0)
                
                if quote_volume and quote_volume >= 10_000_000:
                    symbols.append(s)
                    
    except Exception as e:
        print(f"Error fetching or filtering symbols: {e}")
        return

    print(f"[*] Selected {len(symbols)} active symbols for scanning.")

    for timeframe in TIMEFRAMES:
        for symbol in symbols:
            # 1. فحص اتجاه الفريم اليومي أولاً لتصفية الصفقات المعاكسة
            daily_uptrend = get_daily_trend(symbol)
            if daily_uptrend is None:
                continue

            # 2. جلب بيانات الفريم المستهدف (1h أو 4h)
            df = fetch_data(symbol, timeframe)
            if df is None or len(df) < 30:
                continue
            
            df = calculate_indicators(df)
            i = -2 
            fast_curr, slow_curr = df['fastEMA'].iloc[i], df['slowEMA'].iloc[i]
            fast_prev, slow_prev = df['fastEMA'].iloc[i-1], df['slowEMA'].iloc[i-1]
            close_price = df['close'].iloc[i]
            atr_val = df['ATR'].iloc[i]
            
            is_long = (fast_prev <= slow_prev) and (fast_curr > slow_curr)
            is_short = (fast_prev >= slow_prev) and (fast_curr < slow_curr)
            
            signal_key = f"{symbol}_{timeframe}"
            
            if is_long or is_short:
                candle_timestamp = df['timestamp'].iloc[i]
                
                if is_first_run or last_signals.get(signal_key) == candle_timestamp:
                    continue

                # ==================== فلتر التريند الأكبر ====================
                # إذا كانت الإشارة LONG ولكن الفريم اليومي هابط -> نتجاهلها
                if is_long and not daily_uptrend:
                    continue
                # إذا كانت الإشارة SHORT ولكن الفريم اليومي صاعد -> نتجاهلها
                if is_short and daily_uptrend:
                    continue
                # ==========================================================
                
                last_signals[signal_key] = candle_timestamp
                
                direction = "LONG ▲" if is_long else "SHORT ▼"
                emoji = "🟢" if is_long else "🔴"
                
                if is_long:
                    entry = close_price
                    sl = entry - (atr_val * 1.5)
                    tp1 = entry + (atr_val * 2.0)
                    tp2 = entry + (atr_val * 4.0)
                else:
                    entry = close_price
                    sl = entry + (atr_val * 1.5)
                    tp1 = entry - (atr_val * 2.0)
                    tp2 = entry - (atr_val * 4.0)

                msg = (
                    f"🚨 *New Filtered Signal ({timeframe})* {emoji}\n\n"
                    f"🪙 Symbol: `{symbol}`\n"
                    f"📊 Direction: *{direction}*\n"
                    f"🎯 Entry: `{entry:.4f}`\n"
                    f"🛑 SL: `{sl:.4f}`\n"
                    f"🟢 TP1: `{tp1:.4f}`\n"
                    f"🟢 TP2: `{tp2:.4f}`\n"
                    f"⏱ Timeframe: `{timeframe}`"
                )
                send_telegram_message(msg)
                print(f"[+] Sent high-quality trend-aligned signal for {symbol} on {timeframe}")
                
            time.sleep(0.1)

if __name__ == "__main__":
    print("=== Futures Bot Started (Daily Trend Filter + 10M Volume + No Duplicates) ===")
    first_run = True
    while True:
        try:
            check_signals(first_run)
            first_run = False
            print("[*] Scan completed successfully. Waiting for the next cycle...")
            time.sleep(300) 
        except KeyboardInterrupt:
            print("Bot stopped by user.")
            break
        except Exception as e:
            print(f"An error occurred: {e}")
            time.sleep(60)