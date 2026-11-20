"""Tagged chat display: Swedish A1/A2 replies are shown without their spoken-line tags."""

from app.home.spoken_lines import display_text, parse_reply, tagged_replies_enabled


class TaggedChatStream:
    """Buffers a tagged reply (tags can span chunks) and returns it cleaned once complete."""

    def __init__(self, native_code: str, cefr_level: str, target_code: str) -> None:
        self._target_code = target_code
        self._tagged = tagged_replies_enabled(native_code, cefr_level, target_code)
        self._text = ""

    def token(self, token: str) -> str | None:
        """Return the token to stream, or None while buffering a tagged reply."""
        if not self._tagged:
            return token
        self._text += token
        return None

    def reset(self) -> None:
        """Drop buffered text when the model restarts its reply."""
        self._text = ""

    def final(self) -> str | None:
        """Return the cleaned reply for a tagged reply, otherwise None."""
        if not self._tagged:
            return None
        return display_text(parse_reply(self._text, self._target_code), sep="\n") or None
