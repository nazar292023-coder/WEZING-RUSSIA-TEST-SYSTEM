import os
import json
import time
import sqlite3
import logging
import threading
import asyncio
from datetime import datetime

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = "wezing_tests.db"
TEST_SECONDS = 5 * 60
QUESTION_COUNT = 20
PASS_SCORE = 13

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("wezing-test")

web = Flask(__name__)

@web.route("/")
def home():
    return "WEZING RUSSIA TEST SYSTEM: OK"

def run_web():
    web.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                proof_file_id TEXT,
                category TEXT,
                organization TEXT,
                score INTEGER,
                total INTEGER,
                status TEXT DEFAULT 'new',
                created_at TEXT
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                category TEXT,
                organization TEXT,
                score INTEGER,
                total INTEGER,
                result TEXT,
                created_at TEXT
            )
        """)

ORGANIZATIONS = {
    "fsb": ("ФСБ", "служба ФСБ", "проверка документов, задержания и служебная дисциплина"),
    "gibdd": ("ГИБДД", "сотрудник ГИБДД", "дорожный порядок, остановка транспорта и безопасность движения"),
    "umvd": ("УМВД", "сотрудник УМВД", "охрана порядка, обращения граждан и задержания"),
    "vch": ("ВЧ", "военнослужащий", "военная дисциплина, посты и выполнение приказов"),
    "cb": ("ЦБ", "сотрудник ЦБ", "банковская деятельность, обслуживание и сохранность средств"),
    "media": ("СМИ", "сотрудник СМИ", "эфиры, интервью, объявления и проверка информации"),
    "government": ("Правительство", "сотрудник Правительства", "государственные обязанности и работа с гражданами"),
    "law": ("Право", "представитель закона", "законы, разбирательства и правовые процедуры"),
    "arz": ("ОПГ ARZ", "участник ОПГ ARZ", "правила организации, взаимодействие и RP-ситуации"),
    "bat": ("ОПГ BAT", "участник ОПГ BAT", "правила организации, взаимодействие и RP-ситуации"),
    "lyt": ("ОПГ LYT", "участник ОПГ LYT", "правила организации, взаимодействие и RP-ситуации"),
}

# Базовые RP-вопросы. Для каждой организации формируется отдельный банк
# с её названием и тематикой. Точные внутренние правила проекта можно
# позднее заменить в этих наборах.
def build_bank(org_name, role_name, topic):
    templates = [
        ("Что должен сделать {role}, прежде чем начать служебное действие?",
         ["Убедиться, что есть IC-причина и соблюдены правила", "Начать без объяснений", "Игнорировать ситуацию", "Попросить игрока выйти из игры"], 0),
        ("Как правильно действовать, если гражданин задаёт вопрос по службе?",
         ["Спокойно ответить в рамках полномочий", "Оскорбить его", "Игнорировать всегда", "Сразу применить наказание"], 0),
        ("Что важнее всего при выполнении обязанностей: {topic}?",
         ["Соблюдение правил сервера и RP", "Личная выгода", "Споры в OOC", "Самовольное изменение правил"], 0),
        ("Что следует сделать при обнаружении нарушения?",
         ["Зафиксировать обстоятельства и действовать по регламенту", "Наказать без проверки", "Удалить доказательства", "Попросить друзей решить вопрос"], 0),
        ("Как нужно общаться с игроками во время RP-ситуации?",
         ["Корректно и без OOC-конфликтов", "Грубо и с угрозами", "Только капсом", "Не отвечать ни на что"], 0),
        ("Что означает соблюдение субординации?",
         ["Уважительное служебное взаимодействие по установленной иерархии", "Выполнение любых личных просьб", "Игнорирование руководства", "Самостоятельная выдача должностей"], 0),
        ("Что делать, если приказ руководителя противоречит правилам сервера?",
         ["Не нарушать правила и сообщить о проблеме ответственному лицу", "Выполнить любой ценой", "Скрыть ситуацию", "Потребовать награду"], 0),
        ("Как поступить, если вы не уверены в правильности процедуры?",
         ["Уточнить действующий регламент у руководства", "Придумать собственное правило", "Спросить случайного игрока и сразу действовать", "Игнорировать регламент"], 0),
        ("Можно ли использовать служебные возможности ради личной выгоды?",
         ["Нет, служебные полномочия используются только по назначению", "Да, если никто не видит", "Да, по просьбе друга", "Можно без ограничений"], 0),
        ("Что нужно сделать перед публикацией служебной информации?",
         ["Проверить достоверность и убедиться, что публикация разрешена", "Опубликовать слух", "Изменить факты", "Разослать личные данные"], 0),
        ("Как следует вести себя при конфликте с коллегой?",
         ["Сохранить спокойствие и обратиться к руководству по правилам", "Устроить публичную ссору", "Мстить через полномочия", "Распространять слухи"], 0),
        ("Что является хорошим доказательством нарушения?",
         ["Понятная запись или скриншот с контекстом", "Пересказ без деталей", "Слухи от знакомых", "Предположение"], 0),
        ("Можно ли нарушать правила RP ради быстрого завершения ситуации?",
         ["Нет, нужно соблюдать правила RP", "Да, если спешишь", "Да, если это выгодно", "Можно по просьбе друга"], 0),
        ("Что делать, если гражданин подал жалобу на ваши действия?",
         ["Не удалять материалы и дать спокойное объяснение по процедуре", "Угрожать заявителю", "Удалить переписку", "Игнорировать администрацию"], 0),
        ("Как правильно использовать служебный транспорт или имущество?",
         ["Только по служебной необходимости и установленным правилам", "Для любых личных дел", "Передавать кому угодно", "Использовать без ограничений"], 0),
        ("Что делать при ошибке во время исполнения обязанностей?",
         ["Признать ошибку и сообщить руководству", "Скрыть её любой ценой", "Обвинить другого без оснований", "Удалить доказательства"], 0),
        ("Как поступить, если другой игрок провоцирует вас на OOC-конфликт?",
         ["Не поддерживать конфликт и действовать по правилам", "Ответить оскорблениями", "Использовать полномочия для мести", "Продолжить спор в чате"], 0),
        ("Почему важно знать должностные обязанности {role}?",
         ["Чтобы действовать в пределах полномочий", "Чтобы получать преимущество вне правил", "Чтобы игнорировать руководство", "Чтобы менять правила самостоятельно"], 0),
        ("Что следует сделать перед важным служебным мероприятием?",
         ["Уточнить задачу, подготовиться и соблюдать регламент", "Начать без плана", "Не сообщать участникам", "Игнорировать безопасность"], 0),
        ("Какое поведение лучше всего показывает готовность к должности?",
         ["Ответственность, знание правил и уважительное общение", "Использование статуса для личных споров", "Отказ от обязанностей", "Нарушение дисциплины"], 0),
    ]
    result = []
    for i, (question, options, correct) in enumerate(templates, 1):
        result.append({
            "question": question.format(role=role_name, topic=topic),
            "options": options,
            "correct": correct
        })
    return result

ADMIN_BANK = [
    ("Как должен поступить администратор при получении жалобы?", ["Проверить доказательства и выслушать стороны", "Сразу наказать по просьбе знакомого", "Игнорировать жалобу", "Удалить обращение"], 0),
    ("Можно ли использовать административные права для личной выгоды?", ["Нет, права применяются только по назначению", "Да, если это незаметно", "Да, для друзей", "Можно без ограничений"], 0),
    ("Что делать, если администратор не уверен в пункте правил?", ["Уточнить правило у старшей администрации", "Выдумать наказание", "Спросить нарушителя", "Не обращать внимания"], 0),
    ("Как правильно общаться с игроком при разборе жалобы?", ["Спокойно, нейтрально и уважительно", "Грубо и с угрозами", "С насмешками", "Не объясняя ничего"], 0),
    ("Что важнее при вынесении решения?", ["Правила, доказательства и обстоятельства", "Личные отношения", "Количество просьб в чате", "Мнение друзей"], 0),
    ("Что нужно сделать перед выдачей наказания?", ["Проверить нарушение и соответствующий пункт правил", "Выбрать случайное наказание", "Спросить у нарушителя, какое наказание дать", "Наказать без причины"], 0),
    ("Как поступить при конфликте интересов?", ["Передать рассмотрение другому администратору", "Рассмотреть дело в пользу друга", "Удалить жалобу", "Скрыть конфликт"], 0),
    ("Можно ли раскрывать личные данные игрока без разрешения?", ["Нет", "Да, всем желающим", "Да, в общем чате", "Можно ради шутки"], 0),
    ("Что делать, если игрок предоставил неполные доказательства?", ["Запросить уточнения или принять решение по имеющимся правилам", "Додумать недостающие факты", "Сразу выдать максимальное наказание", "Оскорбить игрока"], 0),
    ("Как администратор должен вести себя вне разбирательств?", ["Соблюдать правила и подавать пример", "Считать себя выше правил", "Провоцировать игроков", "Использовать права для развлечения"], 0),
    ("Что делать при обнаружении ошибки в выданном наказании?", ["Сообщить руководству и исправить её по процедуре", "Скрыть ошибку", "Заблокировать заявителя", "Удалить логи"], 0),
    ("Можно ли принимать решение только на основании слухов?", ["Нет, нужны проверяемые обстоятельства", "Да, если слух популярный", "Да, если сообщил друг", "Можно без проверки"], 0),
    ("Как правильно реагировать на просьбу знакомого нарушить регламент?", ["Отказать и действовать по правилам", "Согласиться ради дружбы", "Попросить оплату", "Скрыть нарушение"], 0),
    ("Зачем нужна фиксация действий администрации?", ["Для прозрачности и последующей проверки", "Чтобы публиковать личные данные", "Чтобы скрывать нарушения", "Она никогда не нужна"], 0),
    ("Что делать, если жалоба касается вашего собственного действия?", ["Передать её независимому администратору", "Самому закрыть без проверки", "Удалить жалобу", "Наказать заявителя"], 0),
    ("Как следует обращаться с конфиденциальной служебной информацией?", ["Не распространять её посторонним", "Публиковать везде", "Передавать друзьям", "Использовать для шантажа"], 0),
    ("Что делать, если игрок не согласен с решением?", ["Объяснить порядок обжалования", "Угрожать ему", "Запретить задавать вопросы", "Оскорбить"], 0),
    ("Можно ли менять правила сервера самостоятельно?", ["Нет, изменения утверждаются уполномоченным руководством", "Да, в любое время", "Да, если администратор так решил", "Можно без уведомления"], 0),
    ("Как поступить при массовом нарушении порядка?", ["Действовать спокойно, по регламенту и при необходимости привлечь руководство", "Наказать всех без разбора", "Покинуть сервер", "Начать спор"], 0),
    ("Что является основой работы администратора?", ["Справедливость, знание правил и ответственность", "Личные симпатии", "Личная выгода", "Самовольные решения"], 0),
]

ORG_BANKS = {
    key: build_bank(name, role, topic)
    for key, (name, role, topic) in ORGANIZATIONS.items()
}

# Активные тесты хранятся в памяти процесса.
active_tests = {}

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 Тест на ЛД организации", callback_data="choose:ld")],
        [InlineKeyboardButton("🛡 Тест на администратора", callback_data="choose:admin")]
    ])

def org_keyboard():
    rows = []
    items = list(ORGANIZATIONS.items())
    for i in range(0, len(items), 2):
        row = []
        for key, data in items[i:i+2]:
            row.append(InlineKeyboardButton(data[0], callback_data=f"org:{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back:menu")])
    return InlineKeyboardMarkup(rows)

def question_keyboard(test):
    buttons = []
    for i, option in enumerate(test["current"]["options"]):
        buttons.append([InlineKeyboardButton(option, callback_data=f"answer:{i}")])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with db() as con:
        row = con.execute("SELECT proof_file_id FROM candidates WHERE user_id=?", (user.id,)).fetchone()
    if row and row["proof_file_id"]:
        await update.message.reply_text(
            "👋 Добро пожаловать в WEZING RUSSIA!\n\n"
            "Выберите тип тестирования:",
            reply_markup=main_menu()
        )
    else:
        await update.message.reply_text(
            "👋 Добро пожаловать в WEZING RUSSIA!\n\n"
            "📸 Сначала отправьте скриншот подтверждения назначения "
            "на форуме. После этого появится выбор тестирования."
        )

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo_id = update.message.photo[-1].file_id
    with db() as con:
        con.execute("""
            INSERT INTO candidates(user_id, full_name, username, proof_file_id, status, created_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                full_name=excluded.full_name,
                username=excluded.username,
                proof_file_id=excluded.proof_file_id,
                status='proof_received'
        """, (
            user.id, user.full_name, user.username or "",
            photo_id, "proof_received", datetime.utcnow().isoformat()
        ))
    await update.message.reply_text(
        "✅ Подтверждение получено!\n\nВыберите тип тестирования:",
        reply_markup=main_menu()
    )
    if ADMIN_ID:
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=photo_id,
                caption=(
                    "📸 Получено подтверждение кандидата\n\n"
                    f"Имя: {user.full_name}\n"
                    f"Username: @{user.username or 'не указан'}\n"
                    f"Telegram ID: {user.id}"
                )
            )
        except Exception:
            log.exception("Не удалось отправить фото администратору")

async def choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "choose:ld":
        await q.edit_message_text(
            "👑 Выберите организацию, на пост ЛД которой проходите тест:",
            reply_markup=org_keyboard()
        )
    elif q.data == "choose:admin":
        await begin_test(q, context, "admin", "Администрация", ADMIN_BANK)

async def begin_test(query, context, category, organization, bank):
    user = query.from_user
    with db() as con:
        row = con.execute(
            "SELECT proof_file_id FROM candidates WHERE user_id=?", (user.id,)
        ).fetchone()
        last = con.execute(
            "SELECT result, created_at FROM history WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user.id,)
        ).fetchone()

    # После неудачного теста повторная попытка доступна через 3 дня.
    if last and last["result"] == "fail":
        try:
            finished = datetime.fromisoformat(last["created_at"])
            elapsed = (datetime.utcnow() - finished).total_seconds()
            wait_seconds = 3 * 24 * 60 * 60 - elapsed
            if wait_seconds > 0:
                hours = int(wait_seconds // 3600)
                minutes = int((wait_seconds % 3600) // 60)
                await query.edit_message_text(
                    "⛔ Вы не набрали проходной балл в прошлый раз.\\n\\n"
                    f"Повторное тестирование будет доступно через {hours} ч. {minutes} мин."
                )
                return
        except (TypeError, ValueError):
            pass

    if not row or not row["proof_file_id"]:
        await query.edit_message_text(
            "Сначала отправьте скриншот подтверждения назначения через /start."
        )
        return

    # Перемешиваем порядок вопросов и вариантов, сохраняя правильный ответ.
    import random
    questions = []
    for source in bank:
        if isinstance(source, dict):
            q = source
            question = q["question"]
            options = list(q["options"])
            correct_text = options[q["correct"]]
        else:
            question, options, correct_index = source
            options = list(options)
            correct_text = options[correct_index]
        random.shuffle(options)
        questions.append({
            "question": question,
            "options": options,
            "correct": options.index(correct_text)
        })
    random.shuffle(questions)
    questions = questions[:QUESTION_COUNT]

    active_tests[user.id] = {
        "category": category,
        "organization": organization,
        "questions": questions,
        "index": 0,
        "score": 0,
        "started": time.time(),
        "deadline": time.time() + TEST_SECONDS,
        "current": questions[0],
    }
    await send_question(user.id, context)

async def send_question(user_id, context):
    test = active_tests.get(user_id)
    if not test:
        return
    if time.time() >= test["deadline"]:
        await finish_test(user_id, context, timed_out=True)
        return
    index = test["index"]
    question = test["current"]
    remaining = max(0, int(test["deadline"] - time.time()))
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"📝 {test['organization']}\n"
            f"Вопрос {index + 1}/{QUESTION_COUNT}\n"
            f"⏳ Осталось: {remaining // 60}:{remaining % 60:02d}\n\n"
            f"{question['question']}"
        ),
        reply_markup=question_keyboard(test)
    )
    if index == 0:
        asyncio.create_task(timeout_watch(user_id, context, test["deadline"]))

async def timeout_watch(user_id, context, deadline):
    await asyncio.sleep(max(0, deadline - time.time()))
    test = active_tests.get(user_id)
    if test and test["deadline"] == deadline:
        await finish_test(user_id, context, timed_out=True)

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    test = active_tests.get(user_id)
    if not test:
        await q.edit_message_text("Тест не найден. Нажмите /start.")
        return
    if time.time() >= test["deadline"]:
        await q.edit_message_text("⏰ Время теста закончилось.")
        await finish_test(user_id, context, timed_out=True)
        return
    try:
        selected = int(q.data.split(":")[1])
    except (ValueError, IndexError):
        return
    if selected == test["current"]["correct"]:
        test["score"] += 1
    test["index"] += 1
    if test["index"] >= QUESTION_COUNT:
        await q.edit_message_text("✅ Вы ответили на все вопросы. Подсчитываю результат…")
        await finish_test(user_id, context)
        return
    test["current"] = test["questions"][test["index"]]
    await q.edit_message_text("Ответ принят.")
    await send_question(user_id, context)

async def finish_test(user_id, context, timed_out=False):
    test = active_tests.pop(user_id, None)
    if not test:
        return
    score = test["score"]
    total = QUESTION_COUNT
    passed = score >= PASS_SCORE
    result = "pass" if passed else "fail"
    with db() as con:
        con.execute("""
            UPDATE candidates SET category=?, organization=?, score=?, total=?, status=?
            WHERE user_id=?
        """, (
            test["category"], test["organization"], score, total,
            "pending_review", user_id
        ))
        con.execute("""
            INSERT INTO history(user_id, category, organization, score, total, result, created_at)
            VALUES(?,?,?,?,?,?,?)
        """, (
            user_id, test["category"], test["organization"], score,
            total, result, datetime.utcnow().isoformat()
        ))
        row = con.execute(
            "SELECT full_name, username, proof_file_id FROM candidates WHERE user_id=?",
            (user_id,)
        ).fetchone()

    player_text = (
        "⏰ Время вышло.\n\n" if timed_out else ""
    ) + (
        f"📊 Тест завершён!\n\n"
        f"Правильных ответов: {score}/{total}\n"
        f"Необходимый результат: {PASS_SCORE}/{total}\n\n"
        "✅ Вы набрали проходной балл. Результат отправлен администрации "
        "на проверку. Это ещё не означает автоматическое назначение."
        if passed else
        f"📊 Тест завершён!\n\n"
        f"Правильных ответов: {score}/{total}\n"
        f"Необходимый результат: {PASS_SCORE}/{total}\n\n"
        "❌ Проходной балл не набран. Обратитесь к администрации "
        "для уточнения возможности повторного тестирования."
    )
    try:
        await context.bot.send_message(user_id, player_text)
    except Exception:
        log.exception("Не удалось отправить результат игроку")

    if ADMIN_ID:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Одобрить", callback_data=f"review:approve:{user_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"review:reject:{user_id}")
            ]
        ])
        username = "@" + row["username"] if row["username"] else "не указан"
        report = (
            "📋 РЕЗУЛЬТАТ ТЕСТИРОВАНИЯ\n\n"
            f"👤 Игрок: {row['full_name']}\n"
            f"🔗 Username: {username}\n"
            f"🆔 Telegram ID: {user_id}\n"
            f"🎯 Тип: {'ЛД организации' if test['category'] == 'ld' else 'Администрация'}\n"
            f"🏢 Организация: {test['organization']}\n"
            f"📊 Результат: {score}/{total}\n"
            f"📌 Статус теста: {'ПРОЙДЕН' if passed else 'НЕ ПРОЙДЕН'}\n"
            "🕒 Статус заявки: ожидает ручной проверки"
        )
        try:
            if row["proof_file_id"]:
                await context.bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=row["proof_file_id"],
                    caption=report,
                    reply_markup=keyboard
                )
            else:
                await context.bot.send_message(
                    chat_id=ADMIN_ID, text=report, reply_markup=keyboard
                )
        except Exception:
            log.exception("Не удалось отправить отчёт администратору")

async def review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer("⛔ Нет доступа", show_alert=True)
        return
    await q.answer()
    try:
        _, action, player_id = q.data.split(":")
        player_id = int(player_id)
    except Exception:
        return
    status = "approved" if action == "approve" else "rejected"
    with db() as con:
        con.execute("UPDATE candidates SET status=? WHERE user_id=?", (status, player_id))
        row = con.execute(
            "SELECT category, organization FROM candidates WHERE user_id=?",
            (player_id,)
        ).fetchone()
    if action == "approve":
        role = "администрации" if row and row["category"] == "admin" else f"ЛД организации {row['organization'] if row else ''}"
        message = (
            "🎉 Поздравляем!\n\n"
            f"Ваша заявка на пост {role} в WEZING RUSSIA одобрена администрацией."
        )
        label = "✅ ОДОБРЕНО"
    else:
        message = (
            "❌ Ваша заявка WEZING RUSSIA отклонена администрацией.\n"
            "Если у вас есть вопросы, обратитесь к руководству проекта."
        )
        label = "❌ ОТКЛОНЕНО"
    try:
        await context.bot.send_message(player_id, message)
        note = ""
    except Exception:
        note = " (игроку не удалось отправить сообщение)"
    try:
        caption = q.message.caption or q.message.text or "Результат"
        if q.message.photo:
            await q.edit_message_caption(caption=f"{caption}\n\n{label}{note}", reply_markup=None)
        else:
            await q.edit_message_text(text=f"{caption}\n\n{label}{note}", reply_markup=None)
    except Exception:
        pass

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Нет доступа.")
        return
    with db() as con:
        total = con.execute("SELECT COUNT(*) n FROM candidates").fetchone()["n"]
        pending = con.execute(
            "SELECT COUNT(*) n FROM candidates WHERE status='pending_review'"
        ).fetchone()["n"]
        history_count = con.execute("SELECT COUNT(*) n FROM history").fetchone()["n"]
        rows = con.execute("""
            SELECT user_id, full_name, category, organization, score, total, status
            FROM candidates ORDER BY created_at DESC LIMIT 10
        """).fetchall()
    lines = [
        "🛠 WEZING RUSSIA — АДМИН-ПАНЕЛЬ",
        "",
        f"Всего кандидатов: {total}",
        f"Ожидают проверки: {pending}",
        f"Всего завершённых тестов: {history_count}",
        "",
        "Последние кандидаты:"
    ]
    for r in rows:
        lines.append(
            f"• {r['full_name']} | {r['organization'] or 'не выбрано'} | "
            f"{r['score'] if r['score'] is not None else '-'}"
            f"/{r['total'] if r['total'] is not None else '-'} | {r['status']}"
        )
    await update.message.reply_text("\n".join(lines))

async def text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Используйте кнопки меню. Для начала нажмите /start."
    )

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    if data.startswith("choose:"):
        await choose(update, context)
    elif data.startswith("org:"):
        await q.answer()
        key = data.split(":", 1)[1]
        if key not in ORGANIZATIONS:
            await q.edit_message_text("Организация не найдена. Нажмите /start.")
            return
        await begin_test(q, context, "ld", ORGANIZATIONS[key][0], ORG_BANKS[key])
    elif data == "back:menu":
        await q.answer()
        await q.edit_message_text("Выберите тип тестирования:", reply_markup=main_menu())
    elif data.startswith("answer:"):
        await answer(update, context)
    elif data.startswith("review:"):
        await review(update, context)

def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в переменных Render")
    if not ADMIN_ID:
        raise RuntimeError("Не задан ADMIN_ID в переменных Render")
    init_db()
    asyncio.set_event_loop(asyncio.new_event_loop())
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(MessageHandler(filters.PHOTO, receive_photo))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_fallback))
    threading.Thread(target=run_web, daemon=True).start()
    log.info("WEZING RUSSIA TEST SYSTEM запущен")
    application.run_polling()

if __name__ == "__main__":
    main()
