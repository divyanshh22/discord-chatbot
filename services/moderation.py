from __future__ import annotations

import random
import re
from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class Level(str, Enum):
    NORMAL = "normal"
    GREETING = "greeting"
    HELP = "help"
    TEASE = "tease"
    BANTER = "banter"
    ROAST = "roast"
    SERIOUS = "serious"


_MILD_PROFANITY = {
    "chutiya", "chutiye", "gandu", "bhosdi", "bhosdike", "madarchod", "mc",
    "bc", "bkl", "bsdk", "harami", "kutta", "kutte", "kamina", "saala", "sala",
    "suar", "gadha", "ullu", "pagal", "idiot", "stupid", "dumb", "nub",
    "noob", "lame", "trash", "garbage", "fuck", "fucking", "shit", "damn",
    "ass", "bastard", "dick", "prick", "moron",
}

_ROAST_REQUEST = [
    r"\broast\s+me\b", r"\broast\s+kar\b", r"\bmujhe\s+roast\b",
    r"\broast\s+kro\b", r"\bgaali\s+de\b", r"\bgaali\s+do\b",
    r"\bbura\s+bol\b", r"\binsult\s+me\b", r"\bmake\s+fun\s+of\s+me\b",
    r"\broast\b",
]

_TEASE = [
    r"\baukaat\b", r"\bhalkat\b", r"\bkaam\s+ka\s+nahi\b",
    r"\bkuch\s+nahi\s+aata\b", r"\bnikamma\b", r"\bfaltu\b", r"\bbekar\b",
    r"\buseless\b", r"\bnautanki\b", r"\btujhse\s+na\s+ho\b",
    r"\btu\s+pagal\b", r"\btum\s+pagal\b", r"\bchallenge\b",
    r"\bweak\s+bot\b", r"\bdumb\s+bot\b",
]

_GREETING = [
    r"\b(hi+|hey+|hello+|helo|yo|sup|hola)\b",
    r"\bnamaste\b", r"\bnamaskar\b", r"\bsalaam\b", r"\bassalam",
    r"\bgood\s+(morning|afternoon|evening|night)\b", r"\b(gm|gn)\b",
    r"\bkya\s+haal\b", r"\bkaise\s+ho\b", r"\bkaisa\s+hai\b",
    r"\bkya\s+chal\s+raha\b", r"\bhow\s+are\s+you\b", r"\bwhat'?s\s+up\b",
]

_HELP_STRONG = [
    r"\bhelp\b", r"\bhow\s+to\b", r"\bhow\s+do\s+i\b", r"\bcan\s+you\s+help\b",
    r"\bguide\s+me\b", r"\bsuggest\b", r"\bexplain\b", r"\bteach\s+me\b",
    r"\berror\b", r"\bexception\b", r"\btraceback\b", r"\bbug\b",
    r"\bdebug\b", r"\bnot\s+working\b", r"\bdoesn'?t\s+work\b",
    r"\bkaam\s+nahi\s+kar", r"\bkaise\s+(kar|kare|karna|fix|solve|bana)",
    r"\bkaise\s+fix\b", r"\bkya\s+karun\b", r"\bproblem\s+aa\b",
]

_HELP_WEAK = [
    r"\bcode\b", r"\bcoding\b", r"\bprogram(ming)?\b", r"\bscript\b",
    r"\bpython\b", r"\bjavascript\b", r"\btypescript\b", r"\bjava\b",
    r"\bc\+\+\b", r"\bc#\b", r"\bhtml\b", r"\bcss\b", r"\bsql\b",
    r"\breact\b", r"\bnode(\.js)?\b", r"\bapi\b", r"\bgithub\b", r"\bgit\b",
    r"\bfunction\b", r"\binstall\b", r"\bpip\b", r"\bnpm\b", r"\bcompile\b",
    r"\bsyntax\b", r"\bstack\s?trace\b",
]

_INFO = [
    r"\bdate\b", r"\btareekh\b", r"\btaareekh\b",
    r"\baaj\s+ka\s+din\b", r"\baaj\s+kons[ae]\s+din\b",
    r"\bwhat(?:'s| is)?\s+the\s+(date|time|day)\b",
    r"\btoday'?s?\s+(date|day)\b", r"\bcurrent\s+(date|time|day)\b",
    r"\bwhat\s+time\b", r"\btime\s+kya\b", r"\bkitne\s+baje\b",
    r"\bkya\s+(date|time|din)\b", r"\bwhich\s+day\b",
]

_STOP_REQUEST = [
    r"\bstop\b", r"\bband\s+kar\b", r"\bbas\s+kar\b", r"\bchup\b",
    r"\bshut\s+up\b", r"\bdon'?t\s+roast\b", r"\bmat\s+kar\b",
    r"\bbas\s+karo\b", r"\bmane\s+kar\b", r"\bplease\s+stop\b",
    r"\bno\s+more\s+roast\b", r"\broast\s+mat\b",
]

_ABUSE = [
    r"\bchut+i?ya?\b", r"\bchutiye\b", r"\bchutiyo\b",
    r"\bg[ao]a?ndu?\b", r"\bgaand\b", r"\bgandu\b",
    r"\bbhosd[aei]\w*", r"\bbhosda\b",
    r"\bmadar+chod\w*", r"\bmadarchod\b", r"\bmadrchod\b", r"\bmaderchod\b",
    r"\bbkl\b", r"\bbsdk\b", r"\bmkc\b", r"\bbkc\b", r"\bmc\b", r"\bbc\b",
    r"\bharami\b", r"\bharamkhor\b", r"\bharamzad[ae]\b",
    r"\bkami(na|ne|ni)\b",
    r"\bkutt?[ae]?i?ya?\b", r"\bkutiya\b",
    r"\bsaal[ae]\b", r"\bsala\b", r"\bsali\b", r"\bsaali\b",
    r"\bsuar\b", r"\bsuwar\b", r"\bgadh[ae]\b", r"\bullu\b",
    r"\bpagal\b", r"\bpaagal\b",
    r"\blodu\b", r"\blaude\b", r"\blavd[ae]\b", r"\blawde\b", r"\bloda?\b",
    r"\brandi\b", r"\brandy\b", r"\bevda\b",
    r"\bbitch\b", r"\bbastard\b", r"\basshole\b", r"\barsehole\b",
    r"\bdickhead\b", r"\bmotherfuck\w*", r"\bfuck(er|ing)?\b", r"\bshit\b",
    r"\bbullshit\b", r"\bidiot\b", r"\bstupid\b", r"\bdumbass\b",
    r"\bmoron\b", r"\bnoob\b", r"\bnub\b", r"\btrash\b", r"\bgarbage\b",
    r"\bloser\b", r"\blame\b", r"\bwtf\b", r"\bstfu\b",
]

_SERIOUS = [
    r"\bdepress(ed|ion)?\b", r"\bsuicid(e|al|e)\b", r"\bself[- ]?harm\b",
    r"\bkilling\s+myself\b", r"\bkill\s+myself\b", r"\bend\s+my\s+life\b",
    r"\bwant\s+to\s+die\b", r"\bwant\s+to\s+kill\s+myself\b",
    r"\bmarna\s+chahta\b", r"\bmar\s+jaun\b", r"\bmar\s+jaunga\b",
    r"\bjeena\s+nahi\b", r"\bkhatam\s+kar\s+dunga\b", r"\bhopeless\b",
    r"\bworthless\b", r"\bpanic\s+attack\b", r"\bcutting\s+myself\b",
    r"\bpassed\s+away\b", r"\bdied\b", r"\bdad\s+died\b", r"\bmom\s+died\b",
    r"\bcancer\b", r"\bdiagnosed\b", r"\bhospital\b",
]

_THREAT = [
    r"i\s+will\s+kill\s+you", r"i'?ll\s+kill\s+you",
    r"tera\s+ghar\s+jala", r"goli\s+mar", r"jaan\s+se\s+maar",
    r"throat\s+slit", r"swat\s+you", r"rick\s+roll\s+you",
    r"maar\s+dunga", r"katl",
]

_HATE = [
    r"\bn[i1]gg", r"\bf[a4]gg", r"\bk[i1]ke\b", r"\bch[i1]nki\b",
    r"\bretard", r"\bnazi\b",
]

_DOXX = [
    r"\b\d{1,3}(\.\d{1,3}){3}\b",
    r"\bthe?i?r?\s+address\b", r"\bhome\s+address\b",
    r"\bcredit\s+card\b", r"\bcvv\b",
]


def _compile(patterns: Sequence[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_ROAST_RE = _compile(_ROAST_REQUEST)
_TEASE_RE = _compile(_TEASE)
_GREETING_RE = _compile(_GREETING)
_HELP_STRONG_RE = _compile(_HELP_STRONG)
_HELP_WEAK_RE = _compile(_HELP_WEAK)
_INFO_RE = _compile(_INFO)
_ABUSE_RE = _compile(_ABUSE)
_STOP_RE = _compile(_STOP_REQUEST)
_SERIOUS_RE = _compile(_SERIOUS)
_THREAT_RE = _compile(_THREAT)
_HATE_RE = _compile(_HATE)
_DOXX_RE = _compile(_DOXX)

_WORD_RE = re.compile(r"[a-zA-Z']+")
_HINDI_RE = re.compile(r"[\u0900-\u097F]")


def _any(patterns: Sequence[re.Pattern], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def detect_language(text: str) -> str:
    if _HINDI_RE.search(text):
        return "hi"
    words = {w.lower() for w in _WORD_RE.findall(text)}
    hindi_roman = {
        "bhai", "kya", "hai", "nahi", "kyun", "kaise", "kaisa", "tum", "tu",
        "mera", "tera", "acha", "bohot", "bahut", "yaar", "kar", "raha",
        "rahi", "hoon", "hun", "theek", "thik", "nhi", "kro", "krna", "kaam",
        "abhi", "kal", "kahan", "kaun", "kyu", "matlab", "bata", "bol",
    }
    if words & hindi_roman:
        return "hinglish"
    return "en"


def has_profanity(text: str) -> bool:
    words = {w.lower() for w in _WORD_RE.findall(text)}
    if words & _MILD_PROFANITY:
        return True
    return _any(_ABUSE_RE, text)


_GAALI_FALLBACKS = [
    "chutiye", "bkl", "gandu", "harami", "lodu", "nikamme", "kamini",
]


def ensure_profanity(reply: str, *, lang: str = "hinglish") -> str:
    if reply and has_profanity(reply):
        return reply
    gaali = random.choice(_GAALI_FALLBACKS)
    base = (reply or "").strip()
    if not base:
        return f"{gaali}, itna bhi nahi bol paaya? wah 😭"
    return f"{gaali}, {base}"


@dataclass
class Classification:
    level: Level
    language: str
    wants_roast: bool
    wants_stop: bool
    serious: bool
    blocked: bool
    block_reason: str = ""


def classify(text: str) -> Classification:
    normalized = text or ""
    lower = normalized.lower()
    language = detect_language(normalized)

    serious = (
        _any(_SERIOUS_RE, normalized)
        or "kill myself" in lower
        or "end my life" in lower
        or "suicide" in lower
    )
    wants_stop = _any(_STOP_RE, normalized)
    wants_roast = _any(_ROAST_RE, normalized) and not serious

    help_intent = (
        _any(_HELP_STRONG_RE, normalized)
        or _any(_INFO_RE, normalized)
        or (_any(_HELP_WEAK_RE, normalized) and "?" in normalized)
    )
    greeting = _any(_GREETING_RE, normalized)

    blocked = False
    block_reason = ""
    if _any(_THREAT_RE, normalized):
        blocked = True
        block_reason = "threat"
    elif _any(_HATE_RE, normalized):
        blocked = True
        block_reason = "hate"
    elif _any(_DOXX_RE, normalized):
        blocked = True
        block_reason = "doxx"

    if serious:
        level = Level.SERIOUS
    elif wants_roast:
        level = Level.ROAST
    elif help_intent:
        level = Level.HELP
    elif has_profanity(normalized):
        level = Level.BANTER
    elif greeting:
        level = Level.GREETING
    elif (
        _any(_TEASE_RE, normalized)
        or normalized.count("!") >= 2
        or normalized.count("?") >= 2
    ):
        level = Level.TEASE
    else:
        level = Level.NORMAL

    return Classification(
        level=level,
        language=language,
        wants_roast=wants_roast,
        wants_stop=wants_stop,
        serious=serious,
        blocked=blocked,
        block_reason=block_reason,
    )


class DuplicateTracker:
    def __init__(self, window: int = 8) -> None:
        self._recent: list[str] = []
        self._window = window

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    def is_duplicate(self, text: str) -> bool:
        key = self._normalize(text)
        if not key:
            return True
        return key in self._recent

    def add(self, text: str) -> None:
        key = self._normalize(text)
        self._recent.append(key)
        if len(self._recent) > self._window:
            self._recent.pop(0)


def sanitize_reply(text: str, max_length: int) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 1].rstrip() + "…"
    return cleaned


def relevance_score(text: str) -> float:
    text = (text or "").strip()
    if not text:
        return 0.0
    score = 0.25
    if "?" in text:
        score += 0.35
    words = text.split()
    score += min(len(words), 12) / 24.0
    if len(text) > 40:
        score += 0.1
    if text.lower() in {"lol", "lmao", "ok", "okay", "hmm", "haha", "xd"}:
        score = 0.05
    return min(score, 1.0)
