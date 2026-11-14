import os
import re
import json
import time
import sqlite3
import logging
import threading
import asyncio
from datetime import datetime, timedelta, timezone

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
DB_PATH = os.getenv("DB_PATH", "wezing_tests.db")
PORT = int(os.getenv("PORT", "10000"))
TEST_SECONDS = int(os.getenv("TEST_SECONDS", "300"))
QUESTION_COUNT = int(os.getenv("QUESTION_COUNT", "20"))
PASS_SCORE = int(os.getenv("PASS_SCORE", "13"))
PREP_MINUTES = int(os.getenv("PREP_MINUTES", "5"))
COOLDOWN_HOURS = int(os.getenv("COOLDOWN_HOURS", str(72)))
MEDIA_MIN_VIEWS = int(os.getenv("MEDIA_MIN_VIEWS", "300"))
MEDIA_MIN_FOLLOWERS = int(os.getenv("MEDIA_MIN_FOLLOWERS", "30"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wezing-test")
web = Flask(__name__)

@web.route("/")
def home():
    return "WEZING RUSSIA TEST SYSTEM: OK"

def run_web():
    web.run(host="0.0.0.0", port=PORT, use_reloader=False)

def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS candidates(
            user_id INTEGER PRIMARY KEY, full_name TEXT, username TEXT,
            proof_file_id TEXT, category TEXT, organization TEXT,
            score INTEGER, total INTEGER, status TEXT DEFAULT 'new', created_at TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            category TEXT, organization TEXT, score INTEGER, total INTEGER,
            result TEXT, created_at TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS media_apps(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, full_name TEXT,
            username TEXT, game_nick TEXT, tiktok TEXT, followers INTEGER, views INTEGER,
            video_url TEXT, status TEXT DEFAULT 'new', created_at TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS knowledge(
            id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, answer TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT, price TEXT, active INTEGER DEFAULT 1)""")
        con.execute("""CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_id INTEGER,
            product_title TEXT, status TEXT DEFAULT 'new', created_at TEXT)""")
        defaults = {
            "question_count": str(QUESTION_COUNT), "test_seconds": str(TEST_SECONDS),
            "pass_score": str(PASS_SCORE), "prep_minutes": str(PREP_MINUTES),
            "cooldown_hours": str(COOLDOWN_HOURS),
            "media_min_views": str(MEDIA_MIN_VIEWS),
            "media_min_followers": str(MEDIA_MIN_FOLLOWERS)
        }
        for k, v in defaults.items():
            con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))

def setting(key, default):
    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    try:
        return int(row["value"]) if row else int(default)
    except (ValueError, TypeError):
        return int(default)

def set_setting(key, value):
    with db() as con:
        con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value)))

ORGANIZATIONS = {
    "fsb": ("ФСБ", "сотрудник ФСБ", "служебная дисциплина и правила проекта"),
    "gibdd": ("ГИБДД", "сотрудник ГИБДД", "дорожный порядок и правила проекта"),
    "umvd": ("УМВД", "сотрудник УМВД", "охрана порядка и правила проекта"),
    "vch": ("ВЧ", "военнослужащий", "военная дисциплина и правила проекта"),
    "cb": ("ЦБ", "сотрудник ЦБ", "обслуживание и правила проекта"),
    "media": ("СМИ", "сотрудник СМИ", "эфиры, публикации и правила проекта"),
    "government": ("Правительство", "сотрудник Правительства", "государственные обязанности и правила проекта"),
    "law": ("Право", "представитель закона", "законы и правила проекта"),
    "arz": ("ОПГ ARZ", "участник ОПГ ARZ", "правила организации и RP"),
    "bat": ("ОПГ BAT", "участник ОПГ BAT", "правила организации и RP"),
    "lyt": ("ОПГ LYT", "участник ОПГ LYT", "правила организации и RP"),
}

def make_bank(org, role, topic):
    prompts = [
        ("Что должен сделать {role} перед служебным действием?", ["Проверить IC-причину и правила", "Начать без причины", "Игнорировать правила", "Попросить выйти из игры"], 0),
        ("Как отвечать гражданину по служебному вопросу?", ["Спокойно и в рамках полномочий", "Оскорбить", "Игнорировать всегда", "Наказать за вопрос"], 0),
        ("Что важнее всего при выполнении обязанностей?", ["Правила сервера и RP", "Личная выгода", "OOC-спор", "Самовольные правила"], 0),
        ("Что делать при обнаружении нарушения?", ["Зафиксировать и действовать по регламенту", "Наказать без проверки", "Удалить доказательства", "Попросить друга решить"], 0),
        ("Как общаться во время RP-ситуации?", ["Корректно и без OOC-конфликта", "Грубо", "Только капсом", "Не отвечать"], 0),
        ("Что означает субординация?", ["Служебное взаимодействие по иерархии", "Любые личные просьбы", "Игнорирование руководства", "Самостоятельная выдача званий"], 0),
        ("Что делать, если приказ противоречит правилам?", ["Не нарушать правила и сообщить руководству", "Выполнить любой ценой", "Скрыть ситуацию", "Потребовать награду"], 0),
        ("Что делать, если процедура неизвестна?", ["Уточнить регламент у руководства", "Придумать правило", "Действовать наугад", "Игнорировать"], 0),
        ("Можно ли использовать полномочия ради личной выгоды?", ["Нет, только по назначению", "Да, если никто не видит", "Для друзей можно", "Без ограничений"], 0),
        ("Что сделать перед публикацией служебной информации?", ["Проверить достоверность и разрешение", "Опубликовать слух", "Изменить факты", "Раскрыть личные данные"], 0),
        ("Как решить конфликт с коллегой?", ["Спокойно обратиться к руководству", "Устроить ссору", "Мстить полномочиями", "Распространять слухи"], 0),
        ("Что является хорошим доказательством нарушения?", ["Запись или скриншот с контекстом", "Слухи", "Пересказ без деталей", "Предположение"], 0),
        ("Можно ли нарушать RP ради быстрого завершения ситуации?", ["Нет, соблюдать правила RP", "Да, если спешишь", "Если выгодно", "По просьбе друга"], 0),
        ("Что делать при жалобе на ваши действия?", ["Сохранить материалы и дать объяснение", "Угрожать заявителю", "Удалить переписку", "Игнорировать"], 0),
        ("Как использовать служебное имущество?", ["По служебной необходимости и правилам", "Для любых личных дел", "Передавать кому угодно", "Без ограничений"], 0),
        ("Что делать при собственной ошибке?", ["Признать и сообщить руководству", "Скрыть", "Обвинить другого", "Удалить доказательства"], 0),
        ("Как реагировать на OOC-провокацию?", ["Не поддерживать конфликт и соблюдать правила", "Оскорблять в ответ", "Мстить полномочиями", "Продолжить спор"], 0),
        ("Зачем знать обязанности {role}?", ["Чтобы действовать в пределах полномочий", "Для преимущества вне правил", "Чтобы игнорировать руководство", "Чтобы менять правила"], 0),
        ("Что сделать перед служебным мероприятием?", ["Уточнить задачу и регламент", "Начать без плана", "Ничего не сообщать", "Игнорировать безопасность"], 0),
        ("Что показывает готовность к должности?", ["Ответственность и знание правил", "Личные споры статусом", "Отказ от обязанностей", "Нарушение дисциплины"], 0),
    ]
    return [{"question": q.format(role=role, topic=topic), "options": opts[:], "correct": idx} for q, opts, idx in prompts]

ADMIN_BANK = [
    ("Как поступить при получении жалобы?", ["Проверить доказательства и выслушать стороны", "Наказать знакомого", "Игнорировать", "Удалить обращение"], 0),
    ("Можно ли использовать права для личной выгоды?", ["Нет, только по назначению", "Да, незаметно", "Для друзей", "Без ограничений"], 0),
    ("Что делать, если пункт правил неизвестен?", ["Уточнить у старшей администрации", "Выдумать наказание", "Спросить нарушителя", "Не обращать внимания"], 0),
    ("Как общаться при разборе жалобы?", ["Нейтрально и уважительно", "Грубо", "С насмешками", "Без объяснений"], 0),
    ("Что важнее при вынесении решения?", ["Правила, доказательства и обстоятельства", "Личные отношения", "Просьбы друзей", "Слухи"], 0),
    ("Что сделать перед наказанием?", ["Проверить нарушение и пункт правил", "Выбрать случайно", "Спросить наказание у нарушителя", "Наказать без причины"], 0),
    ("Как поступить при конфликте интересов?", ["Передать дело другому администратору", "Решить в пользу друга", "Удалить жалобу", "Скрыть конфликт"], 0),
    ("Можно ли раскрывать личные данные игрока?", ["Нет, без законного основания и разрешения нельзя", "Да, всем", "В общий чат", "Ради шутки"], 0),
    ("Что делать при неполных доказательствах?", ["Запросить уточнения", "Додумать факты", "Сразу наказать", "Оскорбить"], 0),
    ("Как вести себя вне разбирательств?", ["Соблюдать правила и подавать пример", "Считать себя выше правил", "Провоцировать", "Развлекаться правами"], 0),
    ("Что делать при ошибке в наказании?", ["Сообщить руководству и исправить по процедуре", "Скрыть", "Заблокировать заявителя", "Удалить логи"], 0),
    ("Можно ли принимать решение по слухам?", ["Нет, нужны проверяемые факты", "Да, если слух популярен", "Если сказал друг", "Без проверки"], 0),
    ("Как реагировать на просьбу нарушить регламент?", ["Отказать и соблюдать правила", "Согласиться", "Попросить оплату", "Скрыть"], 0),
    ("Зачем фиксировать действия администрации?", ["Для прозрачности и проверки", "Для публикации личных данных", "Чтобы скрывать нарушения", "Не нужно"], 0),
    ("Что делать, если жалоба на ваши действия?", ["Передать независимому администратору", "Закрыть самому", "Удалить", "Наказать заявителя"], 0),
    ("Как обращаться с конфиденциальной информацией?", ["Не передавать посторонним", "Публиковать везде", "Передавать друзьям", "Использовать для шантажа"], 0),
    ("Что делать, если игрок не согласен?", ["Объяснить порядок обжалования", "Угрожать", "Запретить вопросы", "Оскорбить"], 0),
    ("Можно ли самостоятельно менять правила сервера?", ["Нет, изменения утверждает руководство", "Да, всегда", "Если администратор решил", "Без уведомления"], 0),
    ("Как действовать при массовом нарушении?", ["Спокойно, по регламенту, при необходимости привлечь руководство", "Наказать всех", "Уйти", "Начать спор"], 0),
    ("Основа работы администратора?", ["Справедливость, знание правил и ответственность", "Симпатии", "Выгода", "Самовольность"], 0),
]

active_tests = {}
pending_flows = {}

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 Тест на ЛД организации", callback_data="choose:ld")],
        [InlineKeyboardButton("🛡 Тест на администратора", callback_data="choose:admin")],
        [InlineKeyboardButton("📱 Подать заявку на медиа", callback_data="media:start")],
        [InlineKeyboardButton("📚 Подготовка к тесту", callback_data="prep:menu")],
        [InlineKeyboardButton("🤖 Помощь по WEZING", callback_data="help:menu")],
        [InlineKeyboardButton("🛒 Магазин", callback_data="shop:menu")],
    ])

def org_keyboard():
    rows, items = [], list(ORGANIZATIONS.items())
    for i in range(0, len(items), 2):
        rows.append([InlineKeyboardButton(ORGANIZATIONS[k][0], callback_data=f"org:{k}") for k, _ in items[i:i+2]])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back:menu")])
    return InlineKeyboardMarkup(rows)

def is_admin(user_id):
    return ADMIN_ID and user_id == ADMIN_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with db() as con:
        row = con.execute("SELECT proof_file_id FROM candidates WHERE user_id=?", (user.id,)).fetchone()
    msg = "👋 Добро пожаловать в WEZING RUSSIA!\n\n"
    if not row or not row["proof_file_id"]:
        msg += "Для тестирования понадобится скриншот подтверждения назначения на форуме. Заявку на медиа можно подать без него.\n\n"
    await update.message.reply_text(msg + "Выберите нужный раздел:", reply_markup=main_menu())

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo_id = update.message.photo[-1].file_id
    with db() as con:
        con.execute("""INSERT INTO candidates(user_id,full_name,username,proof_file_id,status,created_at)
        VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET full_name=excluded.full_name,
        username=excluded.username,proof_file_id=excluded.proof_file_id,status='proof_received'""",
        (user.id, user.full_name, user.username or "", photo_id, "proof_received", datetime.now(timezone.utc).isoformat()))
    await update.message.reply_text("✅ Скриншот получен. Выберите раздел:", reply_markup=main_menu())
    if ADMIN_ID:
        try:
            await context.bot.send_photo(ADMIN_ID, photo_id, caption=f"Подтверждение назначения\n{user.full_name}\nID: {user.id}")
        except Exception:
            log.exception("Admin photo notify failed")

def get_bank(category, org_key=None):
    if category == "admin":
        return [{"question": q, "options": o[:], "correct": c} for q, o, c in ADMIN_BANK]
    name, role, topic = ORGANIZATIONS[org_key]
    return make_bank(name, role, topic)

async def begin_test(query, context, category, organization, bank):
    import random
    uid = query.from_user.id
    with db() as con:
        proof = con.execute("SELECT proof_file_id FROM candidates WHERE user_id=?", (uid,)).fetchone()
        last = con.execute("""SELECT created_at FROM history WHERE user_id=? AND category=? AND organization=?
            AND result='fail' ORDER BY id DESC LIMIT 1""", (uid, category, organization)).fetchone()
    if not proof or not proof["proof_file_id"]:
        await query.edit_message_text("Сначала отправьте скриншот подтверждения назначения через /start.")
        return
    if last:
        try:
            end = datetime.fromisoformat(last["created_at"]) + timedelta(hours=setting("cooldown_hours", 72))
            now = datetime.now(timezone.utc)
            if end.tzinfo is None: end = end.replace(tzinfo=timezone.utc)
            if end > now:
                await query.edit_message_text("⛔ Повторная попытка пока недоступна.\nМожно пройти тест: " + end.astimezone().strftime("%d.%m.%Y в %H:%M"))
                return
        except Exception:
            pass
    random.shuffle(bank)
    questions = []
    for src in bank:
        opts = list(src["options"])
        correct_text = opts[src["correct"]]
        random.shuffle(opts)
        questions.append({"question": src["question"], "options": opts, "correct": opts.index(correct_text)})
    count = min(setting("question_count", 20), len(questions))
    questions = questions[:count]
    if not questions:
        await query.edit_message_text("В банке пока нет вопросов.")
        return
    active_tests[uid] = {"category": category, "organization": organization, "questions": questions,
        "index": 0, "score": 0, "deadline": time.time()+setting("test_seconds",300),
        "current": questions[0], "total": len(questions)}
    await query.edit_message_text("Тест начинается. Удачи!")
    await send_question(uid, context)

def question_keyboard(test):
    return InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"answer:{i}")]
                                 for i, opt in enumerate(test["current"]["options"])])

async def send_question(uid, context):
    test = active_tests.get(uid)
    if not test: return
    if time.time() >= test["deadline"]:
        await finish_test(uid, context, timed_out=True); return
    q = test["current"]
    remain = max(0, int(test["deadline"]-time.time()))
    await context.bot.send_message(uid,
        f"📝 {test['organization']}\nВопрос {test['index']+1}/{test['total']}\n"
        f"⏳ Осталось: {remain//60}:{remain%60:02d}\n\n{q['question']}",
        reply_markup=question_keyboard(test))
    if test["index"] == 0:
        asyncio.create_task(timeout_watch(uid, context, test["deadline"]))

async def timeout_watch(uid, context, deadline):
    await asyncio.sleep(max(0, deadline-time.time()))
    t = active_tests.get(uid)
    if t and t["deadline"] == deadline:
        await finish_test(uid, context, timed_out=True)

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    test = active_tests.get(uid)
    if not test:
        await q.edit_message_text("Тест не найден. Нажмите /start.")
        return
    if time.time() >= test["deadline"]:
        await q.edit_message_text("⏰ Время теста закончилось.")
        await finish_test(uid, context, timed_out=True); return
    try: selected = int(q.data.split(":")[1])
    except Exception: return
    if selected == test["current"]["correct"]: test["score"] += 1
    test["index"] += 1
    if test["index"] >= test["total"]:
        await q.edit_message_text("Ответ принят. Подсчитываю результат…")
        await finish_test(uid, context); return
    test["current"] = test["questions"][test["index"]]
    await q.edit_message_text("Ответ принят.")
    await send_question(uid, context)

async def finish_test(uid, context, timed_out=False):
    test = active_tests.pop(uid, None)
    if not test: return
    score, total = test["score"], test["total"]
    passed = score >= setting("pass_score", 13)
    result = "pass" if passed else "fail"
    now = datetime.now(timezone.utc).isoformat()
    with db() as con:
        con.execute("""UPDATE candidates SET category=?,organization=?,score=?,total=?,status=? WHERE user_id=?""",
                    (test["category"], test["organization"], score, total, result, uid))
        con.execute("""INSERT INTO history(user_id,category,organization,score,total,result,created_at)
                    VALUES(?,?,?,?,?,?,?)""", (uid,test["category"],test["organization"],score,total,result,now))
    if passed:
        text = f"🎉 Поздравляем! Вы прошли тест.\nРезультат: {score}/{total}."
    else:
        unlock = datetime.now(timezone.utc) + timedelta(hours=setting("cooldown_hours",72))
        text = (f"❌ Тест не пройден.\nРезультат: {score}/{total}.\n\n"
                f"🔴 Повторная попытка будет доступна только через {setting('cooldown_hours',72)//24} дня.\n"
                f"Дата следующей попытки: {unlock.astimezone().strftime('%d.%m.%Y в %H:%M')}.")
    if timed_out: text = "⏰ Время теста закончилось.\n\n" + text
    await context.bot.send_message(uid, text)
    if ADMIN_ID:
        try: await context.bot.send_message(ADMIN_ID, f"Результат теста\nID: {uid}\n{test['organization']}\n{score}/{total}\n{result}")
        except Exception: log.exception("Result notify failed")

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    if data.startswith("answer:"):
        await answer(update, context); return
    await q.answer()
    if data == "choose:ld":
        await q.edit_message_text("Выберите организацию:", reply_markup=org_keyboard())
    elif data == "choose:admin":
        await begin_test(q, context, "admin", "Администрация", get_bank("admin"))
    elif data.startswith("org:"):
        key = data.split(":",1)[1]
        if key not in ORGANIZATIONS: return
        if context.user_data.pop("prep_choose", False):
            await start_prep(q.from_user.id, context, "ld", ORGANIZATIONS[key][0], get_bank("ld", key))
            await q.edit_message_text("📚 Подготовка началась. Ответьте на тренировочные вопросы. После завершения будет пауза перед настоящим тестом.")
        else:
            await begin_test(q, context, "ld", ORGANIZATIONS[key][0], get_bank("ld", key))
    elif data == "back:menu":
        await q.edit_message_text("Главное меню:", reply_markup=main_menu())
    elif data == "prep:menu":
        await q.edit_message_text("Подготовка: выберите направление.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Тест ЛД", callback_data="prep:ld")],
            [InlineKeyboardButton("Тест администрации", callback_data="prep:admin")],
            [InlineKeyboardButton("Назад", callback_data="back:menu")]]))
    elif data == "prep:ld":
        await q.edit_message_text("Выберите организацию для подготовки:", reply_markup=org_keyboard())
        context.user_data["prep_choose"] = True
    elif data == "prep:admin":
        await start_prep(uid=q.from_user.id, context=context, category="admin", organization="Администрация", bank=get_bank("admin"))
        await q.edit_message_text("📚 Подготовка началась. Ответьте на тренировочные вопросы. После завершения будет пауза перед настоящим тестом.")
    elif data.startswith("media:"):
        await media_callback(q, context)
    elif data.startswith("help:"):
        await q.edit_message_text("🤖 Помощь WEZING\n\nНапишите ключевое слово или вопрос о проекте. Ответы берутся из базы знаний, которую администратор может пополнять через /admin.")
    elif data == "shop:menu":
        await show_shop(q, context)
    elif data.startswith("order:"):
        pid = int(data.split(":")[1])
        with db() as con:
            p = con.execute("SELECT * FROM products WHERE id=? AND active=1",(pid,)).fetchone()
            if not p:
                await q.edit_message_text("Товар больше недоступен."); return
            cur = con.execute("INSERT INTO orders(user_id,product_id,product_title,created_at) VALUES(?,?,?,?)",
                              (q.from_user.id,pid,p["title"],datetime.now(timezone.utc).isoformat()))
            oid = cur.lastrowid
        await q.edit_message_text(f"✅ Заявка на товар «{p['title']}» создана. Номер заказа: #{oid}. Администрация свяжется с вами.")
        if ADMIN_ID:
            await context.bot.send_message(ADMIN_ID, f"🛒 Новый заказ #{oid}\nТовар: {p['title']}\nПользователь: {q.from_user.id}")
    elif data.startswith("media_review:"):
        await review_media(q, context)

async def start_prep(uid, context, category, organization, bank):
    import random
    random.shuffle(bank)
    questions = []
    for src in bank[:min(5,len(bank))]:
        opts = list(src["options"]); correct_text=opts[src["correct"]]; random.shuffle(opts)
        questions.append({"question":src["question"],"options":opts,"correct":opts.index(correct_text)})
    pending_flows[uid] = {"type":"prep","category":category,"organization":organization,
                          "questions":questions,"index":0,"score":0}
    await send_prep_question(uid, context)

async def send_prep_question(uid, context):
    flow=pending_flows.get(uid)
    if not flow: return
    q=flow["questions"][flow["index"]]
    kb=InlineKeyboardMarkup([[InlineKeyboardButton(o,callback_data=f"prepanswer:{i}")] for i,o in enumerate(q["options"])])
    await context.bot.send_message(uid,f"📚 Тренировка {flow['index']+1}/{len(flow['questions'])}\n\n{q['question']}",reply_markup=kb)

async def prep_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    uid=q.from_user.id; flow=pending_flows.get(uid)
    if not flow: return
    try: selected=int(q.data.split(":")[1])
    except Exception: return
    if selected==flow["questions"][flow["index"]]["correct"]: flow["score"]+=1
    flow["index"]+=1
    if flow["index"]>=len(flow["questions"]):
        pending_flows.pop(uid,None)
        delay=setting("prep_minutes",5)
        await q.edit_message_text(
            f"✅ Подготовка завершена! Результат: {flow['score']}/{len(flow['questions'])}.\n\n"
            f"Настоящий тест начнётся через {delay} минут.\n"
            f"🔴 Если вы не пройдёте тест, повторная попытка будет доступна только через 3 дня!")
        context.job_queue.run_once(real_test_job, when=delay*60, data={
            "uid":uid,"category":flow["category"],"organization":flow["organization"]})
        return
    await q.edit_message_text("Ответ принят.")
    await send_prep_question(uid,context)

async def real_test_job(context: ContextTypes.DEFAULT_TYPE):
    data=context.job.data; uid=data["uid"]
    if data["category"]=="admin":
        bank=get_bank("admin")
    else:
        key=next((k for k,v in ORGANIZATIONS.items() if v[0]==data["organization"]),None)
        if not key: return
        bank=get_bank("ld",key)
    class FakeQuery:
        from_user=type("U",(),{"id":uid})()
        async def edit_message_text(self,*a,**kw): pass
    await begin_test(FakeQuery(),context,data["category"],data["organization"],bank)

async def media_start(q, context):
    uid=q.from_user.id
    pending_flows[uid]={"type":"media","step":"nick","data":{}}
    await q.edit_message_text("📱 Заявка на медиа WEZING RUSSIA\n\n1/5. Напишите ваш игровой ник.")

async def media_callback(q, context):
    if q.data=="media:start":
        await media_start(q,context)

async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id; text=update.message.text.strip()
    flow=pending_flows.get(uid)
    if flow and flow.get("type")=="media":
        step=flow["step"]
        if step=="nick":
            flow["data"]["nick"]=text; flow["step"]="tiktok"
            await update.message.reply_text("2/5. Отправьте ссылку на ваш TikTok-аккаунт.")
        elif step=="tiktok":
            if not re.match(r"^https?://(www\.)?tiktok\.com/",text,re.I):
                await update.message.reply_text("Нужна корректная ссылка на профиль TikTok. Попробуйте ещё раз."); return
            flow["data"]["tiktok"]=text; flow["step"]="followers"
            await update.message.reply_text("3/5. Сколько у вас подписчиков? Укажите число.")
        elif step=="followers":
            if not text.isdigit(): await update.message.reply_text("Введите число подписчиков."); return
            flow["data"]["followers"]=int(text); flow["step"]="views"
            await update.message.reply_text("4/5. Сколько в среднем просмотров набирают ваши видео? Укажите число.")
        elif step=="views":
            if not text.isdigit(): await update.message.reply_text("Введите число просмотров."); return
            flow["data"]["views"]=int(text); flow["step"]="video"
            await update.message.reply_text("5/5. Отправьте ссылку на TikTok-видео именно о проекте WEZING RUSSIA.")
        elif step=="video":
            if not re.match(r"^https?://(www\.)?(tiktok\.com|vm\.tiktok\.com)/",text,re.I):
                await update.message.reply_text("Принимается только ссылка на видео TikTok. Отправьте ссылку ещё раз."); return
            d=flow["data"]
            with db() as con:
                cur=con.execute("""INSERT INTO media_apps(user_id,full_name,username,game_nick,tiktok,followers,views,video_url,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""",(uid,update.effective_user.full_name,update.effective_user.username or "",
                    d["nick"],d["tiktok"],d["followers"],d["views"],text,datetime.now(timezone.utc).isoformat()))
                app_id=cur.lastrowid
            pending_flows.pop(uid,None)
            minv=setting("media_min_views",300); minf=setting("media_min_followers",30)
            meets=d["views"]>=minv and d["followers"]>=minf
            await update.message.reply_text(
                f"✅ Заявка №{app_id} отправлена администрации.\n"
                f"Подписчики: {d['followers']} (минимум {minf})\n"
                f"Просмотры: {d['views']} (минимум {minv})\n"
                f"Условия по числам: {'выполнены' if meets else 'не выполнены'}.\n"
                "Видео и аккаунт администрация проверит вручную.")
            if ADMIN_ID:
                kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Одобрить",callback_data=f"media_review:{app_id}:approved"),
                                          InlineKeyboardButton("❌ Отклонить",callback_data=f"media_review:{app_id}:rejected")]])
                await context.bot.send_message(ADMIN_ID,
                    f"📱 Новая заявка на медиа #{app_id}\nИгровой ник: {d['nick']}\n"
                    f"Пользователь: {update.effective_user.full_name} (ID {uid})\nTikTok: {d['tiktok']}\n"
                    f"Подписчики: {d['followers']}\nСредние просмотры: {d['views']}\n"
                    f"Видео о WEZING: {text}\nЧисловые требования: {'выполнены' if meets else 'не выполнены'}",
                    reply_markup=kb)
        return
    if is_admin(uid) and context.user_data.get("admin_action"):
        action=context.user_data.pop("admin_action")
        if action=="views":
            if text.isdigit(): set_setting("media_min_views",int(text)); await update.message.reply_text("Минимум просмотров обновлён.")
            else: await update.message.reply_text("Нужно число.")
        elif action=="followers":
            if text.isdigit(): set_setting("media_min_followers",int(text)); await update.message.reply_text("Минимум подписчиков обновлён.")
            else: await update.message.reply_text("Нужно число.")
        elif action=="knowledge":
            if "|" not in text: await update.message.reply_text("Формат: вопрос | ответ"); return
            question,answer_text=[x.strip() for x in text.split("|",1)]
            with db() as con: con.execute("INSERT INTO knowledge(question,answer) VALUES(?,?)",(question,answer_text))
            await update.message.reply_text("Запись базы знаний добавлена.")
        elif action=="product":
            parts=[x.strip() for x in text.split("|")]
            if len(parts)<3: await update.message.reply_text("Формат: название | описание | цена"); return
            with db() as con: con.execute("INSERT INTO products(title,description,price) VALUES(?,?,?)",tuple(parts[:3]))
            await update.message.reply_text("Товар добавлен.")
        return
    # Lightweight project FAQ: only answers from admin-maintained knowledge base.
    with db() as con:
        rows=con.execute("SELECT question,answer FROM knowledge").fetchall()
    matches=[r for r in rows if any(word.lower() in (r["question"] or "").lower() for word in text.lower().split() if len(word)>3)]
    if matches:
        await update.message.reply_text(matches[0]["answer"])
    else:
        await update.message.reply_text("Пока нет ответа в базе знаний. Передал бы вопрос администратору — добавьте информацию через /admin.")

async def review_media(q, context):
    if not is_admin(q.from_user.id):
        await q.answer("Нет доступа.",show_alert=True); return
    parts=q.data.split(":"); app_id=int(parts[1]); status=parts[2]
    with db() as con:
        row=con.execute("SELECT user_id FROM media_apps WHERE id=?",(app_id,)).fetchone()
        if not row: await q.edit_message_text("Заявка не найдена."); return
        con.execute("UPDATE media_apps SET status=? WHERE id=?",(status,app_id))
    await q.edit_message_text(f"Заявка #{app_id}: {status}.")
    try: await context.bot.send_message(row["user_id"],"✅ Ваша заявка на медиа одобрена!" if status=="approved" else "❌ Ваша заявка на медиа отклонена.")
    except Exception: pass

async def show_shop(q, context):
    with db() as con: rows=con.execute("SELECT * FROM products WHERE active=1 ORDER BY id DESC").fetchall()
    if not rows:
        await q.edit_message_text("🛒 Магазин пока пуст."); return
    buttons=[[InlineKeyboardButton(f"{r['title']} — {r['price']}",callback_data=f"order:{r['id']}")] for r in rows]
    buttons.append([InlineKeyboardButton("Назад",callback_data="back:menu")])
    await q.edit_message_text("🛒 Магазин WEZING RUSSIA\nВыберите товар:",reply_markup=InlineKeyboardMarkup(buttons))

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа."); return
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика",callback_data="adm:stats")],
        [InlineKeyboardButton("👁 Мин. просмотры медиа",callback_data="adm:views"),
         InlineKeyboardButton("👥 Мин. подписчики",callback_data="adm:followers")],
        [InlineKeyboardButton("📚 Добавить знание",callback_data="adm:knowledge")],
        [InlineKeyboardButton("🛒 Добавить товар",callback_data="adm:product")],
        [InlineKeyboardButton("⚙️ Настройки теста",callback_data="adm:settings")],
    ])
    await update.message.reply_text("🔐 Панель администратора",reply_markup=kb)

async def admin_callback(q, context):
    if not is_admin(q.from_user.id):
        await q.answer("Нет доступа",show_alert=True); return
    data=q.data
    if data=="adm:stats":
        with db() as con:
            candidates=con.execute("SELECT COUNT(*) n FROM candidates").fetchone()["n"]
            tests=con.execute("SELECT COUNT(*) n FROM history").fetchone()["n"]
            media=con.execute("SELECT COUNT(*) n FROM media_apps").fetchone()["n"]
            orders=con.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
        await q.edit_message_text(f"📊 Статистика\nКандидаты: {candidates}\nТесты: {tests}\nЗаявки медиа: {media}\nЗаказы: {orders}")
    elif data in ("adm:views","adm:followers","adm:knowledge","adm:product"):
        action=data.split(":")[1]; context.user_data["admin_action"]=action
        prompts={"views":"Введите новый минимум просмотров:","followers":"Введите новый минимум подписчиков:",
                 "knowledge":"Отправьте: вопрос | ответ","product":"Отправьте: название | описание | цена"}
        await q.edit_message_text(prompts[action])
    elif data=="adm:settings":
        await q.edit_message_text(
            f"⚙️ Текущие настройки\nВопросов: {setting('question_count',20)}\n"
            f"Время: {setting('test_seconds',300)} сек.\nПроходной балл: {setting('pass_score',13)}\n"
            f"Подготовка: {setting('prep_minutes',5)} мин.\nКД: {setting('cooldown_hours',72)} ч.\n\n"
            "Изменение этих значений пока выполняется через переменные окружения Render.")

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    if q.data.startswith("prepanswer:"):
        await prep_answer(update,context); return
    if q.data.startswith("adm:"):
        await q.answer(); await admin_callback(q,context); return
    if q.data.startswith("media_review:"):
        await q.answer(); await review_media(q,context); return
    if q.data.startswith("answer:") or q.data.startswith(("choose:","org:","back:","prep:","media:","help:","shop:","order:")):
        await callback(update,context); return
    await q.answer()

async def post_init(app):
    log.info("Telegram bot started")

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    init_db()
    threading.Thread(target=run_web,daemon=True).start()
    app=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("admin",admin_cmd))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.PHOTO,receive_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,receive_text))
    log.info("Starting polling")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    main()
