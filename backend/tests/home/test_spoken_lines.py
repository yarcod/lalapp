from app.home.spoken_lines import (
    SpokenLine,
    display_text,
    invalid_swedish_lines,
    parse_reply,
)


def test_parse_tags() -> None:
    lines = parse_reply(
        "[sv] Säg så här.\n[en] Good morning.\n[screen] Good morning = God morgon", "en"
    )
    assert lines == [
        SpokenLine("sv", "Säg så här.", True),
        SpokenLine("en", "Good morning.", True),
        SpokenLine("screen", "Good morning = God morgon", False),
    ]


def test_untagged_line_treated_as_swedish_at_low_level() -> None:
    assert parse_reply("Hej, bra jobbat!", "es") == [SpokenLine("sv", "Hej, bra jobbat!", True)]


def test_screen_lines_not_spoken() -> None:
    (line,) = parse_reply("[screen] Rätt: I am", "en")
    assert line.spoken is False


def test_display_text_strips_tags() -> None:
    lines = parse_reply("[sv] Säg:\n[es] Buenos días.\n[screen] Buenos días = God morgon", "es")
    assert display_text(lines) == "Säg: Buenos días. Buenos días = God morgon"


def test_quoted_target_word_in_swedish_is_invalid() -> None:
    lines = parse_reply('[sv] Ordet "apple" betyder äpple.\n[sv] Bra jobbat!', "en")
    assert invalid_swedish_lines(lines) == [lines[0]]


def test_unquoted_target_words_in_swedish_are_invalid() -> None:
    lines = parse_reply("[sv] Du sa hello till mig.\n[en] Hello, how are you?", "en")
    assert invalid_swedish_lines(lines) == [lines[0]]
