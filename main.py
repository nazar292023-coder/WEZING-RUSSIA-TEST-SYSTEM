import os
import logging
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

web = Flask(__name__)

@web.route("/")
def home():
    return "WEZING RUSSIA TEST SYSTEM: OK"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web.run(host="0.0.0.0", port=port)

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Добро пожаловать в WEZING RUSSIA!\n\n"
        "📸 Отправьте фотографию или скриншот "
        "подтверждения назначения на форуме."
    )

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not ADMIN_ID:
        await update.message.reply_text("⚠️ Система настраивается.")
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Одобрить", callback_data=f"approve:{user.id}"),
        InlineKeyboardButton("❌ Отказать", callback_data=f"reject:{user.id}")
    ]])

    username = f"@{user.username}" if user.username else "Не указан"

    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=update.message.photo[-1].file_id,
        caption=(
            "📩 НОВАЯ ЗАЯВКА\n\n"
            f"👤 Имя: {user.full_name}\n"
            f"🔗 Username: {username}\n"
            f"🆔 ID: {user.id}"
        ),
        reply_markup=keyboard
    )

    await update.message.reply_text("✅ Заявка отправлена администрации. Ожидайте!")

async def decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Нет доступа!", show_alert=True)
        return

    await query.answer()

    action, player_id = query.data.split(":")
    player_id = int(player_id)

    if action == "approve":
        message = (
            "🎉 Поздравляем!\n\n"
            "Ваша заявка WEZING RUSSIA одобрена!"
        )
        status = "✅ ОДОБРЕНО"
    else:
        message = "❌ Ваша заявка отклонена."
        status = "❌ ОТКАЗ"

    try:
        await context.bot.send_message(player_id, message)
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n{status}",
            reply_markup=None
        )
    except Exception:
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n{status} (уведомление не отправлено)",
            reply_markup=None
        )

def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN")
    if not ADMIN_ID:
        raise RuntimeError("Не задан ADMIN_ID")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, receive_photo))
    app.add_handler(CallbackQueryHandler(decision))

    threading.Thread(target=run_web, daemon=True).start()

    print("WEZING RUSSIA TEST SYSTEM запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
