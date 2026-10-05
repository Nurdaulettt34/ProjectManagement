"""Optional LLM provider (Anthropic API).

Enabled only when ANTHROPIC_API_KEY is set. Every answer is parsed as JSON;
anything that is not valid JSON raises AIProviderError so the service can
fall back to the rule-based provider. Business validation (allowed types,
grounding of values in the text) lives in ai/service.py and is applied to
every provider.
"""
import json
import re

from .schema import DOC_TYPES, FIELD_SCHEMAS, SUMMARY_MAX_BULLETS, SUMMARY_MIN_BULLETS

MAX_INPUT_CHARS = 15000


class AIProviderError(Exception):
    pass


def _strip_fences(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class AnthropicProvider:
    name = "llm"

    def __init__(self, api_key, model, timeout=20.0):
        try:
            import anthropic
        except ImportError as exc:  # optional dependency
            raise AIProviderError("The 'anthropic' package is not installed.") from exc
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1)

    def _ask_json(self, system, user):
        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                temperature=0,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = "".join(getattr(b, "text", "") for b in msg.content)
            return json.loads(_strip_fences(raw))
        except AIProviderError:
            raise
        except Exception as exc:  # network, auth, rate limit, bad JSON ...
            raise AIProviderError(f"{type(exc).__name__}: {exc}") from exc

    def classify(self, text):
        system = (
            "You classify university documents. Answer with JSON only: "
            '{"type": <one of ' + ", ".join(DOC_TYPES) + '>, "confidence": <number 0..1>}. '
            "If you are not sure, answer type \"other\" with a low confidence. Never guess."
        )
        data = self._ask_json(system, "Document text:\n<<<\n" + text[:MAX_INPUT_CHARS] + "\n>>>")
        if not isinstance(data, dict):
            raise AIProviderError("classification answer is not an object")
        return {"type": data.get("type"), "confidence": data.get("confidence")}

    def extract(self, text, doc_type):
        fields = FIELD_SCHEMAS.get(doc_type, [])
        if not fields:
            return {}
        system = (
            "You extract fields from a university document. Answer with JSON only: an object whose keys are exactly "
            + ", ".join(fields)
            + '. Each value is {"value": <string copied verbatim from the document, or null>, '
            '"state": "ok" | "missing" | "unclear"}. '
            "If a field is not in the document use value null and state \"missing\". "
            "If it is present but illegible or ambiguous use state \"unclear\". "
            "Never invent, normalize or translate values."
        )
        data = self._ask_json(system, "Document text:\n<<<\n" + text[:MAX_INPUT_CHARS] + "\n>>>")
        if not isinstance(data, dict):
            raise AIProviderError("extraction answer is not an object")
        return data

    def summarize(self, text):
        system = (
            f"Summarize a university document in {SUMMARY_MIN_BULLETS}-{SUMMARY_MAX_BULLETS} short bullet points: "
            "key requirements, deadlines and required documents. Use only facts stated in the document; "
            "copy numbers and dates exactly. Answer in the document's language with JSON only: "
            '{"bullets": ["...", "..."]}.'
        )
        data = self._ask_json(system, "Document text:\n<<<\n" + text[:MAX_INPUT_CHARS] + "\n>>>")
        if not isinstance(data, dict) or not isinstance(data.get("bullets"), list):
            raise AIProviderError("summary answer has no bullets list")
        return data["bullets"]
