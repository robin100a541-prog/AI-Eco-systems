"""Arabisk text utan raqm: bokstavsformer ur Unicodes Arabic Presentation Forms-B och höger-till-vänster.

Pillow kan forma arabiska bara med biblioteket raqm, och det finns inte i alla miljöer. `shape()` gör därför
formningen själv för vanlig text:
- **Form efter plats:** varje bokstav får rätt form (isolerad, först, mitt eller sist) efter om den kan
  bindas till grannarna.
- **lam-alef:** lam och alef blir en ligatur.
- **Ordningen** vänds, så att texten kan ritas från vänster till höger.

Vokaltecken (harakat) och tatweel stöds inte och stoppas. En design ska bara ha text som formas rätt.
"""
from __future__ import annotations

# bokstav: (isolerad, sist, först, mitt); None betyder att formen inte finns (bokstaven binder bara bakåt)
FORMS = {
    "ء": ("ﺀ", None, None, None),
    "آ": ("ﺁ", "ﺂ", None, None), "أ": ("ﺃ", "ﺄ", None, None),
    "ؤ": ("ﺅ", "ﺆ", None, None), "إ": ("ﺇ", "ﺈ", None, None),
    "ئ": ("ﺉ", "ﺊ", "ﺋ", "ﺌ"), "ا": ("ﺍ", "ﺎ", None, None),
    "ب": ("ﺏ", "ﺐ", "ﺑ", "ﺒ"), "ة": ("ﺓ", "ﺔ", None, None),
    "ت": ("ﺕ", "ﺖ", "ﺗ", "ﺘ"), "ث": ("ﺙ", "ﺚ", "ﺛ", "ﺜ"),
    "ج": ("ﺝ", "ﺞ", "ﺟ", "ﺠ"), "ح": ("ﺡ", "ﺢ", "ﺣ", "ﺤ"),
    "خ": ("ﺥ", "ﺦ", "ﺧ", "ﺨ"), "د": ("ﺩ", "ﺪ", None, None),
    "ذ": ("ﺫ", "ﺬ", None, None), "ر": ("ﺭ", "ﺮ", None, None),
    "ز": ("ﺯ", "ﺰ", None, None), "س": ("ﺱ", "ﺲ", "ﺳ", "ﺴ"),
    "ش": ("ﺵ", "ﺶ", "ﺷ", "ﺸ"), "ص": ("ﺹ", "ﺺ", "ﺻ", "ﺼ"),
    "ض": ("ﺽ", "ﺾ", "ﺿ", "ﻀ"), "ط": ("ﻁ", "ﻂ", "ﻃ", "ﻄ"),
    "ظ": ("ﻅ", "ﻆ", "ﻇ", "ﻈ"), "ع": ("ﻉ", "ﻊ", "ﻋ", "ﻌ"),
    "غ": ("ﻍ", "ﻎ", "ﻏ", "ﻐ"), "ف": ("ﻑ", "ﻒ", "ﻓ", "ﻔ"),
    "ق": ("ﻕ", "ﻖ", "ﻗ", "ﻘ"), "ك": ("ﻙ", "ﻚ", "ﻛ", "ﻜ"),
    "ل": ("ﻝ", "ﻞ", "ﻟ", "ﻠ"), "م": ("ﻡ", "ﻢ", "ﻣ", "ﻤ"),
    "ن": ("ﻥ", "ﻦ", "ﻧ", "ﻨ"), "ه": ("ﻩ", "ﻪ", "ﻫ", "ﻬ"),
    "و": ("ﻭ", "ﻮ", None, None), "ى": ("ﻯ", "ﻰ", None, None),
    "ي": ("ﻱ", "ﻲ", "ﻳ", "ﻴ"),
}
LAM_ALEF = {"آ": ("ﻵ", "ﻶ"), "أ": ("ﻷ", "ﻸ"), "إ": ("ﻹ", "ﻺ"), "ا": ("ﻻ", "ﻼ")}


def _joins_forward(ch: str) -> bool:
    forms = FORMS.get(ch)
    return bool(forms and forms[2])


def is_arabic(text: str) -> bool:
    return any("؀" <= c <= "ۿ" for c in text)


def shape(text: str) -> str:
    """Formad och omvänd text som kan ritas från vänster till höger."""
    unsupported = {c for c in text if "؀" <= c <= "ۿ" and c not in FORMS}
    if unsupported:
        raise ValueError(f"tecknen stöds inte av formningen: {''.join(sorted(unsupported))}")
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch not in FORMS:
            out.append(ch)
            i += 1
            continue
        prev_joins = i > 0 and _joins_forward(text[i - 1])
        if ch == "ل" and i + 1 < len(text) and text[i + 1] in LAM_ALEF:
            isolated, final = LAM_ALEF[text[i + 1]]
            out.append(final if prev_joins else isolated)
            i += 2
            continue
        nxt = text[i + 1] if i + 1 < len(text) else ""
        next_joins = nxt in FORMS and FORMS[ch][2] is not None
        isolated, final, initial, medial = FORMS[ch]
        if prev_joins and next_joins and medial:
            out.append(medial)
        elif prev_joins and final:
            out.append(final)
        elif next_joins and initial:
            out.append(initial)
        else:
            out.append(isolated)
        i += 1
    return "".join(reversed(out))
