# config.py
# Central configuration for the dashboard


import pytz


# ─── Timezone ────────────────────────────────────────────────────────────────
IST = pytz.timezone("Asia/Kolkata")


# ─── Refresh interval (seconds) ──────────────────────────────────────────────
AUTO_REFRESH_SECONDS = 60


# ─── Data periods ────────────────────────────────────────────────────────────
HISTORY_PERIOD = "1y" # for DMA / RS calculations
INTRADAY_PERIOD = "5d"
INTRADAY_INTERVAL = "5m"


# ─── Technical parameters ────────────────────────────────────────────────────
RSI_PERIOD = 14
EMA_SHORT = 20
EMA_MID = 50
EMA_LONG = 200
VOLUME_MA_PERIOD = 20


# ─── Momentum score weights ──────────────────────────────────────────────────
MOMENTUM_WEIGHTS = {
    "rsi_score": 0.25,
    "rs_score": 0.30,
    "ema_score": 0.25,
    "volume_score": 0.20,
}


# ─── Grade thresholds ────────────────────────────────────────────────────────
GRADE_A_THRESHOLD = 70
GRADE_B_THRESHOLD = 45


# ─── Color palette ───────────────────────────────────────────────────────────
COLORS = {
    "background": "#0E1117",
    "card_bg": "#1C2333",
    "accent": "#00D4FF",
    "green": "#00FF88",
    "red": "#FF4B6E",
    "yellow": "#FFD700",
    "text": "#E8EDF5",
    "subtext": "#8892A4",
    "border": "#2D3748",
    "grade_a": "#00FF88",
    "grade_b": "#FFD700",
    "grade_c": "#FF4B6E",
}


PLOTLY_TEMPLATE = "plotly_dark"


# ─── EMA options for candlestick ─────────────────────────────────────────────
CANDLESTICK_EMAS = [5, 10, 21, 50]

