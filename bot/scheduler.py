# bot/scheduler.py
import logging
from datetime import datetime
import asyncio
from bot.database import get_db
from bot.models import Account
from bot.steam_api import change_password
from bot.utils import generate_secure_password, decrypt_data
from bot.bot import get_bot_instance

async def notify_owner(owner_tg_id: int, message: str):
    bot_instance = get_bot_instance()
    if bot_instance:
        try:
            await bot_instance.send_message(chat_id=owner_tg_id, text=message)
            logging.info(f"[SCHEDULER NOTIFY] Уведомление отправлено владельцу {owner_tg_id}.")
        except Exception as e:
            logging.error(f"[SCHEDULER NOTIFY] Ошибка отправки уведомления владельцу {owner_tg_id}: {e}")

async def check_expired_rentals(app=None):
    logging.info("[SCHEDULER] Начало проверки истекших аренд...")
    try:
        db_gen = get_db()
        db = next(db_gen)
        now = datetime.utcnow()
        expired_accounts = db.query(Account).filter(
            Account.status == 'rented',
            Account.rent_end_time < now
        ).all()

        if not expired_accounts:
            logging.info("[SCHEDULER] Нет истекших аренд.")
            db.close()
            return

        logging.info(f"[SCHEDULER] Найдено {len(expired_accounts)} истекших аренд.")

        for account in expired_accounts:
            try:
                logging.info(f"[SCHEDULER] Обрабатываем {account.login} (ID: {account.id})...")
                new_password = generate_secure_password()
                owner_tg_id = account.owner.tg_id
                old_temp_password = account.current_password or decrypt_data(account.base_password_encrypted)

                await notify_owner(owner_tg_id, f"🔄 Начат процесс завершения аренды аккаунта {account.login}...")

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                change_result = loop.run_until_complete(
                    change_password(account.login, old_temp_password, new_password, owner_tg_id)
                )
                loop.close()

                if not change_result:
                    error_msg = f"❌ Ошибка сброса пароля для аккаунта {account.login} при завершении аренды."
                    logging.error(f"[SCHEDULER] {error_msg}")
                    await notify_owner(owner_tg_id, error_msg)
                    continue

                account.status = "available"
                account.current_password = None
                account.renter_username = None
                account.rent_end_time = None
                db.commit()
                success_msg = f"✅ Аренда аккаунта {account.login} успешно завершена."
                logging.info(f"[SCHEDULER] {success_msg}")
                await notify_owner(owner_tg_id, success_msg)

            except Exception as e:
                logging.error(f"[SCHEDULER] Ошибка обработки {account.login} (ID: {account.id}): {e}", exc_info=True)
                await notify_owner(owner_tg_id, f"❌ Критическая ошибка при завершении аренды {account.login}.")

        db.close()
        logging.info("[SCHEDULER] Проверка истекших аренд завершена.")

    except Exception as e:
        logging.critical(f"[SCHEDULER] Критическая ошибка: {e}", exc_info=True)