"""Shared prompt text snippets."""

DEFAULT_RESPONSE_GUIDANCE = (
    "- Detect the user's language from recent conversation turns and respond in that language (default to English when unclear).\n"
    "- Start with a short acknowledgement/summary, then present key points or next steps in bullets.\n"
    "- When tool output is structured, translate it into clear prose or tidy lists."
)

DEFAULT_FALLBACK_GUIDANCE = (
    "- If a tool returns no data, say so explicitly and suggest concrete follow-up actions (e.g., refine keywords).\n"
    "- When parameters or permissions are invalid, point out the field and explain how to correct it.\n"
    "- If the request exceeds current capabilities or information is missing, acknowledge the limitation and recommend alternative channels."
)

__all__ = ["DEFAULT_RESPONSE_GUIDANCE", "DEFAULT_FALLBACK_GUIDANCE"]
