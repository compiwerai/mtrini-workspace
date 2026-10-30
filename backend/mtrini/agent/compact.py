"""Context compaction: when the conversation nears the model's context window, summarize
older turns into one message and keep the most recent turns verbatim."""
from __future__ import annotations

from typing import Any

from ..providers import ChatMessage
from ..providers.gemini_anthropic import strip_thinking

CHARS_PER_TOKEN = 3.5
IMAGE_TOKENS = 1500
THRESHOLD = 0.7  # compact at 70% of the window
DEFAULT_WINDOWS = {"anthropic": 1_000_000, "gemini": 1_000_000, "openai": 400_000, "openrouter": 128_000,
                   "mistral": 128_000, "groq": 128_000, "deepseek": 128_000, "xai": 256_000,
                   "heabsy": 256_000,
                   # The sponsored free model has a small daily budget: compact early to keep requests cheap.
                   "free": 32_768}
SUMMARY_PREFIX = "[Earlier conversation, summarized to save context]\n"

SUMMARY_PROMPT = (
    "Summarize the conversation below so a coding agent can continue the work without it. "
    "Keep: the user's goals and requests, decisions made, files read or changed (with paths), "
    "commands run and their outcomes, errors still open, and what was about to happen next. "
    "Be specific and complete but concise. Plain text, no preamble.")


def estimate_tokens(messages: list[ChatMessage]) -> int:
    chars = 0
    images = 0
    for m in messages:
        chars += len(m.content or "")
        for c in m.tool_calls or []:
            chars += len(str(c.get("arguments", ""))) + 20
        images += len(m.images or [])
    return int(chars / CHARS_PER_TOKEN) + images * IMAGE_TOKENS


def context_window(provider_name: str, settings: dict[str, Any] | None) -> int:
    try:
        explicit = int((settings or {}).get("contextWindow") or 0)
    except (TypeError, ValueError):
        explicit = 0
    return explicit or DEFAULT_WINDOWS.get(provider_name, 32_768)


def needs_compaction(messages: list[ChatMessage], window: int, threshold: float = THRESHOLD) -> bool:
    return estimate_tokens(messages) > window * threshold


def _render(m: ChatMessage, limit: int = 1500) -> str:
    if m.role == "tool":
        return f"[tool result: {m.name or 'tool'}] {m.content[:limit]}"
    text = m.content[:limit * 4]
    for c in m.tool_calls or []:
        text += f"\n[called {c.get('name')} {str(c.get('arguments', ''))[:limit]}]"
    return f"{m.role.upper()}: {text}"


def _cut_index(messages: list[ChatMessage], keep_turns: int) -> int:
    """Index of the user message that starts the last `keep_turns` turns (cut only at turn starts,
    so a tool call is never separated from its result)."""
    starts = [i for i, m in enumerate(messages) if m.role == "user" and not m.content.startswith(SUMMARY_PREFIX)]
    if len(starts) <= keep_turns:
        return starts[0] if starts else len(messages)
    return starts[-keep_turns]


async def compact(provider: Any, model: str, messages: list[ChatMessage], keep_turns: int = 2,
                  max_chars: int = 400_000) -> tuple[list[ChatMessage], dict[str, Any]]:
    head = messages[:1] if messages and messages[0].role == "system" else []
    body_start = len(head)
    cut = _cut_index(messages, keep_turns)
    if cut <= body_start + 1 and keep_turns > 1:  # one long turn: keep only the current turn
        cut = _cut_index(messages, 1)
    older, recent = messages[body_start:cut], messages[cut:]
    if not older:
        return messages, {"compacted": False}
    transcript = "\n\n".join(_render(m) for m in older)
    if len(transcript) > max_chars:
        transcript = "…(oldest part omitted)…\n" + transcript[-max_chars:]
    reply = await provider.chat(model, [ChatMessage(role="system", content=SUMMARY_PROMPT),
                                        ChatMessage(role="user", content=transcript)], None)
    summary = (reply.get("content") or "").strip() or "(summary unavailable)"
    new = [*head, ChatMessage(role="user", content=SUMMARY_PREFIX + summary), *recent]
    strip_thinking(new)  # history before them changed, so replayed thinking blocks are no longer valid
    before, after = estimate_tokens(messages), estimate_tokens(new)
    return new, {"compacted": True, "before": before, "after": after, "summarized": len(older),
                 "cut": cut, "keptFrom": len(head) + 1}
