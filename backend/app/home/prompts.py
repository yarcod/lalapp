from app.home.context import current_learner
from app.home.spoken_lines import tagged_replies_enabled
from app.services.language_helpers import get_language_name

_CHILD_INSTRUCTION = (
    "The student is a child of about 9-11 years old. Use simple, short words and a warm, "
    "encouraging tone. Choose everyday topics such as school, friends, pets, family, food, and "
    "games. Keep scenarios, examples, and explanations easy for a child to understand."
)

_INSTRUCTION_LANGUAGE_RULES = """\
Language of your replies (these rules override the instruction to answer only in {target}):
The student is a Swedish speaker at {level} level. Your reply is read aloud by two voices, a \
Swedish voice and a {target} voice, so write one item per line and start every line with a tag:
[sv] one short Swedish sentence. It must not contain any English or Spanish word at all, not even \
a quoted one. Refer to "meningen" or "ordet på skärmen" instead.
[{code}] one complete, correct {target} sentence for the student to hear and copy.
[screen] the key correction as short text shown on screen, for example: go → went. This line is \
not spoken.
Rules: 4 to 6 lines. Start with short, kind Swedish feedback. Then say the whole corrected \
sentence in a [{code}] line. Explain the mistake very simply in Swedish. Give the [screen] line. \
End with one easy question in a [{code}] line, followed by an [sv] line saying what the question \
means. Use only the tags [sv], [{code}], and [screen]. No emojis, no other labels."""


def child_instruction() -> str:
    """Return the shared instruction for students who are children."""
    return _CHILD_INSTRUCTION


def instruction_language_rules(level: str, native_code: str, target_code: str) -> str:
    """Return the tagged-line rules for Swedish A1-A2 learners, otherwise an empty string."""
    if not tagged_replies_enabled(native_code, level, target_code):
        return ""
    code = target_code.lower().split("-")[0]
    return _INSTRUCTION_LANGUAGE_RULES.format(
        target=get_language_name(target_code), level=level.upper(), code=code
    )


def child_suffix() -> str:
    """Return the child instruction as a prompt suffix for a child learner, else nothing."""
    return f"\n\n{child_instruction()}" if current_learner().is_child else ""


def tutor_suffix(cefr_level: str, target_code: str) -> str:
    """Return the extra tutor prompt sections for the current learner."""
    learner = current_learner()
    parts = []
    if learner.is_child:
        parts.append(child_instruction())
    rules = instruction_language_rules(cefr_level, learner.native_code, target_code)
    if rules:
        parts.append(rules)
    return "".join(f"\n{part}\n" for part in parts)
