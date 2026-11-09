import os
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Запуск бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Добро пожаловать в WEZING RUSSIA!\n\n"
        "Для начала тестирования отправьте фотографию "
        "или скриншот, подтверждающий ваше назначение на форуме.\n\n"
        "📸 Отправьте фото следующим сообщением."
    )


# Получение фотографии игрока
async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]

    if not ADMIN_ID:
        await update.message.reply_text(
            "⚠️ Система ещё настраивается. Попробуйте позже."
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
            )
        ]
    ])

    username = f"@{user.username}" if user.username else "Не указан"

    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo.file_id,
        caption=(
            "📩 НОВАЯ ЗАЯВКА WEZING RUSSIA\n\n"
            f"👤 Имя: {user.full_name}\n"
            f"🔗 Username: {username}\n"
            f"🆔 Telegram ID: {user.id}\n\n"
            "Проверьте фотографию и примите решение."
        ),
        reply_markup=keyboard
    )

    await update.message.reply_text(
        "✅ Фотография отправлена администрации!\n\n"
        "⏳ Ожидайте проверки вашей заявки."
    )


# Обработка решения администратора
async def decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ У вас нет доступа!", show_alert=True)
        return

    action, player_id = query.data.split(":")
    player_id = int(player_id)

    if action == "approve":
        message = (
            "🎉 Поздравляем!\n\n"
            "Ваша заявка WEZING RUSSIA одобрена!\n"
            "Вы успешно прошли проверку.\n\n"
            "❤️ Ожидайте дальнейших указаний администрации."
        )
        status = "✅ ЗАЯВКА ОДОБРЕНА"

    else:
        message = (
            "❌ К сожалению, ваша заявка WEZING RUSSIA отклонена.\n\n"
            "По вопросам обратитесь к администрации проекта."
        )
        status = "❌ ЗАЯВКА ОТКЛОНЕНА"

    try:
        await context.bot.send_message(
            chat_id=player_id,
            text=message
        )

        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n{status}",
            reply_markup=None
        )

    except Exception:
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n{status}\n⚠️ Не удалось уведомить игрока.",
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

    print("WEZING RUSSIA TEST SYSTEM запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
