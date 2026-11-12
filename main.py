import logging
import asyncio
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from agent import MRRobotAgent
from tools_knowledge import TOOLS_KB, format_tool_info
from owner_state import parse_remember, parse_forget
from config import (
    TELEGRAM_BOT_TOKEN, AUTHORIZED_USER_ID, TELEGRAM_MSG_LIMIT,
    validate_config, BOT_NAME, LOG_FILE, setup_logging
)


setup_logging()
logger = logging.getLogger("MRRobot")
agent = MRRobotAgent()


def is_authorized(update: Update) -> bool:
    """Accept only the configured user in a private chat."""
    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return False
    if getattr(chat, "type", None) != "private":
        return False
    return user.id == AUTHORIZED_USER_ID


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _chunk_text(text: str, limit: int = TELEGRAM_MSG_LIMIT) -> list:
    """Split text within Telegram UTF-16 length limits."""
    chunks, current, cur_len = [], [], 0
    for ch in text:
        cl = _utf16_len(ch)
        if cur_len + cl > limit and current:
            chunks.append("".join(current))
            current, cur_len = [ch], cl
        else:
            current.append(ch)
            cur_len += cl
    if current:
        chunks.append("".join(current))
    return [c for c in chunks if c.strip()]


async def send_safe(update: Update, text: str, parse_mode=None):
    if not text:
        return
    for chunk in _chunk_text(text):
        try:
            await update.message.reply_text(chunk, parse_mode=parse_mode)
        except Exception:
            try:
                await update.message.reply_text(chunk)
            except Exception as e:
                logger.error("فشل إرسال: %s", e)


def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("💬 سولفني", callback_data="chat_mode")],
        [InlineKeyboardButton("📚 دليل الأدوات", callback_data="tools_guide"),
         InlineKeyboardButton("🔍 بحث عن أداة", callback_data="search_tool")],
        [InlineKeyboardButton("🧠 الذاكرة", callback_data="show_stats")],
    ]
    return InlineKeyboardMarkup(keyboard)


def tools_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🛡️ فحص الشبكات", callback_data="tcat_شبكات")],
        [InlineKeyboardButton("🌐 أمن تطبيقات الويب", callback_data="tcat_ويب")],
        [InlineKeyboardButton("📡 تحليل الشبكات", callback_data="tcat_تحليل")],
        [InlineKeyboardButton("🧾 التحليل الجنائي الرقمي", callback_data="tcat_جنائي")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def back_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    welcome = (
        "🤖 أهلاً يا قائدي! أنا MR.Robot\n\n"
        "مساعدك الشخصي ومدرّبك في الأمن السيبراني 🛡️\n\n"
        "💬 اكتب أي شي وبرد عليك\n"
        "🚩 /lab — نتابع لابك خطوة بخطوة\n"
        "👤 /profile — معلوماتك المحفوظة عندي\n"
        "📚 أو تصفح دليل الأدوات من القائمة 👇"
    )
    await update.message.reply_text(welcome, reply_markup=main_menu_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    help_text = (
        "📋 كيف تستخدم MR.Robot:\n\n"
        "💬 اكتب أي رسالة — وبرد عليك بذكاء\n"
        "🔧 اسأل عن أداة — مثل: 'ايش هو nmap؟'\n"
        "📚 /tools — تصفح دليل الأدوات\n"
        "🚩 /lab — متابعة اللاب الحالي (start / note / status / end / history)\n"
        "👤 /profile — ملفك ومعلوماتك المحفوظة\n"
        "💾 قل «تذكر إن ...» لأحفظ معلومة عنك، و«انسَ ...» لأحذفها\n"
        "🧠 /memory — الذاكرة والإحصائيات\n"
        "🗑️ /clear — مسح سجل المحادثة (معلوماتك واللابات تبقى)\n\n"
        "💡 أنا أفهم عربي ولا تحتاج أوامر محددة!"
    )
    await send_safe(update, help_text)


async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    text = "📚 دليل الأدوات السيبرانية\n\nاختر التصنيف 👇"
    await update.message.reply_text(text, reply_markup=tools_menu_keyboard())


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    stats = agent.memory.get_stats()
    resp = (
        "🧠 ذاكرة MR.Robot:\n\n"
        f"💬 المحادثات: {stats['conversations']}\n"
        f"📝 الملخصات: {stats['summaries']}\n"
    )
    await send_safe(update, resp)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    result = agent.clear_memory()
    await send_safe(
        update,
        result + "\n\nℹ️ هذا مسح سجل المحادثة فقط. معلوماتك المحفوظة واللابات "
                 "ما تمسحت — لحذف معلومة قل «انسَ ...»، ولإغلاق اللاب /lab end",
    )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await send_safe(update, agent.owner.profile_text())


async def lab_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    args = context.args or []
    if not args:
        await send_safe(
            update,
            "🚩 أوامر اللاب:\n"
            "/lab start <اسم اللاب> [الهدف]\n"
            "/lab replace <اسم اللاب> [الهدف] — يؤرشف الحالي ويبدأ جديداً\n"
            "/lab note <ملاحظة>\n"
            "/lab status\n"
            "/lab end [النتيجة]\n"
            "/lab history — سجل اللابات المكتملة\n"
            "/lab forget <الاسم> — حذف لاب مؤرشف من السجل",
        )
        return
    sub = args[0].lower()
    rest = " ".join(args[1:])
    if sub == "start":
        parts = rest.split(" ", 1)
        await send_safe(update, agent.owner.lab_start(
            parts[0] if parts else "", parts[1] if len(parts) > 1 else ""))
    elif sub == "replace":
        parts = rest.split(" ", 1)
        await send_safe(update, agent.owner.lab_replace(
            parts[0] if parts else "", parts[1] if len(parts) > 1 else ""))
    elif sub == "note":
        await send_safe(update, agent.owner.lab_note(rest))
    elif sub == "end":
        await send_safe(update, agent.owner.lab_end(rest))
    elif sub == "forget":
        await send_safe(update, agent.owner.delete_archived_lab(rest))
    elif sub == "history":
        await send_safe(update, agent.owner.lab_history_text())
    elif sub == "status":
        lab = agent.owner.lab_status()
        if lab:
            notes = lab.get("notes", [])
            text = f"🚩 اللاب الحالي: {lab['name']}"
            if lab.get("target"):
                text += f" — {lab['target']}"
            text += f"\n📝 الملاحظات ({len(notes)}):"
            for n in notes[-10:]:
                text += f"\n  • {n}"
            await send_safe(update, text)
        else:
            await send_safe(update, "ما فيه لاب شغال. ابدأ واحد بـ /lab start")
    else:
        await send_safe(update, "⚠️ أمر غير معروف. جرّب: start / replace / note / status / end / history")


TCAT_MAP = {
    "tcat_شبكات":   "فحص الشبكات",
    "tcat_ويب":     "أمن تطبيقات الويب",
    "tcat_تحليل":   "تحليل الشبكات",
    "tcat_جنائي":   "التحليل الجنائي الرقمي",
}


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        return

    data = query.data

    if data == "main_menu":
        await query.edit_message_text(
            "🤖 MR.Robot — القائمة الرئيسية\n\nاختر يا قائدي 👇",
            reply_markup=main_menu_keyboard()
        )
        return

    if data == "chat_mode":
        await query.edit_message_text(
            "💬 وضع المحادثة\n\n"
            "اكتب أي شي يا قائدي وبرد عليك! 🤖\n"
            "اسألني عن أي أداة أو موضوع في الأمن السيبراني.",
            reply_markup=back_button()
        )
        return

    if data == "tools_guide":
        await query.edit_message_text(
            "📚 دليل الأدوات السيبرانية\n\n"
            "اختر التصنيف اللي يهمك 👇",
            reply_markup=tools_menu_keyboard()
        )
        return

    if data == "search_tool":
        await query.edit_message_text(
            "🔍 بحث عن أداة\n\n"
            "اكتب اسم أداة أمنية معروفة لعرض تعريف عام مختصر عنها.\n"
            "مثال: nmap أو Burp Suite أو Wireshark",
            reply_markup=back_button()
        )
        return

    if data == "show_stats":
        stats = agent.memory.get_stats()
        text = (
            "🧠 إحصائيات MR.Robot:\n\n"
            f"💬 محادثات: {stats['conversations']}\n"
            f"📝 ملخصات: {stats['summaries']}\n"
            f"📚 أدوات في قاعدة المعرفة: {len(TOOLS_KB)}\n"
        )
        await query.edit_message_text(text, reply_markup=back_button())
        return

    if data in TCAT_MAP:
        cat_name = TCAT_MAP[data]
        tools = [v for v in TOOLS_KB.values() if cat_name in v["cat"]]
        text = f"📁 {cat_name}\n\n"
        for t in tools:
            text += f"🔧 {t['name']} — {t['desc'][:80]}...\n"
            text += f"   📊 المستوى: {t['level']}\n\n"
        text += "💡 اكتب اسم أداة لعرض تعريف عام مختصر عنها"
        await query.edit_message_text(text, reply_markup=back_button())
        return


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    user_text = update.message.text
    if not user_text or not user_text.strip():
        return

    fact = parse_remember(user_text)
    if fact is not None:
        await send_safe(update, agent.owner.remember(fact))
        return
    fragment = parse_forget(user_text)
    if fragment is not None:
        await send_safe(update, agent.owner.forget(fragment))
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )
    sent_msg = await update.message.reply_text("⏳ جاري التفكير...")

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    # requests is blocking, so generation runs outside the event loop.
    def _produce():
        """Read the blocking stream in a worker; queue updates on the event loop."""
        try:
            for token in agent.chat_stream(user_text):
                loop.call_soon_threadsafe(queue.put_nowait, token)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    producer = loop.run_in_executor(None, _produce)

    accumulated = ""
    last_edit_len = 0
    last_edit_time = 0.0
    EDIT_EVERY = 40
    EDIT_MIN_INTERVAL = 0.8

    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            accumulated += item

            now = time.monotonic()
            if (len(accumulated) - last_edit_len) >= EDIT_EVERY and\
               (now - last_edit_time) >= EDIT_MIN_INTERVAL:
                try:
                    await sent_msg.edit_text(_chunk_text(accumulated)[0])
                    last_edit_len = len(accumulated)
                    last_edit_time = now
                except Exception:
                    pass
    except asyncio.CancelledError:
        # Cancelling the future does not stop an in-flight requests call.
        producer.cancel()
        raise
    except Exception as e:
        producer.cancel()
        logger.error("خطأ في معالجة الرسالة: %s", e)
        fallback = "❌ صار خطأ وأنا أجهّز الرد. جرّب مرة ثانية يا قائدي."
        try:
            await sent_msg.edit_text(fallback)
        except Exception:
            await send_safe(update, fallback)
        return

    if not accumulated.strip():
        try:
            await sent_msg.edit_text(
                "⚠️ ما وصلني رد من النموذج. تأكد أن Ollama شغال وجرب مرة ثانية."
            )
        except Exception:
            pass
        return

    chunks = _chunk_text(accumulated)
    try:
        await sent_msg.edit_text(chunks[0])
    except Exception:
        await send_safe(update, chunks[0])
    for chunk in chunks[1:]:
        await send_safe(update, chunk)


async def _post_shutdown(app) -> None:
    """Flush memory on a clean application shutdown."""
    agent.shutdown()


def _ensure_event_loop() -> None:
    """Create a loop when needed by python-telegram-bot on newer Python versions."""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def main():
    if not validate_config():
        print("❌ فشل التحقق من الإعدادات. راجع ملف .env")
        return

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tools", tools_command))
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("lab", lab_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 MR.Robot Bot يعمل الآن!")
    _ensure_event_loop()
    app.run_polling()


if __name__ == '__main__':
    main()
