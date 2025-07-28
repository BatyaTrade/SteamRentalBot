import logging
# Импортируем ReplyKeyboard
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from bot.database import get_db
from bot.models import Owner, FunPayAccount, Account, Transaction
from bot.utils import encrypt_data, is_user_subscribed, funpay_creds_required, add_subscription_days, decrypt_data
from bot.config import TELEGRAM_BOT_TOKEN, SUBSCRIPTION_PLANS, MIN_TOPUP_AMOUNT, YOOKASSA_ENABLED
from datetime import datetime, timedelta
import uuid

try:
    from yookassa import Payment
    YOOKASSA_SDK_AVAILABLE = True
except ImportError:
    Payment = None
    YOOKASSA_SDK_AVAILABLE = False

# --- Декораторы ---
def subscription_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_user_subscribed(user_id):
            msg = "⚠️ Ваша подписка не активна.\nПожалуйста, оформите подписку в главном меню."
            if update.message:
                await update.message.reply_text(msg)
            elif update.callback_query:
                await update.callback_query.message.reply_text(msg)
            return
        return await func(update, context)
    return wrapper

# --- Команды ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username or "Пользователь"
    db_gen = get_db()
    db = next(db_gen)
    owner = db.query(Owner).filter(Owner.tg_id == user_id).first()
    if not owner:
        new_owner = Owner(tg_id=user_id)
        db.add(new_owner)
        db.commit()
        db.refresh(new_owner)
        db.close()
        welcome_msg = f"Привет, {username}! Добро пожаловать."
    else:
        db.close()
        is_sub = owner.is_subscribed() if owner else False
        if is_sub:
            welcome_msg = f"Привет, {username}! Ваша подписка активна до {owner.subscription_end.strftime('%d.%m.%Y %H:%M') if owner.subscription_end else 'N/A'}."
        else:
             welcome_msg = f"Привет, {username}! Ваша подписка не активна."

    await update.message.reply_text(welcome_msg)
    await show_main_menu(update, context) # Показываем меню после приветствия

# --- Показ главного меню (Reply Keyboard) ---
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Создаем Reply Keyboard
    keyboard = [
        [KeyboardButton("💳 Подписка"), KeyboardButton("🎮 Мои аккаунты FunPay")],
        # [KeyboardButton("💰 Баланс"), KeyboardButton("📊 Статистика")], # Можно добавить
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    menu_text = "Выберите действие из меню ниже:"
    
    if update.message:
        await update.message.reply_text(menu_text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.reply_text(menu_text, reply_markup=reply_markup)
        # Или редактируем сообщение, если нужно:
        # await update.callback_query.message.edit_text(menu_text, reply_markup=reply_markup)
    
    context.user_data['current_menu'] = 'main'

# --- Показ меню подписки ---
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    db_gen = get_db()
    db = next(db_gen)
    owner = db.query(Owner).filter(Owner.tg_id == user_id).first()
    db.close()
    
    balance_text = f"{owner.balance:.2f}" if owner else "0.00"
    
    # Reply Keyboard для подписки
    keyboard = [
        [KeyboardButton("1 неделя - 50.00 руб."), KeyboardButton("1 месяц - 150.00 руб.")],
        [KeyboardButton("3 месяца - 400.00 руб.")],
        [KeyboardButton("💰 Пополнить баланс")],
        [KeyboardButton("🔙 Назад")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    msg_text = f"💳 *Выберите тариф подписки:*\n\nВаш баланс: *{balance_text} руб.*"
    
    if update.message:
        await update.message.reply_text(msg_text, parse_mode='Markdown', reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    context.user_data['current_menu'] = 'subscribe'

# --- Показ меню FunPay аккаунтов ---
async def show_funpay_accounts_menu(query_or_update, context):
    user_id = query_or_update.from_user.id if hasattr(query_or_update, 'from_user') else query_or_update.effective_user.id
    
    db_gen = get_db()
    db = next(db_gen)
    owner = db.query(Owner).filter(Owner.tg_id == user_id).first()
    
    # --- Получение общей статистики ---
    total_steam_accounts = 0
    total_rented_now = 0
    if owner:
        total_steam_accounts = db.query(Account).join(FunPayAccount).filter(
            FunPayAccount.owner_id == owner.id
        ).count()
        total_rented_now = db.query(Account).join(FunPayAccount).filter(
            FunPayAccount.owner_id == owner.id,
            Account.status == 'rented'
        ).count()
    stats_text = (
        f"📊 *Общая статистика:*\n"
        f"  • Всего аккаунтов Steam: {total_steam_accounts}\n"
        f"  • Арендовано сейчас: {total_rented_now}\n\n"
    )
    # -----------------------------
    
    # Reply Keyboard для списка FunPay аккаунтов
    keyboard = []
    # Добавляем кнопку общей статистики
    keyboard.append([KeyboardButton("📊 Общая статистика")])
    
    if owner and owner.funpay_accounts:
        for fp_acc in owner.funpay_accounts:
            if fp_acc.is_active:
                keyboard.append([KeyboardButton(f"🎮 {fp_acc.name}")])
    
    keyboard.append([KeyboardButton("➕ Добавить аккаунт FunPay")])
    keyboard.append([KeyboardButton("🔙 Назад")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    full_text = stats_text + "Выберите аккаунт FunPay для управления:"
    
    if hasattr(query_or_update, 'message') and query_or_update.message:
        await query_or_update.message.reply_text(full_text, reply_markup=reply_markup, parse_mode='Markdown')
    elif hasattr(query_or_update, 'edit_message_text'):
        await query_or_update.edit_message_text(full_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    context.user_data['current_menu'] = 'funpay_list'
    db.close()

# --- Обработчик текстовых сообщений (для Reply Keyboard) ---
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает нажатия на кнопки Reply Keyboard."""
    text = update.message.text.strip()
    user_id = update.effective_user.id
    current_menu = context.user_data.get('current_menu', 'main')

    # Проверяем, ожидаем ли мы ввод для какого-либо процесса
    if context.user_data.get('adding_funpay_step'):
        await process_add_funpay_step(update, context)
        return
    elif context.user_data.get('adding_steam_step'):
        await process_add_steam_step(update, context)
        return
    elif context.user_data.get('awaiting_topup_amount'):
        await topup_amount_handler(update, context)
        return

    # --- Обработка главного меню ---
    if current_menu == 'main':
        if text == "💳 Подписка":
            await subscribe(update, context)
            return
        elif text == "🎮 Мои аккаунты FunPay":
            await show_funpay_accounts_menu(update, context)
            return
        # elif text == "💰 Баланс":
        #     await balance(update, context)
        #     return
        # elif text == "📊 Статистика":
        #     await stats(update, context)
        #     return

    # --- Обработка меню подписки ---
    elif current_menu == 'subscribe':
        if text in ["1 неделя - 50.00 руб.", "1 месяц - 150.00 руб.", "3 месяца - 400.00 руб."]:
            plan_map = {
                "1 неделя - 50.00 руб.": "1w",
                "1 месяц - 150.00 руб.": "1m",
                "3 месяца - 400.00 руб.": "3m"
            }
            plan_id = plan_map.get(text)
            if plan_id:
                # Вызываем обработчик покупки подписки
                class FakeQuery:
                    def __init__(self, update):
                        self.from_user = update.effective_user
                        self.message = update.message
                    
                    async def edit_message_text(self, text):
                        await self.message.reply_text(text)
                
                fake_query = FakeQuery(update)
                await handle_subscription_purchase(fake_query, user_id, plan_id)
            return
        elif text == "💰 Пополнить баланс":
            class FakeQuery:
                def __init__(self, update):
                    self.from_user = update.effective_user
                    self.message = update.message
                
                async def edit_message_text(self, text):
                    await self.message.reply_text(text)
            
            fake_query = FakeQuery(update)
            await handle_topup_request(fake_query, user_id)
            return
        elif text == "🔙 Назад":
            await show_main_menu(update, context)
            return

    # --- Обработка меню FunPay аккаунтов ---
    elif current_menu == 'funpay_list':
        if text == "📊 Общая статистика":
            class FakeQuery:
                def __init__(self, update):
                    self.from_user = update.effective_user
                    self.message = update.message
                
                async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
                    await self.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            
            fake_query = FakeQuery(update)
            await show_overall_funpay_stats(fake_query, context)
            return
        elif text == "➕ Добавить аккаунт FunPay":
            class FakeQuery:
                def __init__(self, update):
                    self.from_user = update.effective_user
                    self.message = update.message
                
                async def edit_message_text(self, text):
                    await self.message.reply_text(text)
            
            fake_query = FakeQuery(update)
            await start_add_funpay_account(fake_query, context)
            return
        elif text == "🔙 Назад":
            await show_main_menu(update, context)
            return
        elif text.startswith("🎮 "):
            # Предполагаем, что текст кнопки это "🎮 <имя аккаунта>"
            fp_account_name = text[3:] # Убираем "🎮 "
            db_gen = get_db()
            db = next(db_gen)
            owner = db.query(Owner).filter(Owner.tg_id == user_id).first()
            if owner:
                # Ищем аккаунт среди всех аккаунтов владельца
                fp_account = None
                for account in owner.funpay_accounts:
                    if account.name == fp_account_name and account.is_active:
                        fp_account = account
                        break
                
                if fp_account:
                    class FakeQuery:
                        def __init__(self, update):
                            self.from_user = update.effective_user
                            self.message = update.message
                        
                        async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
                            await self.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                    
                    fake_query = FakeQuery(update)
                    await show_funpay_account_details(fake_query, context, fp_account.id)
                else:
                    # Для отладки покажем все доступные аккаунты
                    available_accounts = [f"{acc.name} (ID: {acc.id})" for acc in owner.funpay_accounts if acc.is_active]
                    debug_msg = f"❌ Аккаунт FunPay '{fp_account_name}' не найден.\nДоступные аккаунты: {', '.join(available_accounts) if available_accounts else 'нет'}"
                    await update.message.reply_text(debug_msg)
                db.close()
            else:
                db.close()
                await update.message.reply_text("❌ Ошибка: владелец не найден.")
            return

    # --- Обработка деталей конкретного FunPay аккаунта ---
    elif current_menu.startswith('funpay_detail_'):
        funpay_account_id = int(current_menu.split('_')[-1])
        if text == "➕ Добавить аккаунт Steam":
            class FakeQuery:
                def __init__(self, update):
                    self.from_user = update.effective_user
                    self.message = update.message
                
                async def edit_message_text(self, text):
                    await self.message.reply_text(text)
            
            fake_query = FakeQuery(update)
            await start_add_steam_account(fake_query, context, funpay_account_id)
            return
        elif text == "📊 Статистика":
            class FakeQuery:
                def __init__(self, update):
                    self.from_user = update.effective_user
                    self.message = update.message
                
                async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
                    await self.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            
            fake_query = FakeQuery(update)
            await show_specific_funpay_stats(fake_query, context, funpay_account_id)
            return
        elif text == "⚙️ Настройки":
            await update.message.reply_text("⚙️ Настройки (пока не реализованы)")
            return
        elif text == "🔙 Назад":
            class FakeQuery:
                def __init__(self, update):
                    self.from_user = update.effective_user
                    self.message = update.message
                
                async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
                    await self.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            
            fake_query = FakeQuery(update)
            await show_funpay_accounts_menu(fake_query, context)
            return
        elif text.startswith("✅ ") or text.startswith("🎮 ") or text.startswith("🔒 "):
            # Предполагаем, что это кнопка аккаунта Steam
            # Текст кнопки: "<статус_иконка> <логин>"
            steam_account_login = text.split(' ', 1)[1]
            db_gen = get_db()
            db = next(db_gen)
            steam_account = db.query(Account).filter(Account.login == steam_account_login).first()
            if steam_account:
                # Показываем детали аккаунта Steam
                await update.message.reply_text(f"Детали аккаунта Steam {steam_account.login} (пока не реализовано)")
            else:
                await update.message.reply_text("❌ Аккаунт Steam не найден.")
            db.close()
            return

    # Если ни одна команда не подошла, считаем это обычным текстовым сообщением
    await update.message.reply_text("Извините, я не понимаю эту команду. Используйте меню.")

# --- Обработчики для покупки подписки ---
async def handle_subscription_purchase(query, user_id: int, plan_id: str):
    plan_data = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan_data:
        await query.edit_message_text(text="❌ Ошибка: Неверный тариф.")
        return
    db_gen = get_db()
    db = next(db_gen)
    owner = db.query(Owner).filter(Owner.tg_id == user_id).first()
    if not owner or owner.balance < plan_data['price']:
        db.close()
        msg = "❌ Недостаточно средств." if owner else "❌ Ошибка: владелец не найден."
        if not owner:
             msg += "\nПожалуйста, начните с команды /start."
        await query.edit_message_text(text=msg)
        return
    owner.balance -= plan_data['price']
    new_end = add_subscription_days(owner, plan_data['duration_days'])
    db.commit()
    db.close()
    success_msg = (
        f"✅ Подписка успешно оформлена!\n"
        f"Тариф: {plan_data['duration_days']} дней\n"
        f"Действует до: {new_end.strftime('%d.%m.%Y %H:%M')}\n"
        f"Остаток на балансе: {owner.balance:.2f} руб."
    )
    await query.edit_message_text(text=success_msg)

# --- Обработчики для пополнения баланса ---
async def handle_topup_request(query, user_id: int):
    if not (YOOKASSA_ENABLED and YOOKASSA_SDK_AVAILABLE):
        # Проверяем, есть ли метод edit_message_text
        if hasattr(query, 'edit_message_text') and callable(query.edit_message_text):
            await query.edit_message_text(text="❌ Пополнение баланса временно недоступно.")
        elif hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
            await query.message.reply_text(text="❌ Пополнение баланса временно недоступно.")
        else:
            # Fallback для fake query объектов - проверяем, есть ли edit_message_text как атрибут
            if hasattr(query, 'edit_message_text'):
                # Это функция, вызываем её
                if callable(query.edit_message_text):
                    await query.edit_message_text("❌ Пополнение баланса временно недоступно.")
                else:
                    # Это атрибут, используем message.reply_text
                    if hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
                        await query.message.reply_text("❌ Пополнение баланса временно недоступно.")
            else:
                # Просто отправляем сообщение
                if hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
                    await query.message.reply_text("❌ Пополнение баланса временно недоступно.")
        return
    
    # Проверяем, есть ли метод edit_message_text
    if hasattr(query, 'edit_message_text') and callable(query.edit_message_text):
        await query.edit_message_text(text=f"Введите сумму пополнения (минимум {MIN_TOPUP_AMOUNT} руб.):")
    elif hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
        await query.message.reply_text(text=f"Введите сумму пополнения (минимум {MIN_TOPUP_AMOUNT} руб.):")
    else:
        # Fallback для fake query объектов
        if hasattr(query, 'edit_message_text'):
            # Это функция, вызываем её
            if callable(query.edit_message_text):
                await query.edit_message_text(f"Введите сумму пополнения (минимум {MIN_TOPUP_AMOUNT} руб.):")
            else:
                # Это атрибут, используем message.reply_text
                if hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
                    await query.message.reply_text(f"Введите сумму пополнения (минимум {MIN_TOPUP_AMOUNT} руб.):")
        else:
            # Просто отправляем сообщение
            if hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
                await query.message.reply_text(f"Введите сумму пополнения (минимум {MIN_TOPUP_AMOUNT} руб.):")
    
    # Устанавливаем флаг в user_data
    # Для настоящих query объектов
    if hasattr(query, 'message') and hasattr(query.message, 'from_user'):
        query.message._user_id = user_id
        if not hasattr(query.message, '_application'):
            # Создаем фейковый application для хранения user_data
            class FakeApplication:
                def __init__(self):
                    self.user_data = {}
            query.message._application = FakeApplication()
        if user_id not in query.message._application.user_data:
            query.message._application.user_data[user_id] = {}
        query.message._application.user_data[user_id]['awaiting_topup_amount'] = True
    # Для fake query объектов
    elif hasattr(query, 'message') and hasattr(query, 'from_user'):
        # Устанавливаем флаг в контексте напрямую
        if hasattr(query, '_user_data_storage'):
            query._user_data_storage[user_id] = query._user_data_storage.get(user_id, {})
            query._user_data_storage[user_id]['awaiting_topup_amount'] = True

async def topup_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Проверяем флаг несколькими способами
    awaiting_topup = False
    
    # Способ 1: через context.user_data (стандартный способ)
    if context.user_data.pop('awaiting_topup_amount', False):
        awaiting_topup = True
    # Способ 2: через application.user_data (для fake query)
    elif hasattr(update.message, '_application') and hasattr(update.message._application, 'user_data'):
        user_id = update.effective_user.id
        if user_id in update.message._application.user_data:
            awaiting_topup = update.message._application.user_data[user_id].pop('awaiting_topup_amount', False)
    # Способ 3: через message attributes (для fake query)
    elif hasattr(update.message, '_user_data_storage'):
        user_id = update.effective_user.id
        if user_id in update.message._user_data_storage:
            awaiting_topup = update.message._user_data_storage[user_id].pop('awaiting_topup_amount', False)
    
    if awaiting_topup:
        user_id = update.effective_user.id
        try:
            amount = float(update.message.text)
            if amount < MIN_TOPUP_AMOUNT:
                await update.message.reply_text(f"❌ Минимальная сумма {MIN_TOPUP_AMOUNT} руб.")
                return
            amount = round(amount, 2)
            payment_id = str(uuid.uuid4())
            try:
                payment = Payment.create({
                    "amount": { "value": f"{amount:.2f}", "currency": "RUB" },
                    "confirmation": { "type": "redirect", "return_url": f"https://t.me/{context.bot.username}" },
                    "capture": True,
                    "description": f"Пополнение баланса в боте '@{context.bot.username}'",
                    "metadata": { "tg_user_id": str(user_id), "internal_payment_id": payment_id },
                })
                payment_link = payment.confirmation.confirmation_url
                if payment_link:
                    keyboard = [[InlineKeyboardButton("Оплатить", url=payment_link)]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(
                        f"💳 Сумма к оплате: {amount} руб.\n"
                        f"Нажмите кнопку ниже для перехода к оплате.\n\n"
                        f"После оплаты баланс будет пополнен автоматически.",
                        reply_markup=reply_markup
                    )
                    logging.info(f"[TOPUP] Создан платеж для {user_id} на {amount} руб. Payment ID: {payment.id}")
                else:
                    raise Exception("Payment link is None")
            except Exception as e:
                logging.error(f"[TOPUP] Ошибка при создании платежа для {user_id}: {e}")
                await update.message.reply_text("❌ Ошибка при создании платежа. Попробуйте позже.")
        except ValueError:
            await update.message.reply_text("❌ Пожалуйста, введите корректное число.")

# --- Обработчики для FunPay аккаунтов ---
async def show_overall_funpay_stats(query, context):
    user_id = query.from_user.id
    db_gen = get_db()
    db = next(db_gen)
    owner = db.query(Owner).filter(Owner.tg_id == user_id).first()
    if not owner:
        # await query.answer("Ошибка!", show_alert=True)
        if hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
            await query.message.reply_text("❌ Ошибка: владелец не найден.")
        db.close()
        return
    from sqlalchemy import func
    status_counts = db.query(Account.status, func.count(Account.id)).join(FunPayAccount).filter(FunPayAccount.owner_id == owner.id).group_by(Account.status).all()
    status_text = "\n".join([f"  • {status}: {count}" for status, count in status_counts]) or "  • Нет аккаунтов"
    stats_message = f"📈 *Подробная статистика:*\n\n*Аккаунты Steam:*\n{status_text}\n"
    # Reply Keyboard для возврата
    keyboard = [[KeyboardButton("🔙 Назад")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    # Проверяем, можно ли редактировать сообщение
    if hasattr(query, 'message') and hasattr(query.message, 'edit_text'):
        try:
            await query.message.edit_text(stats_message, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception:
            # Если не удалось отредактировать, отправляем новое сообщение
            await query.message.reply_text(stats_message, reply_markup=reply_markup, parse_mode='Markdown')
    elif hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
        await query.message.reply_text(stats_message, reply_markup=reply_markup, parse_mode='Markdown')
    context.user_data['current_menu'] = 'funpay_overall_stats'
    db.close()

# --- Добавление FunPay ---
async def start_add_funpay_account(query, context):
    # Проверяем, можно ли редактировать сообщение
    if hasattr(query, 'message') and hasattr(query.message, 'edit_text'):
        try:
            await query.message.edit_text("Введите название для нового аккаунта FunPay (например, Основной):")
        except Exception:
            # Если не удалось отредактировать, отправляем новое сообщение
            await query.message.reply_text("Введите название для нового аккаунта FunPay (например, Основной):")
    elif hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
        await query.message.reply_text("Введите название для нового аккаунта FunPay (например, Основной):")
    context.user_data['adding_funpay_step'] = 'name'
    context.user_data['new_funpay_data'] = {}

async def process_add_funpay_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('adding_funpay_step'):
        return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    step = context.user_data.get('adding_funpay_step')
    if step == 'name':
        if not text:
            await update.message.reply_text("Название не может быть пустым.")
            return
        context.user_data['new_funpay_data']['name'] = text
        await update.message.reply_text("Введите ваш *FunPay User ID*:", parse_mode='Markdown')
        context.user_data['adding_funpay_step'] = 'user_id'
    elif step == 'user_id':
        if not text.isdigit():
            await update.message.reply_text("❌ User ID должен быть числом.")
            return
        context.user_data['new_funpay_data']['user_id'] = text
        await update.message.reply_text("Введите ваш *FunPay Golden Key*:", parse_mode='Markdown')
        context.user_data['adding_funpay_step'] = 'golden_key'
    elif step == 'golden_key':
        golden_key = text
        db_gen = get_db()
        db = next(db_gen)
        owner = db.query(Owner).filter(Owner.tg_id == user_id).first()
        if not owner:
             await update.message.reply_text("Ошибка: владелец не найден.")
             db.close()
             return
        try:
            name = context.user_data['new_funpay_data']['name']
            user_id_fp = context.user_data['new_funpay_data']['user_id']
            encrypted_user_id = encrypt_data(user_id_fp)
            encrypted_golden_key = encrypt_data(golden_key)
            new_fp_account = FunPayAccount(
                owner_id=owner.id, name=name,
                user_id_encrypted=encrypted_user_id,
                golden_key_encrypted=encrypted_golden_key,
                is_active=True
            )
            db.add(new_fp_account)
            db.commit()
            db.close()
            await update.message.reply_text("✅ Аккаунт FunPay успешно добавлен!")
            context.user_data.clear()
            # Отправляем обновленное меню
            fake_update = type('', (), {})()
            fake_update.effective_user = update.effective_user
            fake_update.message = update.message
            await show_funpay_accounts_menu(fake_update, context)
        except Exception as e:
            db.rollback()
            db.close()
            logging.error(f"Ошибка при сохранении FunPay creds для {user_id}: {e}")
            await update.message.reply_text("❌ Ошибка при сохранении данных.")
        finally:
            context.user_data.pop('adding_funpay_step', None)
            context.user_data.pop('new_funpay_data', None)

# --- Просмотр конкретного FunPay аккаунта ---
async def show_funpay_account_details(query, context, funpay_account_id: int):
    user_id = query.from_user.id
    db_gen = get_db()
    db = next(db_gen)
    fp_account = db.query(FunPayAccount).join(Owner).filter(FunPayAccount.id == funpay_account_id, Owner.tg_id == user_id).first()
    if not fp_account:
        # await query.answer("Аккаунт не найден!", show_alert=True)
        if hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
            await query.message.reply_text("❌ Аккаунт не найден!")
        db.close()
        return
    steam_accounts = fp_account.steam_accounts
    total_steam_for_fp = len(steam_accounts)
    rented_for_fp = len([a for a in steam_accounts if a.status == 'rented'])
    text = f"Управление аккаунтом FunPay: *{fp_account.name}*\nСтатус: {'✅ Активен' if fp_account.is_active else '❌ Неактивен'}\n\n"
    text += f"📊 *Статистика этого аккаунта:*\n  • Всего Steam аккаунтов: {total_steam_for_fp}\n  • Арендовано сейчас: {rented_for_fp}\n\n"
    text += "*Аккаунты Steam:*\n"
    
    # Reply Keyboard для управления аккаунтом
    keyboard = []
    for steam_acc in steam_accounts:
        status_icon = {'available': '✅', 'rented': '🎮', 'blocked': '🔒'}.get(steam_acc.status, '❓')
        keyboard.append([KeyboardButton(f"{status_icon} {steam_acc.login}")])
    
    keyboard.append([KeyboardButton("➕ Добавить аккаунт Steam")])
    keyboard.append([KeyboardButton("📊 Статистика")])
    keyboard.append([KeyboardButton("⚙️ Настройки")])
    keyboard.append([KeyboardButton("🔙 Назад")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    # Проверяем, можно ли редактировать сообщение
    if hasattr(query, 'message') and hasattr(query.message, 'edit_text'):
        try:
            await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception:
            # Если не удалось отредактировать, отправляем новое сообщение
            await query.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    elif hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    context.user_data['current_menu'] = f'funpay_detail_{fp_account.id}'
    db.close()

async def show_specific_funpay_stats(query, context, funpay_account_id: int):
    user_id = query.from_user.id
    db_gen = get_db()
    db = next(db_gen)
    fp_account = db.query(FunPayAccount).join(Owner).filter(FunPayAccount.id == funpay_account_id, Owner.tg_id == user_id).first()
    if not fp_account:
        # await query.answer("Аккаунт не найден!", show_alert=True)
        if hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
            await query.message.reply_text("❌ Аккаунт не найден!")
        db.close()
        return
    from sqlalchemy import func
    steam_account_ids = [sa.id for sa in fp_account.steam_accounts]
    status_counts = db.query(Account.status, func.count(Account.id)).filter(Account.id.in_(steam_account_ids)).group_by(Account.status).all()
    status_text = "\n".join([f"  • {status}: {count}" for status, count in status_counts]) or "  • Нет аккаунтов"
    stats_message = f"📈 *Статистика аккаунта FunPay '{fp_account.name}':*\n\n*Аккаунты Steam:*\n{status_text}\n"
    
    # Reply Keyboard для возврата
    keyboard = [[KeyboardButton("🔙 Назад")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    # Проверяем, можно ли редактировать сообщение
    if hasattr(query, 'message') and hasattr(query.message, 'edit_text'):
        try:
            await query.message.edit_text(stats_message, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception:
            # Если не удалось отредактировать, отправляем новое сообщение
            await query.message.reply_text(stats_message, reply_markup=reply_markup, parse_mode='Markdown')
    elif hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
        await query.message.reply_text(stats_message, reply_markup=reply_markup, parse_mode='Markdown')
    context.user_data['current_menu'] = f'funpay_stats_{funpay_account_id}'
    db.close()

# --- Добавление Steam аккаунта ---
async def start_add_steam_account(query, context, funpay_account_id: int):
    context.user_data['adding_steam_step'] = 'login'
    context.user_data['steam_funpay_account_id'] = funpay_account_id
    # Проверяем, можно ли редактировать сообщение
    if hasattr(query, 'message') and hasattr(query.message, 'edit_text'):
        try:
            await query.message.edit_text("Введите логин аккаунта Steam:")
        except Exception:
            # Если не удалось отредактировать, отправляем новое сообщение
            await query.message.reply_text("Введите логин аккаунта Steam:")
    elif hasattr(query, 'message') and hasattr(query.message, 'reply_text'):
        await query.message.reply_text("Введите логин аккаунта Steam:")

async def process_add_steam_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('adding_steam_step'):
        return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    step = context.user_data.get('adding_steam_step')
    if step == 'login':
        context.user_data['new_steam_data'] = {'login': text}
        await update.message.reply_text("Введите пароль аккаунта Steam:")
        context.user_data['adding_steam_step'] = 'password'
    elif step == 'password':
        context.user_data['new_steam_data']['password'] = text
        await update.message.reply_text("Введите `shared_secret` (base64) из maFile:")
        context.user_data['adding_steam_step'] = 'shared_secret'
    elif step == 'shared_secret':
        context.user_data['new_steam_data']['shared_secret'] = text
        await update.message.reply_text("Введите цену аренды за час (руб.):")
        context.user_data['adding_steam_step'] = 'price'
    elif step == 'price':
        try:
            price = float(text)
            db_gen = get_db()
            db = next(db_gen)
            funpay_account_id = context.user_data['steam_funpay_account_id']
            fp_account = db.query(FunPayAccount).join(Owner).filter(FunPayAccount.id == funpay_account_id, Owner.tg_id == user_id).first()
            if not fp_account:
                 await update.message.reply_text("Ошибка: аккаунт FunPay не найден.")
                 db.close()
                 return
            login = context.user_data['new_steam_data']['login']
            if db.query(Account).filter(Account.login == login).first():
                await update.message.reply_text(f"Аккаунт Steam с логином {login} уже существует.")
                db.close()
                return
            encrypted_password = encrypt_data(context.user_data['new_steam_data']['password'])
            encrypted_shared_secret = encrypt_data(context.user_data['new_steam_data']['shared_secret'])
            new_steam_account = Account(
                owner_id=fp_account.owner_id,
                funpay_account_id=fp_account.id,
                login=login,
                base_password_encrypted=encrypted_password,
                shared_secret_encrypted=encrypted_shared_secret,
                price_per_hour=price,
                status='available'
            )
            db.add(new_steam_account)
            db.commit()
            db.close()
            await update.message.reply_text("✅ Аккаунт Steam успешно добавлен!")
            context.user_data.clear()
            # Отправляем обновленное меню
            fake_update = type('', (), {})()
            fake_update.effective_user = update.effective_user
            fake_update.message = update.message
            await show_funpay_accounts_menu(fake_update, context)
        except ValueError:
            await update.message.reply_text("Ошибка: Цена должна быть числом.")
        except Exception as e:
            logging.error(f"Ошибка при добавлении Steam аккаунта для {user_id}: {e}")
            await update.message.reply_text("❌ Ошибка при сохранении данных.")
        finally:
            context.user_data.pop('adding_steam_step', None)
            context.user_data.pop('steam_funpay_account_id', None)
            context.user_data.pop('new_steam_data', None)

# --- Админские команды ---
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Замените на свои ID админов
    if update.effective_user.id not in [7003032714]:
        await update.message.reply_text("❌ У вас нет прав.")
        return
    db_gen = get_db()
    db = next(db_gen)
    total_owners = db.query(Owner).count()
    total_accounts = db.query(Account).count()
    rented_accounts = db.query(Account).filter(Account.status == 'rented').count()
    db.close()
    stats_message = (
        f"📊 *Статистика бота:*\n"
        f"- Всего владельцев: {total_owners}\n"
        f"- Всего аккаунтов: {total_accounts}\n"
        f"- Арендовано сейчас: {rented_accounts}\n"
    )
    await update.message.reply_text(stats_message, parse_mode='Markdown')

async def admin_activate_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
     # Замените на свои ID админов
    if update.effective_user.id not in [7003032714]:
        await update.message.reply_text("❌ У вас нет прав.")
        return
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("Использование: /admin_activate_subscription <TG_ID>")
        return
    try:
        target_tg_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ TG ID должен быть числом.")
        return
    db_gen = get_db()
    db = next(db_gen)
    try:
        owner = db.query(Owner).filter(Owner.tg_id == target_tg_id).first()
        if not owner:
            owner = Owner(tg_id=target_tg_id)
            db.add(owner)
            db.flush()
        current_end = owner.subscription_end or datetime.utcnow()
        new_end = current_end + timedelta(days=30) # По умолчанию 30 дней
        owner.subscription_end = new_end
        db.commit()
        db.close()
        success_msg = f"✅ Подписка для {target_tg_id} активирована до {new_end.strftime('%d.%m.%Y %H:%M')}."
        logging.info(f"[ADMIN] {success_msg}")
        await update.message.reply_text(success_msg)
        try:
            bot_instance = context.bot
            if bot_instance:
                await bot_instance.send_message(chat_id=target_tg_id, text=f"✅ Администратор активировал вашу подписку до {new_end.strftime('%d.%m.%Y %H:%M')}!")
        except Exception as e:
            logging.error(f"[ADMIN] Не удалось уведомить владельца {target_tg_id}: {e}")
    except Exception as e:
        db.rollback()
        db.close()
        logging.error(f"[ADMIN] Ошибка активации подписки для {target_tg_id}: {e}")
        await update.message.reply_text("❌ Произошла ошибка.")

# --- Обработчик кнопок (для совместимости с InlineKeyboard) ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_main":
        await show_main_menu(update, context)
        return
    elif data == "menu_subscribe":
        await subscribe(update, context)
        return
    elif data == "menu_funpay_accounts":
        await show_funpay_accounts_menu(query, context)
        return
    elif data.startswith("sub_"):
        plan_id = data.split("_", 1)[1]
        await handle_subscription_purchase(query, query.from_user.id, plan_id)
        return
    elif data == "topup":
        await handle_topup_request(query, query.from_user.id)
        return
    elif data == "funpay_overall_stats":
        await show_overall_funpay_stats(query, context)
        return
    elif data == "funpay_add":
        await start_add_funpay_account(query, context)
        return
    elif data.startswith("funpay_view_"):
        funpay_account_id = int(data.split("_")[-1])
        await show_funpay_account_details(query, context, funpay_account_id)
        return
    elif data.startswith("funpay_stats_"):
        funpay_account_id = int(data.split("_")[-1])
        await show_specific_funpay_stats(query, context, funpay_account_id)
        return
    elif data.startswith("funpay_steam_add_"):
        funpay_account_id = int(data.split("_")[-1])
        await start_add_steam_account(query, context, funpay_account_id)
        return
    elif data == "funpay_back_to_list":
        await show_funpay_accounts_menu(query, context)
        return
    # Добавьте обработку других кнопок по необходимости

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Извините, я не понимаю эту команду.")
