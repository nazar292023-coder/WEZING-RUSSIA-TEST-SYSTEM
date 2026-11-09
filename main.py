import os
import asyncio
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
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

web = Flask(__name__)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


@web.route("/")
def home():
    return "WEZING RUSSIA TEST SYSTEM: OK"


def run_web():
    port = int(os.environ.get("PORT", 10000))
    web.run(host="0.0.0.0", port=port)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Добро пожаловать в WEZING RUSSIA!\n\n"
        "📋 Здесь проходит тестирование кандидатов "
        "на должности проекта.\n\n"
        "📸 Для начала отправьте фотографию или скриншот "
        "подтверждения вашего назначения на форуме.\n\n"
        "После проверки ожидайте дальнейших инструкций."
    )


async def receive_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    if not ADMIN_ID:
        await update.message.reply_text(
            "⚠️ Система временно настраивается."
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Одобрить",
                callback_data=f"approve:{user.id}"
            ),
            InlineKeyboardButton(
                "❌ Отказать",
                callback_data=f"reject:{user.id}"
            ),
        ]
    ])

    username = (
        f"@{user.username}"
        if user.username
        else "Не указан"
    )

    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=update.message.photo[-1].file_id,
            caption=(
                "📩 НОВАЯ ЗАЯВКА WEZING RUSSIA\n\n"
                f"👤 Имя: {user.full_name}\n"
                f"🔗 Username: {username}\n"
                f"🆔 Telegram ID: {user.id}\n\n"
                "Проверьте подтверждение кандидата."
            ),
            reply_markup=keyboard,
        )

        await update.message.reply_text(
            "✅ Ваша фотография отправлена администрации!\n\n"
            "⏳ Ожидайте проверки."
        )

    except Exception:
        logger.exception("Ошибка отправки заявки")
        await update.message.reply_text(
            "⚠️ Не удалось отправить заявку. "
            "Попробуйте позже."
        )


async def decision(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer(
            "⛔ У вас нет доступа!",
            show_alert=True
        )
        return

    await query.answer()

    try:
        action, player_id = query.data.split(":")
        player_id = int(player_id)

        if action == "approve":
            message = (
                "🎉 Поздравляем!\n\n"
                "Ваша заявка WEZING RUSSIA одобрена!\n\n"
                "Ожидайте дальнейших инструкций администрации."
            )
            status = "✅ ОДОБРЕНО"

        elif action == "reject":
            message = (
                "❌ Ваша заявка WEZING RUSSIA отклонена.\n\n"
                "По вопросам обратитесь к администрации."
            )
            status = "❌ ОТКАЗ"

        else:
            return

        try:
            await context.bot.send_message(
                chat_id=player_id,
                text=message
            )
            notification = ""

        except Exception:
            notification = "\n⚠️ Уведомление игроку не отправлено."

        await query.edit_message_caption(
            caption=(
                f"{query.message.caption}\n\n"
                f"{status}{notification}"
            ),
            reply_markup=None
        )

    except Exception:
        logger.exception("Ошибка обработки решения")
        await query.message.reply_text(
            "Не удалось обработать решение."
        )


async def unknown_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "📸 Пожалуйста, отправьте фотографию "
        "или скриншот подтверждения с форума."
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN")

    if not ADMIN_ID:
        raise RuntimeError("Не задан ADMIN_ID")

    # Исправление запуска на Python 3.14
    asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, receive_photo))
    app.add_handler(CallbackQueryHandler(decision))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            unknown_message
        )
    )

    threading.Thread(
        target=run_web,
        daemon=True
    ).start()

    print("WEZING RUSSIA TEST SYSTEM запущен!")

    app.run_polling()


if __name__ == "__main__":
    main()
