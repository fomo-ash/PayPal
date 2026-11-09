"""Provider-neutral LLM client for the AI judge.

Verdict talks to any OpenAI-compatible endpoint, so the model is a config choice:
  primary  = Groq      (free tier, no card, prompts not used for training)
  fallback = Gemini    (Google AI Studio free tier, via its OpenAI-compatible endpoint)
Switching to Cerebras, OpenRouter, Mistral or a paid provider means changing .env only.

Behaviour:
  * JSON mode (`response_format={"type": "json_object"}`) works across providers; the
    result is validated with a Pydantic model, and one repair attempt is made if invalid.
  * Rate limits (HTTP 429) are retried by the SDK with backoff; if the primary still fails,
    the fallback provider is tried. If every provider fails, LLMUnavailable is raised and
    the caller routes the case to HUMAN_REVIEW (never to a payment change).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(Exception):
    """Every configured provider failed or returned invalid output."""


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class LLMResult:
    data: BaseModel
    provider: str
    model: str
    raw: str


def untrusted(text: str) -> str:
    """Neutralise closing tags so text written by a worker or buyer cannot end the
    <untrusted>/<tests> block it is wrapped in and pose as instructions."""
    return text.replace("</", "<\\/")


def _json_mode_rejected(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "json_validate_failed" in msg or "failed to validate json" in msg


def _extract_json(text: str) -> str:
    """Accept bare JSON or JSON wrapped in ``` fences / surrounding prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


class LLMClient:
    def __init__(self, providers: list[Provider], timeout: float = 60.0, max_retries: int = 3,
                 client_factory=None):
        self.providers = [p for p in providers if p.api_key and p.base_url and p.model]
        if not self.providers:
            raise LLMUnavailable("no LLM provider configured; set LLM_API_KEY in .env")
        if client_factory is None:
            from openai import OpenAI

            def client_factory(p: Provider):
                return OpenAI(base_url=p.base_url, api_key=p.api_key,
                              timeout=timeout, max_retries=max_retries)
        self._clients = {p.name: client_factory(p) for p in self.providers}

    def chat_json(self, system: str, user: str, schema: type[T],
                  temperature: float = 0.0, max_tokens: int = 1500) -> LLMResult:
        errors: list[str] = []
        for p in self.providers:
            client = self._clients[p.name]
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            strict = True                     # provider-side JSON mode
            for attempt in range(2):          # 1 normal try + 1 repair try
                try:
                    kw = {"response_format": {"type": "json_object"}} if strict else {}
                    resp = client.chat.completions.create(
                        model=p.model, messages=messages, temperature=temperature,
                        max_tokens=max_tokens, **kw,
                    )
                    raw = resp.choices[0].message.content or ""
                except Exception as exc:  # noqa: BLE001 - network, 429 after retries, 5xx
                    errors.append(f"{p.name}: {type(exc).__name__}: {exc}")
                    if strict and attempt == 0 and _json_mode_rejected(exc):
                        # Groq returns 400 when its own JSON-mode output fails validation.
                        # Ask again without JSON mode; _extract_json + Pydantic still check it.
                        strict = False
                        continue
                    log.warning("LLM provider %s failed: %s", p.name, exc)
                    break                     # move on to the next provider
                try:
                    data = schema.model_validate(json.loads(_extract_json(raw)))
                    return LLMResult(data, p.name, p.model, raw)
                except (json.JSONDecodeError, ValidationError) as exc:
                    errors.append(f"{p.name}: invalid output (attempt {attempt + 1}): {exc}")
                    messages = messages + [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": "That was not valid. Reply with ONLY one JSON "
                                                    "object matching the required fields."},
                    ]
        raise LLMUnavailable("; ".join(errors))


def client_from_settings(settings) -> LLMClient:
    """Raises LLMUnavailable when no provider key is set."""
    providers = [
        Provider(settings.llm_provider, settings.llm_base_url, settings.llm_api_key,
                 settings.judge_model),
        Provider("fallback", settings.llm_fallback_base_url, settings.llm_fallback_api_key,
                 settings.llm_fallback_model),
    ]
    return LLMClient(providers)


def optional_client(settings) -> LLMClient | None:
    """The judge client, or None when no LLM key is configured (the AI steps are skipped)."""
    try:
        return client_from_settings(settings)
    except LLMUnavailable:
        log.warning("no LLM key configured: spec check and AI review are skipped")
        return None
