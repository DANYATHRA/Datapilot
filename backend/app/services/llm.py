from ..config import settings


class LLMUnavailable(Exception):
    pass


def available() -> bool:
    return bool(settings.ANTHROPIC_API_KEY)


def complete(system: str, messages: list[dict], max_tokens: int = 1500) -> str:
    if not available():
        raise LLMUnavailable("Set ANTHROPIC_API_KEY to enable AI features.")
    import anthropic

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    r = client.messages.create(model=settings.LLM_MODEL, max_tokens=max_tokens,
                               system=system, messages=messages)
    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
