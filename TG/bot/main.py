import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Используем бэкенд без GUI
import matplotlib.pyplot as plt
import telebot
from io import BytesIO
# Telegram API токен
API_TOKEN = '7647511729:AAG5-Iin2wNG16HLGBSBqU0gIxCSDz6iPTw'
bot = telebot.TeleBot(API_TOKEN)

# Словарь для хранения выбранных валютных пар пользователями
user_pairs = {}

# Функция для получения текущей цены с Binance
def get_binance_price(symbol):
    url = f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}'
    response = requests.get(url)
    if response.status_code != 200:
        raise ValueError(f"Не удалось получить данные с Binance для пары {symbol}. Проверьте символ.")
    data = response.json()
    return float(data['price'])

# Функция для получения исторических данных с Binance
def get_historical_data(symbol, interval='1d', limit=100):
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    response = requests.get(url)
    if response.status_code != 200:
        raise ValueError(f"Не удалось получить исторические данные для пары {symbol}.")
    data = response.json()
    return [(float(item[1]), float(item[4])) for item in data]  # (Open, Close)

# Рассчитываем простую скользящую среднюю (SMA)
def moving_average(data, window=14):
    close_prices = [item[1] for item in data]
    df = pd.DataFrame(close_prices, columns=['Close'])
    df['SMA'] = df['Close'].rolling(window=window).mean()
    return df['SMA'].tolist()

# Рассчитываем экспоненциальную скользящую среднюю (EMA)
def exponential_moving_average(data, window=14):
    close_prices = [item[1] for item in data]
    df = pd.DataFrame(close_prices, columns=['Close'])
    df['EMA'] = df['Close'].ewm(span=window, adjust=False).mean()
    return df['EMA'].tolist()

# Рассчитываем MACD
def macd(data):
    close_prices = [item[1] for item in data]
    df = pd.DataFrame(close_prices, columns=['Close'])
    short_ema = df['Close'].ewm(span=12, adjust=False).mean()
    long_ema = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = short_ema - long_ema
    df['Signal Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    return df['MACD'].tolist(), df['Signal Line'].tolist()

# Рассчитываем Bollinger Bands
def bollinger_bands(data, window=20):
    close_prices = [item[1] for item in data]
    df = pd.DataFrame(close_prices, columns=['Close'])
    sma = df['Close'].rolling(window=window).mean()
    std = df['Close'].rolling(window=window).std()
    df['Upper Band'] = sma + (std * 2)
    df['Lower Band'] = sma - (std * 2)
    return df['Upper Band'].tolist(), df['Lower Band'].tolist()

# Рассчитываем RSI вручную
def rsi(data, period=14):
    close_prices = [item[1] for item in data]
    deltas = np.diff(close_prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    rsi_values = []
    for i in range(period, len(close_prices)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period

        rs = avg_gain / avg_loss if avg_loss != 0 else 0
        rsi = 100 - (100 / (1 + rs))
        rsi_values.append(rsi)

    return rsi_values

# Генерация торговых сигналов на основе индикаторов
def generate_signals(data):
    close_prices = [item[1] for item in data]
    sma = moving_average(data)
    ema = exponential_moving_average(data)
    rsi_values = rsi(data)
    macd_values, signal_line = macd(data)
    upper_band, lower_band = bollinger_bands(data)

    last_price = close_prices[-1]
    last_sma = sma[-1]
    last_ema = ema[-1]
    last_rsi = rsi_values[-1]
    last_macd = macd_values[-1]
    last_signal_line = signal_line[-1]
    last_upper_band = upper_band[-1]
    last_lower_band = lower_band[-1]

    signals = []

    # Добавление сигнала на основе пересечения SMA/EMA и цены
    if last_price > last_sma and last_price > last_ema:
        signals.append("💹 Buy: Цена выше SMA и EMA")
    elif last_price < last_sma and last_price < last_ema:
        signals.append("📉 Sell: Цена ниже SMA и EMA")

    # Сигнал на основе RSI
    if last_rsi < 30:
        signals.append("RSI: Перепроданность (ниже 30)")
    elif last_rsi > 70:
        signals.append("RSI: Перекупленность (выше 70)")

    # Сигнал на основе MACD
    if last_macd > last_signal_line:
        signals.append("MACD: Бычий сигнал")
    elif last_macd < last_signal_line:
        signals.append("MACD: Медвежий сигнал")

    # Сигнал на основе Bollinger Bands
    if last_price > last_upper_band:
        signals.append("Bollinger Bands: Цена выше верхней границы (перекупленность)")
    elif last_price < last_lower_band:
        signals.append("Bollinger Bands: Цена ниже нижней границы (перепроданность)")

    return "\n".join(signals)

# Команда /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я бот для анализа криптовалютного рынка. Используй команды /setpair для выбора валютной пары, /price для получения цены и /signal для анализа.")

# Команда /setpair для выбора торговой пары
@bot.message_handler(commands=['setpair'])
def set_pair(message):
    msg = bot.reply_to(message, "Введите символ криптовалютной пары (например, BTCUSDT):")
    bot.register_next_step_handler(msg, save_pair)

def save_pair(message):
    user_id = message.from_user.id
    pair = message.text.upper()
    try:
        # Проверяем, существует ли пара
        get_binance_price(pair)
        user_pairs[user_id] = pair
        bot.reply_to(message, f"Вы выбрали пару: {pair}")
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {str(e)}")

# Команда /price для получения текущей цены выбранной пары
@bot.message_handler(commands=['price'])
def get_price(message):
    try:
        user_id = message.from_user.id
        symbol = user_pairs.get(user_id, 'BTCUSDT')  # По умолчанию BTCUSDT, если пара не выбрана
        price = get_binance_price(symbol)
        bot.reply_to(message, f"Текущая цена {symbol}: ${price}")
    except Exception as e:
        bot.reply_to(message, f"Ошибка при получении цены: {str(e)}")

# Команда /signal для получения торгового сигнала для выбранной пары
@bot.message_handler(commands=['signal'])
def get_signal(message):
    try:
        user_id = message.from_user.id
        symbol = user_pairs.get(user_id, 'BTCUSDT')  # По умолчанию BTCUSDT, если пара не выбрана
        data = get_historical_data(symbol)
        signal = generate_signals(data)

        # Генерация графика для визуализации
        close_prices = [item[1] for item in data]
        plt.style.use('fivethirtyeight')  # Пример другого доступного стиля
        plt.figure(figsize=(10, 6))
        plt.plot(close_prices, label='Цена закрытия')
        plt.title(f'{symbol} Цена закрытия')
        plt.legend()
        plt.tight_layout()

        # Сохранение графика в буфер
        buffer = BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        plt.close()

        # Отправка графика и сигнала
        bot.send_photo(message.chat.id, buffer, caption=f"Торговый сигнал для {symbol}:\n{signal}")
    except Exception as e:
        bot.reply_to(message, f"Ошибка при генерации сигнала: {str(e)}")

# Запуск бота
bot.polling(none_stop=True)