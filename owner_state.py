

from __future__ import annotations

import json
import os
import re
import shutil
import logging
from datetime import datetime, timezone

from config import OWNER_STATE_FILE

logger = logging.getLogger(__name__)


_REMEMBER_RE = re.compile(
    r"^(?:تذكر|تذكّر|ذكّر)[\s:،\-]+(?:(?:إن|أن|ان)[\s:،\-]+)?", re.UNICODE)
_FORGET_RE = re.compile(
    r"^(?:انسَ|انسِ|انسى|نسي|انس)[\s:،\-]+(?:(?:إن|أن|ان|عن)[\s:،\-]+)?", re.UNICODE)


def parse_remember(text: str):
    """يرجع نص المعلومة إذا كانت الرسالة أمر «تذكر»، وإلا None."""
    m = _REMEMBER_RE.match(text.strip())
    return text.strip()[m.end():].strip() if m else None


def parse_forget(text: str):
    """يرجع الجزء المطلوب نسيانه إذا كانت الرسالة أمر «انسَ/انسى»، وإلا None."""
    m = _FORGET_RE.match(text.strip())
    return text.strip()[m.end():].strip() if m else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class OwnerState:
    """Store explicitly saved facts, the current lab, and completed labs."""

    BROKEN_MSG = (
        "⚠️ ملف الحفظ (owner_state.json) تالف أو غير مقروء. أوقفت الكتابة عليه "
        "حتى لا يضيع محتواه — راجعه يدوياً أو احذفه ثم أعد المحاولة."
    )
    SAVE_FAIL_MSG = (
        "❌ ما قدرت أحفظ على القرص (تحقق من الصلاحيات والمساحة). "
        "لم يُحفظ أي تغيير — أعد المحاولة بعد ما تحل المشكلة."
    )

    def __init__(self, path: str = OWNER_STATE_FILE) -> None:
        self._path = path
        self._data = {"facts": [], "lab": None, "completed_labs": []}
        self._broken = False
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Owner state unreadable (%s) — refusing writes.", exc)
            self._broken = True
            return

        if not isinstance(loaded, dict):
            self._broken = True
            return
        facts = loaded.get("facts", [])
        lab = loaded.get("lab")
        completed = loaded.get("completed_labs", [])

        def _valid_lab(entry) -> bool:
            return (
                isinstance(entry, dict)
                and isinstance(entry.get("name"), str)
                and isinstance(entry.get("notes", []), list)
                and all(isinstance(n, str) for n in entry.get("notes", []))
                and isinstance(entry.get("target", ""), str)
            )

        if (
            not isinstance(facts, list)
            or not all(isinstance(f, str) for f in facts)
            or (lab is not None and not _valid_lab(lab))
            or not isinstance(completed, list)
            or not all(_valid_lab(l) for l in completed)
        ):
            logger.warning("Owner state schema invalid — writes refused.")
            self._broken = True
            return
        self._data["facts"] = list(facts)
        self._data["lab"] = lab
        self._data["completed_labs"] = list(completed)

    def _save(self) -> None:
        """Save atomically, backing up an existing file before its first overwrite."""
        if self._broken:
            raise OSError("state file broken; writes refused")
        if os.path.exists(self._path) and not os.path.exists(self._path + ".bak"):
            shutil.copy2(self._path, self._path + ".bak")
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    def _mutate(self, apply_fn, success_msg: str) -> str:
        """Save a state change or roll back and report the failure."""
        if self._broken:
            return self.BROKEN_MSG
        snapshot = json.loads(json.dumps(self._data))
        try:
            apply_fn()
            self._save()
        except OSError as exc:
            self._data = snapshot
            logger.error("Owner state save failed: %s", exc)
            return self.SAVE_FAIL_MSG
        except Exception:
            self._data = snapshot
            raise
        return success_msg

    def remember(self, fact: str) -> str:
        fact = fact.strip()
        if not fact:
            return "⚠️ ما كتبت شي أتذكره. مثال: تذكر إن اسمي محمود"
        if fact in self._data["facts"]:
            return "ℹ️ هالمعلومة محفوظة عندي من قبل يا قائدي."
        return self._mutate(
            lambda: self._data["facts"].append(fact),
            f"✅ تمام، حفظتها: {fact}",
        )

    def forget(self, fragment: str) -> str:
        """يحذف كل معلومة تحتوي الجزء المحدد - التصحيح = احذف ثم أعد الحفظ."""
        fragment = fragment.strip()
        if not fragment:
            return "⚠️ وش الشي اللي تبي أنساه؟"
        if self._broken:
            return self.BROKEN_MSG
        removed = [f for f in self._data["facts"] if fragment in f]
        if not removed:
            return f"🔍 ما لقيت معلومة محفوظة فيها «{fragment}»."
        lines = "\n".join(f"  • {r}" for r in removed)
        return self._mutate(
            lambda: self._data["facts"].remove(removed[0]) if len(removed) == 1
                    else [self._data["facts"].remove(r) for r in removed],
            f"🗑️ نسيت هالمعلومات:\n{lines}",
        )

    def facts(self) -> list:
        return list(self._data["facts"])

    def lab_start(self, name: str, target: str = "") -> str:
        name = name.strip()
        if not name:
            return "⚠️ اكتب اسم اللاب. مثال: /lab start Lame HTB"
        if self._broken:
            return self.BROKEN_MSG
        active = self._data["lab"]
        if active:
            return (
                f"⚠️ عندك لاب شغال: «{active['name']}». "
                "أنهِه أولاً بـ /lab end أو استبدله صراحة بـ /lab replace — ما أمسحه من نفسي."
            )

        def apply():
            self._data["lab"] = {
                "name": name, "target": target.strip(),
                "started": _now(), "notes": [],
            }
        t = f" — الهدف: {target.strip()}" if target.strip() else ""
        return self._mutate(
            apply,
            f"🚩 بدأنا لاب «{name}»{t}. ارسل لي المخرجات وبتابع معك خطوة بخطوة.",
        )

    def lab_replace(self, name: str, target: str = "") -> str:
        """يستبدل اللاب الحالي صراحة: يؤرشف القديم بملاحظاته ثم يبدأ الجديد."""
        name = name.strip()
        if not name:
            return "⚠️ اكتب اسم اللاب الجديد. مثال: /lab replace Blue 10.10.10.40"
        if self._broken:
            return self.BROKEN_MSG
        old = self._data["lab"]

        def apply():
            if old:
                old["ended"] = _now()
                old["result"] = "(استُبدل بلاب آخر)"
                self._data["completed_labs"].append(old)
            self._data["lab"] = {
                "name": name, "target": target.strip(),
                "started": _now(), "notes": [],
            }
        if old:
            msg = (f"📦 أرشفت «{old['name']}» بملاحظاته ({len(old.get('notes', []))}).\n"
                   f"🚩 بدأنا لاب «{name}».")
        else:
            msg = f"🚩 بدأنا لاب «{name}»."
        return self._mutate(apply, msg)

    def lab_note(self, note: str) -> str:
        if self._broken:
            return self.BROKEN_MSG
        if not self._data["lab"]:
            return "⚠️ ما فيه لاب شغال. ابدأ واحد بـ /lab start"
        note = note.strip()
        if not note:
            return "⚠️ اكتب الملاحظة. مثال: /lab note جربت hydra وما نجح"

        def apply():
            self._data["lab"]["notes"].append(note)
        return self._mutate(
            apply,
            f"📝 سجلتها في ملف اللاب ({len(self._data['lab']['notes']) + 1} ملاحظة).",
        )

    def lab_end(self, result: str = "") -> str:
        """يغلق اللاب ويؤرشفه كاملاً بملاحظاته - لا يضيّع شيئاً."""
        if self._broken:
            return self.BROKEN_MSG
        if not self._data["lab"]:
            return "⚠️ ما فيه لاب شغال أصلاً."
        lab = self._data["lab"]

        def apply():
            lab["ended"] = _now()
            lab["result"] = result.strip()
            self._data["completed_labs"].append(lab)
            self._data["lab"] = None
        r = f"\nالنتيجة: {result.strip()}" if result.strip() else ""
        return self._mutate(
            apply,
            f"🏁 أغلقنا لاب «{lab['name']}» وانحفظ كاملاً في السجل.\n"
            f"📓 ملاحظاته: {len(lab.get('notes', []))}.{r}\n"
            "تشوفه وغيره بـ /lab history",
        )

    def lab_status(self):
        return self._data["lab"]

    def delete_archived_lab(self, fragment: str) -> str:
        """Delete matching archived labs; leave backup files for manual removal."""
        fragment = fragment.strip()
        if not fragment:
            return "⚠️ اكتب اسم اللاب المؤرشف. مثال: /lab forget Lame"
        if self._broken:
            return self.BROKEN_MSG
        matches = [l for l in self._data["completed_labs"] if fragment in l.get("name", "")]
        if not matches:
            return f"🔍 ما لقيت لاباً مؤرشفاً باسم «{fragment}»."
        names = [l.get("name", "?") for l in matches]

        def apply():
            self._data["completed_labs"] = [
                l for l in self._data["completed_labs"] if l not in matches
            ]
        return self._mutate(
            apply,
            "🗑️ حذفت من السجل: " + "، ".join(names) +
            "\nℹ️ ملفات النسخ الاحتياطي .bak لا تُحذف تلقائياً — احذفها يدوياً إذا تبي حذفاً كاملاً.",
        )

    def lab_history_text(self) -> str:
        completed = self._data["completed_labs"]
        if not completed:
            return "📦 ما عندك لابات مؤرشفة بعد."
        out = f"📦 سجل اللابات المكتملة ({len(completed)}):\n"
        for lab in completed[-10:]:
            line = f"\n🚩 {lab.get('name', '?')}"
            if lab.get("target"):
                line += f" — {lab['target']}"
            line += f"\n   📝 {len(lab.get('notes', []))} ملاحظة"
            if lab.get("result"):
                line += f"\n   🏁 {lab['result']}"
            out += line
        return out

    def context_block(self) -> str:
        """نص مختصر يُضاف لسياق النموذج - فقط ما هو محفوظ فعلاً، بلا اختراع."""
        parts = []
        if self._data["facts"]:
            lines = "\n".join(f"- {f}" for f in self._data["facts"][-15:])
            parts.append(f"معلومات محفوظة عن محمود (صاحبك الوحيد):\n{lines}")
        lab = self._data["lab"]
        if lab:
            block = f"اللاب الحالي: «{lab['name']}»"
            if lab.get("target"):
                block += f" — الهدف: {lab['target']}"
            notes = lab.get("notes", [])
            if notes:
                tail = "\n".join(f"- {n}" for n in notes[-10:])
                block += f"\nآخر ملاحظات اللاب:\n{tail}"
            parts.append(block)
        return "\n\n".join(parts)

    def profile_text(self) -> str:
        out = "👤 ملفك عندي يا قائدي:\n"
        if self._data["facts"]:
            out += "\n📌 معلومات محفوظة:\n" + "\n".join(
                f"  {i+1}. {f}" for i, f in enumerate(self._data["facts"])
            )
        else:
            out += "\n📌 ما عندي معلومات محفوظة عنك بعد. قل «تذكر إن ...» وأحفظها."
        lab = self._data["lab"]
        out += "\n"
        if lab:
            out += f"\n🚩 اللاب الحالي: {lab['name']}"
            if lab.get("target"):
                out += f" — {lab['target']}"
            out += f"\n📝 الملاحظات: {len(lab.get('notes', []))}"
        else:
            out += "\n🚩 ما فيه لاب شغال حالياً."
        done = len(self._data["completed_labs"])
        out += f"\n📦 لابات مؤرشفة: {done}"
        out += "\n\nللتصحيح: «انسَ ...» ثم «تذكر إن ...» من جديد."
        return out
