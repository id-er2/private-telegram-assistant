

from __future__ import annotations

import json
import logging
import requests

from config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    SYSTEM_PROMPT,
    MAX_RESPONSE_TOKENS,
    CONTEXT_WINDOW,
)
from memory import AdvancedMemory
from owner_state import OwnerState
from tools_knowledge import lookup_tool

logger = logging.getLogger(__name__)


class MRRobotAgent:
    """Ollama chat with local conversation memory and saved owner context."""

    def __init__(self) -> None:
        self.memory = AdvancedMemory()
        self.owner  = OwnerState()
        self._api_url = f"{OLLAMA_BASE_URL}/api/chat"
        self._warned_broken = False
        logger.info("Agent initialized with model: %s", OLLAMA_MODEL)

    def _payload(self, messages: list[dict], stream: bool) -> dict:
        system = SYSTEM_PROMPT
        owner_ctx = self.owner.context_block()
        if owner_ctx:
            system = f"{SYSTEM_PROMPT}\n\n{owner_ctx}"
        return {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                *messages,
            ],
            "stream": stream,
            "options": {
                "num_predict": MAX_RESPONSE_TOKENS,
                "temperature": 0.7,
                "top_p": 0.9,
            },
        }

    def _call_ollama(self, messages: list[dict]) -> str:
        try:
            response = requests.post(
                self._api_url,
                json=self._payload(messages, stream=False),
                timeout=180,
            )
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"].strip()

        except requests.exceptions.ConnectionError:
            logger.error("Cannot connect to Ollama at %s", OLLAMA_BASE_URL)
            return "⚠️ تعذّر الاتصال بـ Ollama. تأكد أن الخدمة تعمل على المنفذ 11434."
        except requests.exceptions.Timeout:
            logger.error("Ollama request timed out")
            return "⚠️ انتهت مهلة الطلب. النموذج بطيء أو المدخل كبير جداً."
        except requests.exceptions.HTTPError as exc:
            logger.error("Ollama HTTP error: %s", exc)
            return f"⚠️ خطأ من Ollama: {exc.response.status_code}"
        except (KeyError, json.JSONDecodeError) as exc:
            logger.error("Unexpected Ollama response format: %s", exc)
            return "⚠️ ردّ غير متوقع من النموذج. حاول مجدداً."
        except Exception as exc:
            logger.exception("Unexpected error calling Ollama: %s", exc)
            return "⚠️ حدث خطأ غير متوقع. حاول مجدداً."

    def _stream_ollama(self, messages: list[dict]):
        try:
            with requests.post(
                self._api_url,
                json=self._payload(messages, stream=True),
                timeout=(10, 300),
                stream=True,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break

        except requests.exceptions.ConnectionError:
            logger.error("Cannot connect to Ollama at %s", OLLAMA_BASE_URL)
            yield "⚠️ تعذّر الاتصال بـ Ollama. تأكد أن الخدمة تعمل على المنفذ 11434."
        except requests.exceptions.Timeout:
            logger.error("Ollama request timed out")
            yield "⚠️ انتهت مهلة الطلب. النموذج بطيء أو المدخل كبير جداً."
        except requests.exceptions.HTTPError as exc:
            logger.error("Ollama HTTP error: %s", exc)
            yield f"⚠️ خطأ من Ollama: {exc.response.status_code}"
        except Exception as exc:
            logger.exception("Unexpected error calling Ollama: %s", exc)
            yield "⚠️ حدث خطأ غير متوقع. حاول مجدداً."

    def chat(self, user_message: str) -> str:
        """Return a complete reply without streaming."""
        if not user_message or not user_message.strip():
            return "⚠️ لم تكتب شيئاً يا قائدي!"

        tool_reply = lookup_tool(user_message.strip().lower())
        if tool_reply:
            saved = self._record_exchange(user_message, tool_reply)
            return self._broken_warning_once() + tool_reply + ("" if saved else self._SAVE_WARN)

        self.memory.add_message("user", user_message)
        reply = self._call_ollama(self.memory.get_recent(CONTEXT_WINDOW))
        self.memory.add_message("assistant", reply)
        saved = self.memory.force_save()
        return self._broken_warning_once() + reply + ("" if saved else self._SAVE_WARN)

    def chat_stream(self, user_message: str):
        """Yield response chunks as the model produces them."""
        if not user_message or not user_message.strip():
            yield "⚠️ لم تكتب شيئاً يا قائدي!"
            return

        warn = self._broken_warning_once()
        if warn:
            yield warn

        tool_reply = lookup_tool(user_message.strip().lower())
        if tool_reply:
            saved = self._record_exchange(user_message, tool_reply)
            yield tool_reply
            if not saved:
                yield self._SAVE_WARN
            return

        self.memory.add_message("user", user_message)
        context = self.memory.get_recent(CONTEXT_WINDOW)

        accumulated = ""
        for token in self._stream_ollama(context):
            accumulated += token
            yield token

        if accumulated.strip():
            self.memory.add_message("assistant", accumulated.strip())
            if not self.memory.force_save():
                yield self._SAVE_WARN

    _SAVE_WARN = ("\n\n⚠️ تنبيه: الرد كامل فوق، لكن ما قدرت أحفظ المحادثة "
                  "على القرص — قد تضيع لو قفلت البوت.")
    _BROKEN_WARN = ("⚠️ ملف الذاكرة تالف — أشتغل معك عادي، لكن المحادثة "
                    "ما تنحفظ لين يتصلح الملف.\n\n")

    def _broken_warning_once(self) -> str:
        if self.memory.broken and not self._warned_broken:
            self._warned_broken = True
            return self._BROKEN_WARN
        return ""

    def _record_exchange(self, user_message: str, reply: str) -> bool:
        self.memory.add_message("user", user_message)
        self.memory.add_message("assistant", reply)
        return self.memory.force_save()

    def clear_memory(self) -> str:
        """Clear conversation history without deleting saved facts or labs."""
        try:
            self.memory.clear()
        except OSError:
            logger.error("Memory clear failed")
            return ("❌ ما قدرت أمسح سجل المحادثة — فشل الحفظ على القرص "
                    "أو ملف الذاكرة تالف. السجل القديم باقٍ كما هو.")
        return "🗑️ تم مسح سجل المحادثة يا قائدي."

    def memory_stats(self) -> str:
        return (
            f"📊 إحصائيات الذاكرة:\n"
            f"  • النموذج: {OLLAMA_MODEL}\n"
            f"  • إجمالي الرسائل المحفوظة: {self.memory.total_messages}\n"
            f"  • نافذة السياق: {CONTEXT_WINDOW} رسائل\n"
            f"  • الحد الأقصى للرد: {MAX_RESPONSE_TOKENS} توكن"
        )

    def shutdown(self) -> None:
        """Flush pending conversation writes."""
        self.memory.force_save()
        logger.info("Agent shut down cleanly.")
