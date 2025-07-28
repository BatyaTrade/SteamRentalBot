# bot/config.py
import os
import json
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен в .env файле")

# Database
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "steam_rental_db")
DB_USER = os.getenv("DB_USER", "tradebatyachrono")
DB_PASS = os.getenv("DB_PASS", "260502")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Security
MASTER_ENCRYPTION_KEY = os.getenv("MASTER_ENCRYPTION_KEY")
if not MASTER_ENCRYPTION_KEY or len(MASTER_ENCRYPTION_KEY.encode()) < 32:
    raise ValueError("MASTER_ENCRYPTION_KEY должен быть длиной не менее 32 символов")

# Admins
ADMIN_USER_IDS = [int(id.strip()) for id in os.getenv("ADMIN_USER_IDS", "").split(",") if id.strip().isdigit()]

# YooKassa
YOOKASSA_ACCOUNT_ID = os.getenv("YOOKASSA_ACCOUNT_ID")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
YOOKASSA_WEBHOOK_URL = os.getenv("YOOKASSA_WEBHOOK_URL", "https://yourdomain.com/payment/yookassa/webhook")
YOOKASSA_ENABLED = bool(YOOKASSA_ACCOUNT_ID and YOOKASSA_SECRET_KEY)

# Subscription
try:
    SUBSCRIPTION_PLANS = json.loads(os.getenv("SUBSCRIPTION_PLANS", "{}"))
except json.JSONDecodeError:
    SUBSCRIPTION_PLANS = {
        '1w': {'duration_days': 7, 'price': 50.00},
        '1m': {'duration_days': 30, 'price': 150.00},
        '3m': {'duration_days': 90, 'price': 400.00},
    }

try:
    MIN_TOPUP_AMOUNT = float(os.getenv("MIN_TOPUP_AMOUNT", "10.0"))
except ValueError:
    MIN_TOPUP_AMOUNT = 10.0