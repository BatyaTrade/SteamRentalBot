# bot/steam_api.py
import logging
import base64
import pyotp
import asyncio
import concurrent.futures
from steam.client import SteamClient
from steam.enums.common import EResult
from steam.webapi import WebAPI
from bot.utils import decrypt_data
from bot.database import get_db
from bot.models import Account

async def change_password(login: str, current_password: str, new_password: str, owner_tg_id: int) -> bool:
    logging.info(f"[STEAM API] Запуск смены пароля для {login}...")

    def _do_change_password():
        db_gen = get_db()
        db = next(db_gen)
        db_account = db.query(Account).filter(Account.login == login, Account.owner_tg_id == owner_tg_id).first()
        db.close()

        if not db_account:
            logging.error(f"[STEAM API THREAD] Аккаунт {login} не найден.")
            return False

        try:
            shared_secret_encrypted = db_account.shared_secret_encrypted
            shared_secret_b64 = decrypt_data(shared_secret_encrypted)

            try:
                secret_bytes = base64.b64decode(shared_secret_b64)
                secret_b32 = base64.b32encode(secret_bytes).decode('utf-8')
                totp = pyotp.TOTP(secret_b32)
                twofactor_code = totp.now()
                logging.debug(f"[STEAM API THREAD] 2FA код для {login}: {twofactor_code}")
            except Exception as e:
                logging.error(f"[STEAM API THREAD] Ошибка генерации 2FA: {e}")
                return False

            client = SteamClient()
            logging.debug(f"[STEAM API THREAD] Попытка логина для {login}...")
            
            login_result = client.login(login, current_password, two_factor_code=twofactor_code)

            if login_result != EResult.OK:
                logging.error(f"[STEAM API THREAD] Ошибка логина для {login}: {login_result}")
                return False

            logging.info(f"[STEAM API THREAD] Успешный логин для {login}.")

            try:
                api_key = client.get_web_api_key()
                if not api_key:
                    logging.error(f"[STEAM API THREAD] Не удалось получить WebAPI ключ.")
                    client.logout()
                    return False
                logging.debug(f"[STEAM API THREAD] WebAPI ключ получен.")
            except Exception as e:
                logging.error(f"[STEAM API THREAD] Ошибка получения WebAPI ключа: {e}")
                client.logout()
                return False

            if not client.steam_id:
                logging.error(f"[STEAM API THREAD] SteamID не получен после логина.")
                client.logout()
                return False

            try:
                api = WebAPI(key=api_key, format='json')
                params = {
                    'steamid': client.steam_id,
                    'password': current_password,
                    'new_password': new_password,
                    'code': twofactor_code,
                }
                logging.debug(f"[STEAM API THREAD] Вызов IAccountService.ChangePassword...")
                response = api.call('IAccountService', 'ChangePassword', 'v1', **params)
                logging.debug(f"[STEAM API THREAD] Ответ: {response}")

                if isinstance(response, dict) and 'response' in response:
                    resp_body = response['response']
                    if isinstance(resp_body, dict):
                        if not resp_body:
                            logging.info(f"[STEAM API THREAD] Пароль для {login} успешно изменен.")
                            client.logout()
                            return True
                        elif 'error' in resp_body:
                            error_msg = resp_body['error']
                            logging.error(f"[STEAM API THREAD] Ошибка WebAPI: {error_msg}")
                            client.logout()
                            return False
                        else:
                            logging.warning(f"[STEAM API THREAD] Неожиданный ответ: {resp_body}")
                            client.logout()
                            return False
                    else:
                        logging.error(f"[STEAM API THREAD] Неверный формат response['response']: {resp_body}")
                        client.logout()
                        return False
                else:
                    logging.error(f"[STEAM API THREAD] Неверный формат ответа: {response}")
                    client.logout()
                    return False
            except Exception as e:
                logging.error(f"[STEAM API THREAD] Ошибка вызова WebAPI: {e}", exc_info=True)
                client.logout()
                return False

        except Exception as e:
            logging.error(f"[STEAM API THREAD] Необработанная ошибка для {login}: {e}", exc_info=True)
            return False

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as executor:
        try:
            result = await loop.run_in_executor(executor, _do_change_password)
            return result
        except concurrent.futures.TimeoutError:
            logging.error(f"[STEAM API] Таймаут при смене пароля для {login}")
            return False
        except Exception as e:
            logging.error(f"[STEAM API] Ошибка в потоке для {login}: {e}", exc_info=True)
            return False