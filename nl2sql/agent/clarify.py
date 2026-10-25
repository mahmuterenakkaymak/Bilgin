"""The follow-up a clarification turns into, and how to split it back apart.

A clarification stops the run (PLAN R5-10), so the user's choice comes back as a *new* question:
the chosen meaning rides along inside the question text after a marker sentence. That is why
`ask --choice` and the API need no second protocol, and why a real model reads the choice as part
of the question it was asked. `split_follow_up` is the other half - the fake has to tell an
ambiguous question from its own follow-up, and the ask log keeps the two as separate fields.
"""

from __future__ import annotations

# PLAN R5-11 fixes the text; every reader of a follow-up goes through this one constant.
CHOICE_MARKER = "\n\nKullanıcının seçtiği anlam: "


def follow_up_text(question: str, choice: str) -> str:
    """The question plus the meaning the user picked, as one question text."""
    return f"{question}{CHOICE_MARKER}{choice}"


def split_follow_up(text: str) -> tuple[str, str | None]:
    """(question, choice) of a follow-up text; (text, None) when nothing was chosen.

    The last marker wins, so a question that itself quotes the phrase still splits correctly.
    """
    question, marker, choice = str(text or "").rpartition(CHOICE_MARKER)
    if not marker:
        return str(text or "").strip(), None
    return question.strip(), choice.strip()
