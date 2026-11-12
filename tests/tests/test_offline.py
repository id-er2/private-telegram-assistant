

import asyncio
import io
import json
import logging
import os
import sys
import tempfile
import threading
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:AAE" + "x" * 32)
os.environ.setdefault("AUTHORIZED_USER_ID", "555")

FAKE_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


def _stub_missing():
    try:
        import dotenv
    except ImportError:
        m = types.ModuleType("dotenv")
        m.load_dotenv = lambda *a, **k: None
        sys.modules["dotenv"] = m
    try:
        import requests
    except ImportError:
        m = types.ModuleType("requests")
        class Exc(Exception):
            pass
        m.exceptions = types.SimpleNamespace(
            ConnectionError=type("ConnectionError", (Exc,), {}),
            Timeout=type("Timeout", (Exc,), {}),
            HTTPError=type("HTTPError", (Exc,), {}))
        m.post = lambda *a, **k: None
        sys.modules["requests"] = m
    try:
        import telegram
    except ImportError:
        tg = types.ModuleType("telegram")
        tg.Update = type("Update", (), {})
        tg.InlineKeyboardButton = type("B", (), {"__init__": lambda s, *a, **k: None})
        tg.InlineKeyboardMarkup = type("M", (), {"__init__": lambda s, *a, **k: None})
        ext = types.ModuleType("telegram.ext")
        class _F:
            def __and__(s, o): return s
            def __invert__(s): return s
        ext.Application = type("A", (), {"builder": staticmethod(lambda: types.SimpleNamespace(
            token=lambda s, t: s, post_shutdown=lambda s, f: s,
            build=lambda s: types.SimpleNamespace(add_handler=lambda h: None, run_polling=lambda: None)))})
        ext.CommandHandler = ext.MessageHandler = ext.CallbackQueryHandler = type(
            "H", (), {"__init__": lambda s, *a, **k: None})
        ext.filters = types.SimpleNamespace(TEXT=_F(), COMMAND=_F())
        ext.ContextTypes = type("C", (), {"DEFAULT_TYPE": object()})
        sys.modules["telegram"] = tg
        sys.modules["telegram.ext"] = ext


_stub_missing()

import config
import memory as memory_mod
import owner_state
import agent as agent_mod
import main as main_mod


def run(coro):
    return asyncio.run(coro)


class _TmpDirMixin:
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.mkdtemp()
        os.chdir(self._tmp)

    def tearDown(self):
        os.chdir(self._cwd)


class TestArabicParsing(unittest.TestCase):
    def test_remember_prefixes_no_corruption(self):
        from owner_state import parse_remember, parse_forget
        self.assertEqual(parse_remember("تذكر إن اسمي محمود"), "اسمي محمود")
        self.assertEqual(parse_remember("تذكر أن اسمي محمود"), "اسمي محمود")
        self.assertEqual(parse_remember("تذكر أني أحب القهوة"), "أني أحب القهوة")
        self.assertIsNone(parse_remember("وش تتذكر من اللاب؟"))
        self.assertEqual(parse_forget("انسَ إن جامعته"), "جامعته")
        self.assertEqual(parse_forget("انسى محمود"), "محمود")


class TestChunking(unittest.TestCase):
    def test_utf16_limits_with_emoji(self):
        s = "🔥" * 3000 + "نص عربي " * 800
        chunks = main_mod._chunk_text(s)
        self.assertEqual("".join(chunks), s)
        for c in chunks:
            self.assertLessEqual(main_mod._utf16_len(c), config.TELEGRAM_MSG_LIMIT)
        self.assertGreater(len(chunks), 1)


class TestOwnerState(_TmpDirMixin, unittest.TestCase):
    def test_remember_forget_profile(self):
        o = owner_state.OwnerState("owner_state.json")
        self.assertIn("حفظتها", o.remember("يدرس الأمن السيبراني"))
        self.assertIn("من قبل", o.remember("يدرس الأمن السيبراني"))
        o.remember("جامعته KFUPM")
        self.assertIn("KFUPM", o.profile_text())
        self.assertIn("نسيت", o.forget("KFUPM"))
        self.assertNotIn("KFUPM", o.profile_text())

    def test_save_failure_rolls_back(self):
        o = owner_state.OwnerState("owner_state.json")
        o.remember("أول معلومة")
        orig = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            r = o.remember("ثانية")
        finally:
            os.replace = orig
        self.assertEqual(r, owner_state.OwnerState.SAVE_FAIL_MSG)
        self.assertEqual(o.facts(), ["أول معلومة"])

    def test_corrupt_file_fail_closed(self):
        with open("owner_state.json", "w", encoding="utf-8") as f:
            f.write("not json {{{")
        o = owner_state.OwnerState("owner_state.json")
        self.assertEqual(o.remember("أي شي"), owner_state.OwnerState.BROKEN_MSG)
        with open("owner_state.json", encoding="utf-8") as f:
            self.assertEqual(f.read(), "not json {{{")

    def test_invalid_schema_fail_closed(self):
        with open("owner_state.json", "w", encoding="utf-8") as f:
            json.dump({"facts": ["ok", 123]}, f)
        o = owner_state.OwnerState("owner_state.json")
        self.assertTrue(o._broken)
        with open("owner_state.json", "w", encoding="utf-8") as f:
            json.dump({"facts": [], "lab": {"notes": "نص-مو-قائمة"}}, f)
        o = owner_state.OwnerState("owner_state.json")
        self.assertTrue(o._broken)

    def test_lab_archive_history_delete(self):
        o = owner_state.OwnerState("owner_state.json")
        o.lab_start("Lame", "10.10.10.3")
        o.lab_note("nmap: 21/22/80")
        self.assertIn("أنهِه أولاً", o.lab_start("Blue"))
        self.assertIn("أرشفت", o.lab_replace("Blue"))
        o.lab_end("طلعنا root")
        hist = o.lab_history_text()
        self.assertIn("Lame", hist)
        self.assertIn("root", hist)
        o2 = owner_state.OwnerState("owner_state.json")
        archived = {l["name"]: l for l in o2._data["completed_labs"]}
        self.assertEqual(archived["Lame"]["notes"], ["nmap: 21/22/80"])
        self.assertIn("حذفت", o2.delete_archived_lab("Lame"))
        self.assertNotIn("Lame", o2.lab_history_text())


class TestMemoryFormats(_TmpDirMixin, unittest.TestCase):
    def _reload(self):
        import importlib
        return importlib.reload(memory_mod)

    def test_new_format(self):
        with open("memory.json", "w", encoding="utf-8") as f:
            json.dump({"conversations": [{"role": "user", "content": "هلا"},
                                         {"role": "assistant", "content": "أهلين"}],
                       "total_messages": 2}, f)
        m = self._reload().AdvancedMemory()
        self.assertEqual(m.get_stats()["conversations"], 2)
        self.assertFalse(m.broken)

    def test_old_format_migration(self):
        with open("memory.json", "w", encoding="utf-8") as f:
            json.dump({"conversations": [{"time": "2026-05-01", "user": "سؤال", "bot": "جواب"}],
                       "summaries": ["ملخص قديم"], "targets": ["t1"]}, f)
        m = self._reload().AdvancedMemory()
        conv = m._data["conversations"]
        self.assertEqual(conv, [{"role": "user", "content": "سؤال"},
                                {"role": "assistant", "content": "جواب"}])
        self.assertEqual(m._data.get("summaries"), ["ملخص قديم"])
        self.assertEqual(m._data["total_messages"], 2)
        m.force_save()
        with open("memory.json", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["summaries"], ["ملخص قديم"])
        self.assertEqual(saved["conversations"][0]["role"], "user")

    def test_invalid_entries_dropped_not_fabricated(self):
        with open("memory.json", "w", encoding="utf-8") as f:
            json.dump({"conversations": [{"role": "hacker", "content": "x"},
                                         {"role": "user"}, "نص عاري",
                                         {"role": "user", "content": "سليم"}]}, f)
        m = self._reload().AdvancedMemory()
        self.assertEqual(m._data["conversations"],
                         [{"role": "user", "content": "سليم"}])

    def test_corrupt_fail_closed(self):
        with open("memory.json", "w", encoding="utf-8") as f:
            f.write("{{{{")
        m = self._reload().AdvancedMemory()
        self.assertTrue(m.broken)
        with self.assertRaises(OSError):
            m.clear()
        m.force_save()
        m.add_message("user", "لن تُحفظ")
        m.force_save()
        with open("memory.json", encoding="utf-8") as f:
            self.assertEqual(f.read(), "{{{{")

    def test_disk_full_honest_clear(self):
        m = self._reload().AdvancedMemory()
        m.add_message("user", "س")
        orig = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            with self.assertRaises(OSError):
                m.clear()
        finally:
            os.replace = orig


class TestTokenScrub(unittest.TestCase):
    def test_all_forms(self):
        stream = io.StringIO()
        h = logging.StreamHandler(stream)
        h.setFormatter(config.ScrubbingFormatter("%(levelname)s %(message)s"))
        h.addFilter(config.TokenScrubFilter())
        log = logging.getLogger("scrub_test")
        log.setLevel(logging.INFO)
        log.addHandler(h)
        log.propagate = False
        log.info("GET https://api.telegram.org/bot%s/getMe", FAKE_TOKEN)
        try:
            raise ValueError(f"token was {FAKE_TOKEN}")
        except ValueError:
            log.exception("boom")
        log.info("leak bot987654321:AAH%s/send", "y" * 32)
        out = stream.getvalue()
        self.assertNotIn(FAKE_TOKEN, out)
        self.assertNotIn("987654321:AAH" + "y" * 32, out)
        self.assertGreaterEqual(out.count("[REDACTED]"), 3)


class TestGateAndHandler(_TmpDirMixin, unittest.TestCase):
    class SentLog:
        replies = []
        edits = []

    class FakeSentMessage:
        def __init__(self, text): self.text = text
        async def edit_text(self, text, **k):
            TestGateAndHandler.SentLog.edits.append(text)
            self.text = text

    class FakeMessage:
        def __init__(self, text=""): self.text = text
        async def reply_text(self, text, **k):
            TestGateAndHandler.SentLog.replies.append(text)
            return TestGateAndHandler.FakeSentMessage(text)

    class FakeUpdate:
        def __init__(self, text="", uid=555, ctype="private"):
            self.effective_user = types.SimpleNamespace(id=uid)
            self.effective_chat = types.SimpleNamespace(id=1, type=ctype)
            self.message = TestGateAndHandler.FakeMessage(text)

    class FakeContext:
        def __init__(self, args=None):
            self.bot = types.SimpleNamespace(
                send_chat_action=lambda **k: asyncio.sleep(0))
            self.args = args or []

    def setUp(self):
        super().setUp()
        TestGateAndHandler.SentLog.replies = []
        TestGateAndHandler.SentLog.edits = []

    def test_group_and_stranger_silence(self):
        run(main_mod.handle_message(self.FakeUpdate("هلا", uid=555, ctype="group"), self.FakeContext()))
        run(main_mod.handle_message(self.FakeUpdate("هلا", uid=999), self.FakeContext()))
        run(main_mod.start(self.FakeUpdate(uid=555, ctype="group"), self.FakeContext()))
        self.assertEqual(self.SentLog.replies, [])

    def test_streaming_threadsafe_and_complete(self):
        toks = ["تحليل ", "المنافذ ", "يعطي ", "22 مفتوح"]
        main_mod.agent.chat_stream = lambda text: iter(toks)
        put_threads = set()
        orig = asyncio.Queue.put_nowait
        tid = threading.get_ident()

        def spy(self, item):
            put_threads.add(threading.get_ident())
            return orig(self, item)

        asyncio.Queue.put_nowait = spy
        try:
            run(main_mod.handle_message(self.FakeUpdate("حلل"), self.FakeContext()))
        finally:
            asyncio.Queue.put_nowait = orig
        self.assertEqual(self.SentLog.edits[-1], "".join(toks))
        self.assertEqual(put_threads, {tid})

    def test_producer_error_honest_fallback(self):
        def boom(text):
            yield "جزء "
            raise RuntimeError("ollama died")
        main_mod.agent.chat_stream = boom
        run(main_mod.handle_message(self.FakeUpdate("اختبار"), self.FakeContext()))
        self.assertTrue(any("صار خطأ" in e for e in self.SentLog.edits))

    def test_clear_truthful(self):
        ag = agent_mod.MRRobotAgent()
        main_mod.agent = ag
        run(main_mod.clear_command(self.FakeUpdate(), self.FakeContext()))
        self.assertIn("سجل المحادثة فقط", self.SentLog.replies[0])

    def test_lab_forget_command_route(self):
        ag = agent_mod.MRRobotAgent()
        main_mod.agent = ag
        ag.owner.lab_start("Lame")
        ag.owner.lab_end("تم")
        run(main_mod.lab_command(self.FakeUpdate(), self.FakeContext(args=["forget", "Lame"])))
        self.assertIn("حذفت", self.SentLog.replies[-1])


class _FakeStreamResp:
    def __init__(self, tokens):
        self._lines = [json.dumps({"message": {"content": t}}) for t in tokens]
        self._lines.append(json.dumps({"done": True}))
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def raise_for_status(self): pass
    def iter_lines(self, decode_unicode=False): return iter(self._lines)


class TestAgentPayload(_TmpDirMixin, unittest.TestCase):
    def _patched_post(self, calls, tokens=("رد ", "تجريبي")):
        def fake_post(url, json=None, timeout=None, stream=False):
            calls.append(json)
            return _FakeStreamResp(list(tokens))
        self._orig_post = agent_mod.requests.post
        agent_mod.requests.post = fake_post

    def tearDown(self):
        super().tearDown()
        if hasattr(self, "_orig_post"):
            agent_mod.requests.post = self._orig_post

    def test_owner_facts_and_lab_injected(self):
        calls = []
        self._patched_post(calls)
        ag = agent_mod.MRRobotAgent()
        ag.owner.remember("يحب الشرح بالتلميحات")
        ag.owner.lab_start("Blue", "10.10.10.40")
        ag.owner.lab_note("gobuster طلع /hidden")
        out = "".join(ag.chat_stream("وش الخطوة الجاية؟"))
        sysmsg = calls[0]["messages"][0]["content"]
        self.assertIn("يحب الشرح بالتلميحات", sysmsg)
        self.assertIn("Blue", sysmsg)
        self.assertIn("gobuster", sysmsg)
        self.assertEqual(out, "رد تجريبي")

    def test_no_generative_cache_context_change(self):
        """نفس السؤال مرتين = طلبان فعليان، والسياق الجديد يظهر في الثاني."""
        calls = []
        self._patched_post(calls)
        ag = agent_mod.MRRobotAgent()
        "".join(ag.chat_stream("وش أنسب خطوة؟"))
        ag.owner.remember("انتقل لتحدي XYZUNIQUE123")
        "".join(ag.chat_stream("وش أنسب خطوة؟"))
        self.assertEqual(len(calls), 2, "رد مولّد من كاش قديم")
        self.assertNotIn("XYZUNIQUE123", calls[0]["messages"][0]["content"])
        self.assertIn("XYZUNIQUE123", calls[1]["messages"][0]["content"])


class TestMemoryTruthfulness(_TmpDirMixin, unittest.TestCase):
    def test_clear_failure_rolls_back_ram_and_disk(self):
        ag = agent_mod.MRRobotAgent()
        ag.memory.add_message("user", "رسالة مهمة")
        ag.memory.force_save()
        with open("memory.json", encoding="utf-8") as f:
            disk_before = f.read()
        orig = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            msg = ag.clear_memory()
        finally:
            os.replace = orig
        self.assertIn("ما قدرت", msg)
        self.assertEqual(len(ag.memory.get_recent(10)), 1)
        with open("memory.json", encoding="utf-8") as f:
            self.assertEqual(f.read(), disk_before)

    def test_failed_save_warns_in_stream(self):
        calls = []
        TestAgentPayload._patched_post(self, calls)
        ag = agent_mod.MRRobotAgent()
        orig = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            out = "".join(ag.chat_stream("سؤال"))
        finally:
            os.replace = orig
            agent_mod.requests.post = self._orig_post
            del self._orig_post
        self.assertIn("رد تجريبي", out)
        self.assertIn("ما قدرت أحفظ", out)
        self.assertEqual(len(ag.memory.get_recent(10)), 2)

    def test_broken_memory_visible_warning(self):
        with open("memory.json", "w", encoding="utf-8") as f:
            f.write("{{{{")
        calls = []
        TestAgentPayload._patched_post(self, calls)
        ag = agent_mod.MRRobotAgent()
        out = "".join(ag.chat_stream("هلا"))
        self.assertIn("ملف الذاكرة تالف", out)
        self.assertFalse(ag.memory.broken is False)
        agent_mod.requests.post = self._orig_post
        del self._orig_post


if __name__ == "__main__":
    unittest.main(verbosity=2)
