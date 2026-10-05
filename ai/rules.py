"""Rule-based AI provider (default).

Deterministic, offline, no API key needed. Works with English, Russian and
Kazakh documents using keywords and regular expressions.

Interface (shared with the LLM provider):
    classify(text)            -> {"type": str, "confidence": float}
    extract(text, doc_type)   -> {field: {"value": str | None, "state": str}}
    summarize(text)           -> [str, ...]
"""
import re

from .schema import (
    DATE_FIELDS,
    FALLBACK_TYPE,
    FIELD_SCHEMAS,
    SUMMARY_MAX_BULLETS,
    SUMMARY_MIN_BULLETS,
)

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
# (keyword, weight). Strong (3) = wording that names the document type,
# weak (1) = wording that is typical but also appears elsewhere.
# Keywords match at the start of a word, so Russian/Kazakh endings are fine
# ("справк" matches "справка", "справку").
KEYWORDS = {
    "certificate": [
        ("certificate", 3), ("this is to certify", 3), ("hereby certif", 3), ("is issued to", 1),
        ("справка", 3), ("справку", 3), ("сертификат", 3), ("дана настоящая", 3), ("настоящая справка", 3),
        ("выдана", 1), ("по месту требования", 1),
        ("анықтама", 3), ("куәлік", 2), ("берілді", 1),
    ],
    "application_form": [
        ("application form", 3), ("application for", 3), ("i hereby apply", 3), ("applicant", 1),
        ("заявление", 3), ("анкета", 2), ("прошу зачислить", 3), ("прошу принять", 3), ("прошу предоставить академ", 2),
        ("өтініш", 3), ("сұраймын", 1),
    ],
    "request": [
        ("request", 3), ("i kindly ask", 2), ("please provide", 2),
        ("запрос", 3), ("просьба", 2), ("прошу предоставить", 2), ("прошу выдать", 2),
        ("сұрау", 3), ("сұраныс", 3),
    ],
    "transcript": [
        ("transcript", 3), ("academic record", 3), ("gpa", 2), ("credit", 1), ("grade", 1),
        ("транскрипт", 3), ("выписка из зачетной", 3), ("ведомость оценок", 3), ("кредит", 1), ("оценк", 1),
        ("академиялық анықтама", 3), ("баға", 1),
    ],
    "id_document": [
        ("passport", 3), ("identity card", 3), ("id card", 3), ("date of birth", 1), ("nationality", 1),
        ("паспорт", 3), ("удостоверение личности", 3), ("дата рождения", 1), ("гражданство", 1),
        ("жеке куәлік", 3), ("туған күні", 1), ("азаматтығы", 1),
    ],
    "internal_form": [
        ("internal form", 3), ("for internal use", 3), ("office use only", 2), ("memo", 2), ("approved by", 1),
        ("служебная записка", 3), ("внутренняя форма", 3), ("для служебного пользования", 3), ("утверждаю", 1),
        ("қызметтік хат", 3), ("ішкі нысан", 3), ("бекітемін", 1),
    ],
}

HEADER_CHARS = 200          # keywords in the title area count double
FULL_EVIDENCE_SCORE = 6.0   # score at which evidence is considered "strong"


def _kw_regex(keyword):
    # start of word on the left; Russian/Kazakh endings allowed on the right
    return re.compile(r"(?<!\w)" + re.escape(keyword), re.IGNORECASE)


_KW_COMPILED = {t: [(_kw_regex(k), w) for k, w in kws] for t, kws in KEYWORDS.items()}


def score_types(text):
    lower = (text or "").lower()
    header = lower[:HEADER_CHARS]
    scores = {}
    for doc_type, patterns in _KW_COMPILED.items():
        score = 0.0
        for regex, weight in patterns:
            if regex.search(lower):
                score += weight
                if weight >= 3 and regex.search(header):
                    score += weight  # title bonus
        scores[doc_type] = score
    return scores


def classify(text):
    scores = score_types(text)
    total = sum(scores.values())
    if total == 0:
        return {"type": FALLBACK_TYPE, "confidence": 0.0}
    best_type = max(scores, key=lambda t: (scores[t], -list(KEYWORDS).index(t)))
    best = scores[best_type]
    share = best / total                              # how dominant the winner is
    evidence = min(1.0, best / FULL_EVIDENCE_SCORE)   # how much evidence there is
    confidence = round(min(0.99, share * evidence), 2)
    return {"type": best_type, "confidence": confidence}


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
# Labels as they appear in documents: "Label: value".
FIELD_LABELS = {
    "full_name": ["full name", "name", "student name", "applicant", "фио", "ф.и.о.", "ф.и.о", "фамилия имя отчество",
                  "имя", "студент", "аты-жөні", "толық аты-жөні", "аты жөні"],
    "issuer": ["issued by", "issuer", "issuing organization", "organization", "выдано", "кем выдан",
               "организация", "берген ұйым", "берген"],
    "issue_date": ["date of issue", "issue date", "issued on", "дата выдачи", "берілген күні"],
    "document_number": ["document number", "document no.", "document no", "certificate number", "certificate no.",
                        "certificate no", "passport number", "id number", "номер документа", "номер справки",
                        "номер", "№", "құжат нөмірі", "нөмірі"],
    "purpose": ["purpose", "issued for", "for submission to", "цель", "для предоставления", "предоставляется",
                "мақсаты", "ұсыну үшін"],
    "student_id": ["student id", "student number", "id", "студенческий билет", "номер студента", "студенттік билет",
                   "id студента"],
    "faculty": ["faculty", "school", "факультет", "институт", "факультеті"],
    "request_subject": ["subject", "regarding", "re", "тема", "по вопросу", "тақырыбы"],
    "date": ["date", "дата", "күні"],
    "addressee": ["to", "addressee", "кому", "адресат", "кімге"],
    "program": ["program", "programme", "major", "специальность", "образовательная программа", "мамандық",
                "білім беру бағдарламасы"],
    "gpa": ["gpa", "cumulative gpa", "средний балл", "орташа балл"],
    "date_of_birth": ["date of birth", "birth date", "дата рождения", "туған күні"],
    "expiry_date": ["expiry date", "date of expiry", "valid until", "expires", "срок действия", "действителен до",
                    "жарамдылық мерзімі"],
    "department": ["department", "отдел", "кафедра", "подразделение", "бөлім"],
    "form_number": ["form number", "form no.", "form no", "номер формы", "форма №", "нысан нөмірі"],
    "approved_by": ["approved by", "утверждено", "утвердил", "бекіткен"],
}

# Patterns that find a full name in running text when there is no label.
NAME_PATTERNS = [
    re.compile(r"this is to certify that\s+(?:mr\.?\s+|ms\.?\s+)?([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,3})"),
    re.compile(r"(?:справка выдана|дана настоящая справка)\s+([А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі\-]+(?:\s+[А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі\-]+){1,2})"),
]

UNCLEAR_MARKERS = re.compile(
    r"\?|_{2,}|\.{3,}|…|\[(?:illegible|unclear|\?)\]|illegible|unreadable|неразборчив|нечитаем|оқылмайды|xxx",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"^\s*(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}|\d{4}[./\-]\d{1,2}[./\-]\d{1,2}|"
    r"\d{1,2}\s+[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]+\.?\s+\d{4}|"
    r"[A-Za-z]+\s+\d{1,2},\s*\d{4})\s*(г\.?|ж\.?|year)?\s*$"
)
SEPARATOR = r"\s*[:：\-–—]\s*"


def _label_index(fields):
    """All (label, field) pairs for the requested fields, longest label first,
    so 'date of birth' wins over 'date'."""
    pairs = [(label, f) for f in fields for label in FIELD_LABELS.get(f, [])]
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    compiled = []
    for label, field in pairs:
        sep = SEPARATOR if label[-1].isalnum() else r"\s*"
        compiled.append((re.compile(r"^\s*" + re.escape(label) + sep + r"(.*)$", re.IGNORECASE), field))
    return compiled


def _clean(value):
    value = (value or "").strip().strip(" \t;,")
    return value or None


def _state_for(field, value):
    if value is None:
        return "missing"
    if UNCLEAR_MARKERS.search(value):
        return "unclear"
    if len(re.sub(r"\W", "", value)) < 2:
        return "unclear"
    if field in DATE_FIELDS and not DATE_RE.match(value):
        return "unclear"
    return "ok"


def extract(text, doc_type):
    fields = FIELD_SCHEMAS.get(doc_type, [])
    found = {}
    index = _label_index(fields)
    for line in (text or "").splitlines():
        for regex, field in index:
            m = regex.match(line)
            if m:
                if field not in found:
                    found[field] = _clean(m.group(1))
                break  # a line belongs to one label only

    if "full_name" in fields and not found.get("full_name"):
        for pattern in NAME_PATTERNS:
            m = pattern.search(text or "")
            if m:
                found["full_name"] = _clean(m.group(1))
                break

    result = {}
    for field in fields:
        value = found.get(field)
        state = _state_for(field, value)
        # never keep a value we have marked as missing
        result[field] = {"value": value if state != "missing" else None, "state": state}
    return result


# ---------------------------------------------------------------------------
# Summary (extractive: bullets are sentences taken from the document itself,
# so the summary cannot contain facts that are not in the document)
# ---------------------------------------------------------------------------
CUE_PATTERNS = [
    # deadlines / dates
    (re.compile(r"deadline|no later than|until|by \d|within \d+|\d{1,2}[./]\d{1,2}[./]\d{2,4}|"
                r"\d{1,2}\s+(january|february|march|april|may|june|july|august|september|october|november|december)|"
                r"срок|не позднее|до \d|в течение|"
                r"дейін|мерзім|ішінде", re.IGNORECASE), 3),
    # requirements
    (re.compile(r"\bmust\b|required|requirement|mandatory|should|need to|"
                r"необходимо|обязательн|требуется|должен|должны|нужно|"
                r"қажет|міндетті|тиіс", re.IGNORECASE), 2),
    # documents to bring
    (re.compile(r"copy|copies|passport|photo|certificate|transcript|application|form|"
                r"копи|паспорт|фото|справк|заявлени|"
                r"көшірме|төлқұжат|сурет|анықтама|өтініш", re.IGNORECASE), 1),
]
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+|(?<=;)\s+")
MAX_BULLET_CHARS = 220


def split_sentences(text):
    parts = [re.sub(r"\s+", " ", p).strip(" -•*\t") for p in SENTENCE_SPLIT.split(text or "")]
    return [p for p in parts if len(re.findall(r"\w+", p)) >= 3]


def summarize(text):
    sentences = split_sentences(text)
    if not sentences:
        return []
    scored = []
    for i, s in enumerate(sentences):
        score = sum(w for rx, w in CUE_PATTERNS if rx.search(s))
        scored.append((score, i, s))

    picked = [x for x in scored if x[0] > 0]
    picked.sort(key=lambda x: (-x[0], x[1]))
    picked = picked[:SUMMARY_MAX_BULLETS]

    # Top up with the leading sentences if the cues found fewer than 3.
    if len(picked) < SUMMARY_MIN_BULLETS:
        chosen_idx = {x[1] for x in picked}
        for x in scored:
            if len(picked) >= SUMMARY_MIN_BULLETS:
                break
            if x[1] not in chosen_idx:
                picked.append(x)

    picked.sort(key=lambda x: x[1])  # keep the document's own order
    bullets = []
    for _, _, s in picked:
        if len(s) > MAX_BULLET_CHARS:
            s = s[:MAX_BULLET_CHARS].rsplit(" ", 1)[0] + "…"
        bullets.append(s)
    return bullets


class RuleBasedProvider:
    name = "rules"

    def classify(self, text):
        return classify(text)

    def extract(self, text, doc_type):
        return extract(text, doc_type)

    def summarize(self, text):
        return summarize(text)
