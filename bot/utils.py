# bot/utils.py
import os
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
import secrets
import string
from typing import Optional # Импорт для аннотаций
from bot.config import MASTER_ENCRYPTION_KEY
from bot.database import get_db
from bot.models import Owner
from datetime import datetime, timedelta

class SimpleCrypto:
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("Key must be 32 bytes long for AES-256")
        self.key = key
        self.backend = default_backend()

    def encrypt(self, plaintext: bytes) -> bytes:
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(iv), backend=self.backend)
        encryptor = cipher.encryptor()
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(plaintext)
        padded_data += padder.finalize()
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()
        return iv + ciphertext

    def decrypt(self, ciphertext: bytes) -> bytes:
        iv = ciphertext[:16]
        actual_ciphertext = ciphertext[16:]
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(iv), backend=self.backend)
        decryptor = cipher.decryptor()
        padded_plaintext = decryptor.update(actual_ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_plaintext)
        plaintext += unpadder.finalize()
        return plaintext

# --- ИНИЦИАЛИЗАЦИЯ КРИПТО-ОБЪЕКТА ---
# ВАЖНО: Убедитесь, что MASTER_ENCRYPTION_KEY в .env содержит ровно 32 символа.
# Если ключ неверный, бот упадет при импорте этого модуля.
try:
    _crypto = SimpleCrypto(MASTER_ENCRYPTION_KEY.encode())
    _CRYPTO_AVAILABLE = True
except ValueError as e:
    print(f"[ERROR] Ошибка инициализации криптографии: {e}")
    print("[ERROR] Проверьте переменную MASTER_ENCRYPTION_KEY в .env. Она должна быть длиной 32 символа.")
    _crypto = None
    _CRYPTO_AVAILABLE = False
# -----------------------------------

def encrypt_data(data: str) -> bytes:
    """Шифрует строку и возвращает байты."""
    if not _CRYPTO_AVAILABLE or _crypto is None:
        raise RuntimeError("Криптография недоступна. Проверьте MASTER_ENCRYPTION_KEY.")
    return _crypto.encrypt(data.encode('utf-8'))

def decrypt_data(encrypted_data: bytes) -> str: # <-- ИСПРАВЛЕНО: правильное имя параметра
    """Расшифровывает байты и возвращает строку."""
    if not _CRYPTO_AVAILABLE or _crypto is None:
        raise RuntimeError("Криптография недоступна. Проверьте MASTER_ENCRYPTION_KEY.")
    return _crypto.decrypt(encrypted_data).decode('utf-8')

def generate_secure_password(length=12) -> str:
    """Генерирует безопасный случайный пароль."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def parse_account_id_from_product_name(product_name: str) -> Optional[int]: # <-- ИСПРАВЛЕНО: Аннотация
    """Парсит ID аккаунта из названия товара FunPay."""
    import re
    match = re.search(r'\[ID:(\d+)\]', product_name)
    if match:
        return int(match.group(1))
    return None

# --- ХЕЛПЕРЫ ДЛЯ ПОДПИСКИ ---
def is_user_subscribed(owner_tg_id: int) -> bool:
    """Проверяет, подписан ли пользователь."""
    try:
        db_gen = get_db()
        db = next(db_gen)
        owner = db.query(Owner).filter(Owner.tg_id == owner_tg_id).first()
        db.close()
        if owner and owner.is_subscribed():
            return True
        return False
    except Exception:
        return False

def get_decrypted_funpay_creds(owner_tg_id: int) -> Optional[tuple[str, str]]:
    """Получает и расшифровывает учетные данные FunPay для владельца."""
    try:
        db_gen = get_db()
        db = next(db_gen)
        owner = db.query(Owner).filter(Owner.tg_id == owner_tg_id).first()
        db.close()
        if owner and owner.has_funpay_credentials():
            user_id = decrypt_data(owner.funpay_user_id_encrypted)
            golden_key = decrypt_data(owner.funpay_golden_key_encrypted)
            return user_id, golden_key
        return None
    except Exception as e:
        print(f"Error getting FunPay creds for {owner_tg_id}: {e}")
        return None

# --- ДЕКОРАТОР ДЛЯ ПРОВЕРКИ FUNPAY CREDENTIALS ---
def funpay_creds_required(func):
    async def wrapper(update, context):
        from bot.utils import get_decrypted_funpay_creds
        user_id = update.effective_user.id
        creds = get_decrypted_funpay_creds(user_id)
        if not creds:
            await update.message.reply_text(
                "⚠️ Учетные данные FunPay не найдены.\n"
                "Пожалуйста, добавьте их через меню 'Мои аккаунты FunPay'."
            )
            return
        return await func(update, context)
    return wrapper

# --- ХЕЛПЕР ДЛЯ ПОДПИСКИ ---
def add_subscription_days(owner, days: int):
    """Добавляет дни подписки владельцу."""
    current_end = owner.subscription_end or datetime.utcnow()
    if current_end < datetime.utcnow():
        new_end = datetime.utcnow() + timedelta(days=days)
    else:
        new_end = current_end + timedelta(days=days)
    owner.subscription_end = new_end
    return new_end
