import pandas as pd
import numpy as np

class TechnicalIndicators:
    def __init__(self, data):
        self.data = data

    def calculate_rsi(self, periods=14):
        delta = self.data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=periods).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=periods).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_macd(self, short_window=12, long_window=26, signal_window=9):
        exp1 = self.data['Close'].ewm(span=short_window, adjust=False).mean()
        exp2 = self.data['Close'].ewm(span=long_window, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=signal_window, adjust=False).mean()
        return macd, signal

    def calculate_bollinger_bands(self, window=20, no_of_std=2):
        rolling_mean = self.data['Close'].rolling(window=window).mean()
        rolling_std = self.data['Close'].rolling(window=window).std()
        upper_band = rolling_mean + (rolling_std * no_of_std)
        lower_band = rolling_mean - (rolling_std * no_of_std)
        return upper_band, lower_band

    def calculate_moving_average(self, window=50):
        return self.data['Close'].rolling(window=window).mean()