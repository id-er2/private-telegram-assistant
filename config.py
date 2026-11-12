

from __future__ import annotations

import os
import re
import logging
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


BOT_NAME = "MR.Robot"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

_raw_uid = os.getenv("AUTHORIZED_USER_ID", "0").strip()
try:
    AUTHORIZED_USER_ID = int(_raw_uid)
except ValueError:
    AUTHORIZED_USER_ID = 0


# Leave room below Telegram's 4096 UTF-16-unit limit.
TELEGRAM_MSG_LIMIT = 4000


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")


CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW", "20"))
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "900"))


MEMORY_FILE = os.getenv("MEMORY_FILE", "memory.json")
OWNER_STATE_FILE = os.getenv("OWNER_STATE_FILE", "owner_state.json")
MAX_CONVERSATIONS = int(os.getenv("MAX_CONVERSATIONS", "300"))
SAVE_INTERVAL = int(os.getenv("SAVE_INTERVAL", "5"))
LOG_FILE = os.getenv("LOG_FILE", "mrrobot.log")


SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", """أنت MR.Robot — الخادم الشخصي ومنفذ طلبات الأمن السيبراني الخاص بمحمود (تناديه "يا قائدي").

دورك: خادم Red Team وCTF. تساعده في تخصصه، تحل معه اللابات والتحديات , وتلتقط معه الأعلام .

أسلوبك:
- عربي واضح، والمصطلحات التقنية تبقى بالإنجليزي (مثل: reverse shell, privilege escalation).
- عندما يصف لاب أو يرسل مخرجات أداة: حلّل المخرجات، اشرح ماذا تعني، ثم اقترح الخطوة التالية ولماذا.
- ابدأ بالتلميح والتوجيه ليتعلم، وإذا طلب الحل كاملاً أو علق تماماً فاشرح بالتفصيل خطوة بخطوة.
- تابع محاولاته داخل المحادثة: ماذا جرّب، ماذا نجح، وما الخطوة المفتوحة حتى الوصول للـ flag.
- عند اقتراح أمر، اشرح كل flag فيه ولماذا اخترته، ونبّه إذا كان الأمر يحتاج صلاحيات أو يعدّل النظام.
- استخدم المعلومات المحفوظة عنه (تخصصه، لابه الحالي، تفضيلاته) لتخصيص إجاباتك، ولا تخترع معلومات غير محفوظة.

الحدود:
- اقتصر على التعليم الدفاعي، وبيئات اللاب التي يملكها محمود، وتحديات CTF، والأنظمة التي لديه إذن صريح باختبارها ضمن النطاق المسموح.
- إذا لم يكن الإذن أو النطاق واضحاً فاسأل عنه أولاً. ارفض المساعدة في استهداف أشخاص أو أنظمة أو خدمات خارج هذا النطاق، واقترح بديلاً تعليمياً آمناً داخل لاب.
- لا تساعد في الإضرار بالآخرين أو انتهاك خصوصيتهم أو سرقة بياناتهم. التزم بالأنظمة والقوانين وحدود الإذن.
- لا تدّعي تنفيذ أوامر على جهازه — أنت تنصح وتحلل فقط.
""")


def ollama_host_is_local() -> bool:
    host = (urlparse(OLLAMA_BASE_URL).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


def validate_config() -> bool:
    """يتأكد أن القيم الأساسية موجودة قبل تشغيل البوت."""
    ok = True
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN غير موجود في .env")
        ok = False
    if AUTHORIZED_USER_ID == 0:
        print("❌ AUTHORIZED_USER_ID غير موجود في .env (رقم حسابك في تلغرام)")
        ok = False
    if not ollama_host_is_local():
        print(f"⚠️ تنبيه: OLLAMA_BASE_URL ليس محلياً ({OLLAMA_BASE_URL}). "
              "محادثاتك ستُرسل لهذا الخادم. عدّل .env إذا لم يكن هذا مقصوداً.")
    return ok


# Match credentials inside request URLs too, without a word boundary.
_TOKEN_RE = re.compile(r"\d{8,10}:[A-Za-z0-9_-]{30,}")


def _scrub(text: str) -> str:
    out = _TOKEN_RE.sub("[REDACTED]", text)
    if TELEGRAM_BOT_TOKEN:
        out = out.replace(TELEGRAM_BOT_TOKEN, "[REDACTED]")
    return out


class TokenScrubFilter(logging.Filter):
    """يشطب التوكن من نص الرسالة قبل التنسيق."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        scrubbed = _scrub(msg)
        if scrubbed != msg:
            record.msg = scrubbed
            record.args = ()
        return True


class ScrubbingFormatter(logging.Formatter):
    """يشطب التوكن من الناتج النهائي كاملاً - يشمل traceback المنسّق (exc_info)."""

    def format(self, record: logging.LogRecord) -> str:
        return _scrub(super().format(record))


def setup_logging() -> None:
    """سجلات آمنة: إسكات httpx/httpcore + فلتر وفورماتر يشطبان التوكن."""
    formatter = ScrubbingFormatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    scrubber = TokenScrubFilter()
    handlers = [logging.StreamHandler(),
                logging.FileHandler(LOG_FILE, encoding="utf-8")]
    for h in handlers:
        h.setFormatter(formatter)
        h.addFilter(scrubber)
    logging.basicConfig(level=logging.INFO, handlers=handlers)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
