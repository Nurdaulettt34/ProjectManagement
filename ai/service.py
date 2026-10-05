"""AI service: chooses a provider, validates its answer and falls back to the
rule-based provider whenever the LLM is not configured, fails or returns
something we cannot trust.

Public functions follow the project interface:
    classify(text)          -> {"type", "confidence"}          (+ "method")
    extract(text, doc_type) -> {field: {"value", "state"}}
    summarize(text)         -> [bullets]
`run(op, ...)` returns `(result, method)` where method is "rules" or "llm";
the backend uses it to store the method in the database.
"""
import logging
import re

from . import rules
from .llm import AIProviderError, AnthropicProvider
from .schema import (
    DOC_TYPES,
    FALLBACK_TYPE,
    FIELD_SCHEMAS,
    SUMMARY_MAX_BULLETS,
)

log = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.5
_rules = rules.RuleBasedProvider()


def _settings():
    try:
        from flask import current_app
        cfg = current_app.config
        return (cfg.get("ANTHROPIC_API_KEY"), cfg.get("ANTHROPIC_MODEL"),
                cfg.get("AI_CONFIDENCE_THRESHOLD", DEFAULT_THRESHOLD))
    except RuntimeError:  # outside an app context (e.g. a quick script)
        return None, None, DEFAULT_THRESHOLD


def get_llm_provider():
    """Return the LLM provider or None. Tests monkeypatch this function."""
    api_key, model, _ = _settings()
    if not api_key:
        return None
    try:
        return AnthropicProvider(api_key, model)
    except AIProviderError as exc:
        log.warning("LLM provider unavailable, using rules: %s", exc)
        return None


def threshold():
    return _settings()[2]


# ---------------------------------------------------------------------------
# Validation applied to every provider's raw answer
# ---------------------------------------------------------------------------
def _normalize(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def validate_classification(raw, min_confidence):
    if not isinstance(raw, dict):
        raise AIProviderError("classification is not an object")
    doc_type = raw.get("type")
    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        raise AIProviderError("confidence is not a number")
    if doc_type not in DOC_TYPES or not 0.0 <= confidence <= 1.0:
        raise AIProviderError(f"invalid classification: {raw!r}")
    confidence = round(confidence, 2)
    # Below the threshold we do not trust the label: report "other" (US3).
    if doc_type != FALLBACK_TYPE and confidence < min_confidence:
        doc_type = FALLBACK_TYPE
    return {"type": doc_type, "confidence": confidence}


def validate_fields(raw, text, doc_type):
    """Keep exactly the schema fields; a value that does not occur in the
    document text is treated as invented and dropped (state = missing)."""
    if not isinstance(raw, dict):
        raise AIProviderError("fields are not an object")
    source = _normalize(text)
    result = {}
    for field in FIELD_SCHEMAS.get(doc_type, []):
        item = raw.get(field) or {}
        value = item.get("value") if isinstance(item, dict) else None
        state = item.get("state") if isinstance(item, dict) else None
        value = value.strip() if isinstance(value, str) else None
        if not value:
            value, state = None, "missing"
        elif _normalize(value) not in source:
            value, state = None, "missing"  # not grounded in the text -> never shown
        elif state not in ("ok", "unclear"):
            state = "unclear"
        result[field] = {"value": value, "state": state}
    return result


def validate_summary(raw, text):
    if not isinstance(raw, list):
        raise AIProviderError("summary is not a list")
    source = _normalize(text)
    source_numbers = set(re.findall(r"\d+", source))
    bullets = []
    for b in raw:
        if not isinstance(b, str) or not b.strip():
            continue
        b = re.sub(r"\s+", " ", b).strip(" -•*")
        # a bullet with a number/date that is not in the document is invented
        if any(n not in source_numbers for n in re.findall(r"\d+", b)):
            continue
        bullets.append(b)
    bullets = bullets[:SUMMARY_MAX_BULLETS]
    if not bullets:
        raise AIProviderError("no grounded bullets left")
    return bullets


# ---------------------------------------------------------------------------
# Dispatch with fallback
# ---------------------------------------------------------------------------
def run(op, text, doc_type=None):
    min_conf = threshold()

    def check(raw):
        if op == "classify":
            return validate_classification(raw, min_conf)
        if op == "extract":
            return validate_fields(raw, text, doc_type)
        return validate_summary(raw, text)

    def call(provider):
        if op == "classify":
            return provider.classify(text)
        if op == "extract":
            return provider.extract(text, doc_type)
        return provider.summarize(text)

    llm = get_llm_provider()
    if llm is not None:
        try:
            return check(call(llm)), "llm"
        except AIProviderError as exc:
            log.warning("LLM %s failed, falling back to rules: %s", op, exc)

    raw = call(_rules)
    if op == "summarize":
        return raw, "rules"  # extractive: already grounded, may be empty
    return check(raw), "rules"


def classify(text):
    result, method = run("classify", text)
    return {**result, "method": method}


def extract(text, doc_type):
    return run("extract", text, doc_type)[0]


def summarize(text):
    return run("summarize", text)[0]
