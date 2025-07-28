# bot/funpay_integration.py
import sys
import os

# Добавляем путь к funpay_lib в sys.path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'funpay_lib'))

import logging
from flask import Flask, request, jsonify
import threading
import asyncio
from datetime import datetime, timedelta
from bot.database import get_db
from bot.models import Account, Owner, Transaction
from bot.steam_api import change_password
from bot.utils import generate_secure_password, parse_account_id_from_product_name, get_decrypted_funpay_creds
from bot.bot import get_bot_instance

try:
    from FunPayAPI.account import Account as FunPayAPIAccount
    FUNPAY_API_AVAILABLE = True
    logging.info("FunPayCardinal (локальная копия) успешно импортирован.")
except ImportError as e:
    logging.warning(f"FunPayCardinal не найден или ошибка импорта: {e}")
    FUNPAY_API_AVAILABLE = False
    FunPayAPIAccount = None

def get_funpay_account_for_owner(owner_tg_id: int):
    if not FUNPAY_API_AVAILABLE:
        return None
    try:
        creds = get_decrypted_funpay_creds(owner_tg_id)
        if creds:
            user_id, golden_key = creds
            fp_acc = FunPayAPIAccount(user_id=user_id, golden_key=golden_key)
            return fp_acc
        else:
            logging.warning(f"FP creds not found for owner {owner_tg_id}")
            return None
    except Exception as e:
        logging.error(f"Error creating FP API for owner {owner_tg_id}: {e}")
        return None

async def notify_owner(owner_tg_id: int, message: str):
    bot_instance = get_bot_instance()
    if bot_instance:
        try:
            await bot_instance.send_message(chat_id=owner_tg_id, text=message)
        except Exception as e:
            logging.error(f"[NOTIFY] Ошибка уведомления владельца {owner_tg_id}: {e}")

def process_order(order_data):
    logging.info(f"[FUNPAY] Обработка аренды: {order_data}")
    try:
        buyer = order_data.get('buyer')
        product_name = order_data.get('product')
        duration = int(order_data.get('duration', 1))
        order_id = order_data.get('order_id')

        account_id = parse_account_id_from_product_name(product_name)
        if not account_id:
            logging.error(f"[FUNPAY] Не найден ID аккаунта в '{product_name}'")
            return

        db_gen = get_db()
        db = next(db_gen)
        account = db.query(Account).filter(Account.id == account_id).first()
        owner = account.owner if account else None
        owner_tg_id = owner.tg_id if owner else None
        db.close()

        if not account or not owner:
            logging.error(f"[FUNPAY] Аккаунт {account_id} или владелец не найдены.")
            return

        if account.status != 'available':
            msg = f"❌ Аренда аккаунта {account.login} отклонена. Статус: {account.status}."
            logging.warning(f"[FUNPAY] {msg}")
            asyncio.run(notify_owner(owner_tg_id, msg))
            fp_acc = get_funpay_account_for_owner(owner_tg_id)
            if fp_acc:
                try:
                    fp_acc.send_message(buyer, f"❌ Извините, аккаунт {account.login} временно недоступен.")
                except Exception as e:
                    logging.error(f"[FUNPAY] Ошибка отправки сообщения покупателю {buyer}: {e}")
            return

        temp_password = generate_secure_password()
        current_pass_to_use = account.current_password or decrypt_data(account.base_password_encrypted)

        process_msg = f"🔄 Начата аренда аккаунта {account.login} для {buyer} на {duration} ч."
        asyncio.run(notify_owner(owner_tg_id, process_msg))

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        change_result = loop.run_until_complete(
            change_password(account.login, current_pass_to_use, temp_password, owner_tg_id)
        )
        loop.close()

        if not change_result:
            error_msg = f"❌ Ошибка смены пароля для аккаунта {account.login}. Аренда отменена."
            logging.error(f"[FUNPAY] {error_msg}")
            asyncio.run(notify_owner(owner_tg_id, error_msg))
            fp_acc = get_funpay_account_for_owner(owner_tg_id)
            if fp_acc:
                try:
                    fp_acc.send_message(buyer, f"❌ Произошла ошибка. Средства будут возвращены.")
                except Exception as e:
                    logging.error(f"[FUNPAY] Ошибка отправки сообщения покупателю {buyer}: {e}")
            return

        db_gen = get_db()
        db = next(db_gen)
        account_to_update = db.query(Account).filter(Account.id == account_id).first()
        if account_to_update:
            account_to_update.status = "rented"
            account_to_update.renter_username = buyer
            account_to_update.rent_end_time = datetime.utcnow() + timedelta(hours=duration)
            account_to_update.current_password = temp_password
            db.commit()
            
            rental_transaction = Transaction(
                owner_id=owner.id,
                account_id=account_id,
                transaction_type='rental',
                external_id=order_id,
                amount=account_to_update.price_per_hour * duration,
                status='completed'
            )
            db.add(rental_transaction)
            db.commit()
            
            success_msg = f"✅ Аккаунт {account.login} успешно арендован пользователю {buyer} на {duration} ч."
            logging.info(f"[FUNPAY] {success_msg}")
            asyncio.run(notify_owner(owner_tg_id, success_msg))
            db.close()
        else:
            db.close()
            error_msg_db = f"❌ Аккаунт {account_id} исчез из БД перед обновлением."
            logging.error(f"[FUNPAY] {error_msg_db}")
            asyncio.run(notify_owner(owner_tg_id, error_msg_db))
            return

        fp_acc = get_funpay_account_for_owner(owner_tg_id)
        if fp_acc:
            try:
                message_text = (
                    f"✅ Аренда аккаунта подтверждена!\n"
                    f"Логин: {account.login}\n"
                    f"Пароль: {temp_password}\n"
                    f"Доступен на {duration} часов.\n"
                    f"❗Важно: Выйдите из аккаунта по окончании!"
                )
                fp_acc.send_message(buyer, message_text)
                logging.info(f"[FUNPAY] Данные доступа отправлены покупателю {buyer}.")
            except Exception as e:
                logging.error(f"[FUNPAY] Ошибка отправки сообщения покупателю {buyer}: {e}")
                asyncio.run(notify_owner(owner_tg_id, f"⚠️ Не удалось отправить данные арендатору {buyer}."))
        else:
             error_msg_fp = f"⚠️ Не удалось отправить данные арендатору {buyer} (FP API недоступен)."
             logging.error(f"[FUNPAY] {error_msg_fp}")
             asyncio.run(notify_owner(owner_tg_id, error_msg_fp))

    except Exception as e:
        logging.critical(f"[FUNPAY] Критическая ошибка обработки аренды {order_data}: {e}", exc_info=True)

def create_funpay_webhook_handler(app: Flask):
    @app.route('/funpay/webhook', methods=['POST'])
    def funpay_webhook():
        data = request.get_json()
        logging.debug(f"[FUNPAY WEBHOOK] Получены данные: {data}")
        if data and data.get('event') == 'order_completed':
            thread = threading.Thread(target=process_order, args=(data,))
            logging.info("[FUNPAY WEBHOOK] Запущена обработка аренды в новом потоке.")
            thread.start()
            return jsonify(status="ok", message="Order received."), 200
        else:
            logging.warning("[FUNPAY WEBHOOK] Получено необрабатываемое событие.")
            return jsonify(status="ignored", message="Event not handled."), 200
