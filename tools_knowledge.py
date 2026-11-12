"""Short, non-operational descriptions of widely known security tools."""

TOOLS_KB: dict[str, dict] = {
    "nmap": {
        "name": "nmap",
        "description": "أداة معروفة لاستكشاف الأجهزة والخدمات في الشبكات المصرح بفحصها.",
        "cat": ["فحص الشبكات"],
        "desc": "استكشاف الشبكات والخدمات",
        "level": "عام",
    },
    "burpsuite": {
        "name": "Burp Suite",
        "description": "منصة معروفة لمراجعة أمان تطبيقات الويب وتحليل طلبات المتصفح.",
        "cat": ["أمن تطبيقات الويب"],
        "desc": "مراجعة أمان تطبيقات الويب",
        "level": "عام",
    },
    "wireshark": {
        "name": "Wireshark",
        "description": "محلل معروف لحركة الشبكة وبروتوكولاتها.",
        "cat": ["تحليل الشبكات"],
        "desc": "تحليل حركة الشبكة",
        "level": "عام",
    },
    "tcpdump": {
        "name": "tcpdump",
        "description": "أداة سطر أوامر معروفة لتحليل حركة الشبكة.",
        "cat": ["تحليل الشبكات"],
        "desc": "تحليل حركة الشبكة",
        "level": "عام",
    },
    "volatility": {
        "name": "Volatility",
        "description": "إطار معروف للتحليل الجنائي لتفريغات ذاكرة الحاسوب.",
        "cat": ["التحليل الجنائي الرقمي"],
        "desc": "تحليل الذاكرة رقمياً",
        "level": "عام",
    },
    "autopsy": {
        "name": "Autopsy",
        "description": "منصة مفتوحة المصدر للتحقيق الجنائي الرقمي في الوسائط والملفات.",
        "cat": ["التحليل الجنائي الرقمي"],
        "desc": "التحقيق الجنائي الرقمي",
        "level": "عام",
    },
}

TOOL_NAMES: dict[str, str] = {
    **{k: k for k in TOOLS_KB},
    "burp": "burpsuite",
    "burp suite": "burpsuite",
    "volatility3": "volatility",
    "vol": "volatility",
    "vol.py": "volatility",
    "wireshark": "wireshark",
}


def format_tool_info(tool_key: str) -> str:
    """Return only a tool name and a brief general description."""
    info = TOOLS_KB.get(tool_key)
    if not info:
        return ""
    return f"🔧 *{info['name']}* — {info['description']}"


def lookup_tool(query: str) -> str:
    """Try an exact alias, then scan aliases for a substring match."""

    key = TOOL_NAMES.get(query.strip().lower())
    if key:
        return format_tool_info(key)

    q = query.strip().lower()
    for alias, canonical in TOOL_NAMES.items():
        if q in alias or alias in q:
            return format_tool_info(canonical)

    return ""
