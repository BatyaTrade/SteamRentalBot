# bot/bot.py
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from bot.handlers import (
    start, show_main_menu, subscribe, button_handler, text_message_handler, process_add_funpay_step, process_add_steam_step,
    topup_amount_handler, admin_stats, admin_activate_subscription, unknown_command
)
from bot.config import TELEGRAM_BOT_TOKEN

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_INSTANCE = None

def get_bot_instance():
    global BOT_INSTANCE
    return BOT_INSTANCE

async def post_init(application) -> None:
    global BOT_INSTANCE
    BOT_INSTANCE = application.bot
    logging.info("Экземпляр Telegram бота сохранен.")

def run_bot():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN не установлен")

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_main_menu))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("admin_stats", admin_stats))
    application.add_handler(CommandHandler("admin_activate_subscription", admin_activate_subscription))

    # Обработчики
    application.add_handler(CallbackQueryHandler(button_handler)) # Для инлайн-кнопок (если остались)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler)) # <-- ДОБАВИЛИ
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_funpay_step))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_steam_step))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount_handler))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    application.run_polling(allowed_updates=Update.ALL_TYPES)
