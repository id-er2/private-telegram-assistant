

from __future__ import annotations

import json
import os
import shutil
import logging
from typing import Any

from config import MEMORY_FILE, MAX_CONVERSATIONS, SAVE_INTERVAL

logger = logging.getLogger(__name__)

_VALID_ROLES = {"user", "assistant", "system"}


class AdvancedMemory:
    """Store chat history as JSON, with backups and atomic file replacement."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {"conversations": [], "total_messages": 0}
        self._msg_counter: int = 0
        self._broken: bool = False
        self._load()

    @staticmethod
    def _migrate_conversations(raw: list) -> list:
        """Read current or legacy history entries; warn and drop invalid entries."""
        out = []
        dropped = 0
        for entry in raw:
            if not isinstance(entry, dict):
                dropped += 1
                continue
            if "role" in entry:
                role, content = entry.get("role"), entry.get("content")
                if role in _VALID_ROLES and isinstance(content, str):
                    out.append({"role": role, "content": content})
                else:
                    dropped += 1
            elif "user" in entry or "bot" in entry:
                u, b = entry.get("user"), entry.get("bot")
                if isinstance(u, str) and u.strip():
                    out.append({"role": "user", "content": u})
                if isinstance(b, str) and b.strip():
                    out.append({"role": "assistant", "content": b})
                if not ((isinstance(u, str) and u.strip()) or (isinstance(b, str) and b.strip())):
                    dropped += 1
            else:
                dropped += 1
        if dropped:
            logger.warning("Memory: dropped %d malformed entries on load.", dropped)
        return out

    def _load(self) -> None:
        if not os.path.exists(MEMORY_FILE):
            return
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Memory file unreadable (%s) — writes refused.", exc)
            self._broken = True
            return
        if not isinstance(loaded, dict) or not isinstance(loaded.get("conversations"), list):
            logger.warning("Memory file schema invalid — writes refused.")
            self._broken = True
            return
        conversations = self._migrate_conversations(loaded["conversations"])

        # Preserve extra fields when reading legacy memory files.
        self._data = {k: v for k, v in loaded.items()
                      if k not in ("conversations", "total_messages")}
        self._data["conversations"] = conversations
        total = loaded.get("total_messages")
        self._data["total_messages"] = total if isinstance(total, int) and total >= 0\
            else len(conversations)

    def _save(self) -> None:
        """Save atomically, or raise OSError without overwriting broken input."""
        if self._broken:
            raise OSError("memory file broken; writes refused")
        if os.path.exists(MEMORY_FILE) and not os.path.exists(MEMORY_FILE + ".bak"):
            shutil.copy2(MEMORY_FILE, MEMORY_FILE + ".bak")
        tmp = MEMORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, MEMORY_FILE)

    def add_message(self, role: str, content: str) -> None:
        """Append a message and attempt a periodic save."""
        self._data["conversations"].append({"role": role, "content": content})
        self._data["total_messages"] = self._data.get("total_messages", 0) + 1

        if len(self._data["conversations"]) > MAX_CONVERSATIONS:
            self._data["conversations"] = self._data["conversations"][-MAX_CONVERSATIONS:]

        self._msg_counter += 1
        if self._msg_counter >= SAVE_INTERVAL:
            try:
                self._save()
            except OSError as exc:
                logger.error("Memory periodic save FAILED: %s", exc)
            self._msg_counter = 0

    def get_recent(self, n: int) -> list:
        """Return the last *n* messages in standard chat format."""
        return self._data["conversations"][-n:]

    def get_stats(self) -> dict:
        summaries = self._data.get("summaries", 0)
        return {
            "conversations": len(self._data["conversations"]),
            "total_messages": self._data.get("total_messages", 0),
            "summaries": len(summaries) if isinstance(summaries, list) else 0,
        }

    def clear(self) -> None:
        """Save empty history, rolling back in-memory state if saving fails."""
        data_before = self._data
        counter_before = self._msg_counter
        self._data = {"conversations": [], "total_messages": 0}
        self._msg_counter = 0
        try:
            self._save()
        except OSError:
            self._data = data_before
            self._msg_counter = counter_before
            raise

    @property
    def total_messages(self) -> int:
        return self._data.get("total_messages", 0)

    @property
    def broken(self) -> bool:
        return self._broken

    def force_save(self) -> bool:
        """Return whether the history was written successfully."""
        try:
            self._save()
            return True
        except OSError as exc:
            logger.error("Memory force save FAILED: %s", exc)
            return False
