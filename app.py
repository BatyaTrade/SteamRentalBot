# app.py
import threading
import logging
from flask import Flask, request
from bot.bot import run_bot
from bot.database import init_db
from bot.funpay_integration import create_funpay_webhook_handler
from apscheduler.schedulers.background import BackgroundScheduler
from bot.scheduler import check_expired_rentals
import asyncio

# YooKassa
try:
    import yookassa
    from yookassa import Webhook
    YOOKASSA_IMPORT_SUCCESS = True
except ImportError:
    logging.error("Не удалось импортировать YooKassa SDK.")
    YOOKASSA_IMPORT_SUCCESS = False
    yookassa = None
    Webhook = None

# Импорты для вебхука Юкассы
from bot.config import YOOKASSA_ENABLED, YOOKASSA_ACCOUNT_ID, YOOKASSA_SECRET_KEY, YOOKASSA_WEBHOOK_URL
from bot.database import get_db
from bot.models import Owner
# import json # json уже импортирован в Flask

def create_app():
    """Создает и конфигурирует Flask приложение."""
    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)

    # Инициализируем БД
    init_db()

    # Регистрируем вебхук FunPay
    create_funpay_webhook_handler(app)

    # Функция-обертка для запуска асинхронной задачи в синхронном планировщике
    def run_check_expired_rentals():
        """Обертка для запуска асинхронной задачи check_expired_rentals."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(check_expired_rentals())

    # Инициализируем и запускаем планировщик
    scheduler = BackgroundScheduler()
    # Задача выполняется каждые 5 минут
    scheduler.add_job(run_check_expired_rentals, 'interval', minutes=5, id='check_expired_rentals')
    scheduler.start()
    logging.info("APScheduler started with check_expired_rentals job.")

    # --- YooKassa Webhook ---
    if YOOKASSA_ENABLED and YOOKASSA_IMPORT_SUCCESS and YOOKASSA_ACCOUNT_ID and YOOKASSA_SECRET_KEY:
        @app.route('/payment/yookassa/webhook', methods=['POST'])
        def yookassa_webhook():
            """Обрабатывает вебхук от YooKassa о статусе платежа."""
            # Получаем данные и подпись из запроса
            event_json = request.get_json()
            # signature = request.headers.get('yookassa-signature') # Опционально для проверки

            logging.debug(f"[YOOKASSA WEBHOOK] Получены данные: {event_json}")
            
            try:
                # Проверяем подпись для безопасности (рекомендуется)
                # if signature: Webhook.check_sign(event_json, signature) 
                
                if event_json.get('event') == 'payment.succeeded':
                    payment_object = event_json.get('object')
                    # Извлекаем данные из метаданных платежа
                    user_id_str = payment_object.get('metadata', {}).get('tg_user_id')
                    amount_value = payment_object.get('amount', {}).get('value')
                    currency = payment_object.get('amount', {}).get('currency')
                    payment_id = payment_object.get('id')

                    if user_id_str and amount_value and currency == "RUB":
                        try:
                            user_id = int(user_id_str)
                            amount = float(amount_value)
                            
                            # Начисляем средства владельцу
                            db_gen = get_db()
                            db = next(db_gen)
                            owner = db.query(Owner).filter(Owner.tg_id == user_id).first()
                            if owner:
                                owner.balance = float(owner.balance or 0) + amount
                                db.commit()
                                
                                # Логируем успешное пополнение
                                logging.info(
                                    f"[YOOKASSA] Баланс пользователя {user_id} "
                                    f"пополнен на {amount} {currency}. Payment ID: {payment_id}"
                                )
                                
                                db.close()
                                return '', 200 # Важно вернуть 200, чтобы Юкасса не ретранслировала
                            else:
                                db.close()
                                logging.error(f"[YOOKASSA] Владелец с TG ID {user_id} не найден.")
                                return 'Owner not found', 400
                        except ValueError as e:
                            logging.error(f"[YOOKASSA] Ошибка конвертации данных: {e}")
                            return 'Bad Data', 400
                    else:
                        logging.error(f"[YOOKASSA] Некорректные данные в вебхуке: {event_json}")
                        return 'Bad Request', 400
                else:
                    logging.info(f"[YOOKASSA] Получено другое событие: {event_json.get('event')}")
                return '', 200
            except Exception as e:
                logging.error(f"[YOOKASSA] Ошибка обработки вебхука: {e}", exc_info=True)
                # Не возвращаем 500, чтобы Юкасса не считала это критической ошибкой сразу
                return 'Internal Error', 500 

        logging.info(f"Вебхук YooKassa зарегистрирован по адресу: {YOOKASSA_WEBHOOK_URL}")
    else:
        logging.info("Вебхук YooKassa НЕ зарегистрирован (SDK не импортирован или конфигурация отсутствует).")

    @app.route('/')
    def index():
        """Простая страница для проверки работы Flask."""
        return "Steam Rental Bot is running!"

    return app

# --- Точка входа при запуске файла напрямую ---
if __name__ == '__main__':
    import os
    # Определяем режим запуска: 'bot', 'web', 'all'
    mode = os.environ.get('RUN_MODE', 'all')

    if mode in ['all', 'web']:
        # Запускаем Flask-приложение (веб-сервер для вебхуков)
        app = create_app()
        port = int(os.environ.get("PORT", 5000))
        # Запуск Flask в отдельном потоке, чтобы не блокировать основной поток
        flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, debug=False))
        flask_thread.start()
        print(f"Flask server started on port {port}")

    if mode in ['all', 'bot']:
        # Запускаем Telegram-бота
        print("Starting Telegram Bot...")
        # ИСПРАВЛЕНО: Вызываем run_bot, а не main
        run_bot() # run_bot() сам по себе блокирующий
