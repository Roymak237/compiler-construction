"""Correction engine: what to do after the analyzer says REJECTED.

A rejection is only half an answer.  This module turns the two kinds of
failure the pipeline can report into concrete, actionable advice:

*Lexical failure*
    A lexeme is not in the specification.  We look for the closest declared
    entries using a combination of edit distance and a phonetic key tuned for
    the way Yaounde speech is transcribed (``tchop``/``chop``, ``mbombo``/
    ``mbomvo``, ``wanda``/``ouanda``).  We also try splitting the unknown run
    in two, because transcribers routinely glue a particle onto the word in
    front of it (``quartierla`` for ``quartier la``).

*Syntactic failure*
    The lexemes are all known but the order is not in the language.  The
    parser already reports which terminals the table would have accepted at
    that point, so we name them and show a declared example of each.

When every unknown lexeme has a confident replacement, the module rewrites
the transcription and, if it is given an analyzer, re-runs it so the user is
told whether the proposal actually parses.  Nothing here guesses silently:
each suggestion carries its score and the reason it was proposed.

The module is deliberately dependency-free, like the rest of the package.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .lexspec import PHRASES, WORDS, fold
from .tokens import TokenType

__all__ = [
    "Candidate",
    "Suggestion",
    "SyntaxHint",
    "CorrectionReport",
    "edit_distance",
    "similarity",
    "phonetic_key",
    "consonant_key",
    "suggest_lexeme",
    "corrections",
]


# --------------------------------------------------------------------------
# Tuning constants.  They are module level so the report can quote them and
# the tests can assert on them instead of on magic numbers.
# --------------------------------------------------------------------------

#: Below this similarity a candidate is not worth showing to the user.
MIN_SIMILARITY = 0.55

#: A phonetic match is strong evidence in speech transcription, so it lifts
#: the score rather than merely breaking ties.
PHONETIC_BONUS = 0.25

#: Vowels are the least stable part of an informal transcription, so two forms
#: sharing a consonant skeleton (``drapp``/``drop``) get a smaller lift.
SKELETON_BONUS = 0.15

#: A bonus can only rescue a candidate that was already plausible on letters
#: alone; without this floor every three-letter word matches every other one.
MIN_BASE = 0.40

#: Never overwhelm the panel; the ranking is only meaningful at the top.
MAX_SUGGESTIONS = 5

#: A rewrite is only proposed when the best candidate clears this bar.
CONFIDENT = 0.72


# --------------------------------------------------------------------------
# String distance
# --------------------------------------------------------------------------

def edit_distance(a: str, b: str) -> int:
    """Damerau-Levenshtein distance between *a* and *b*.

    Transpositions count as one edit, which matters here because the common
    transcription slips are swapped letters (``mkolo`` for ``mokolo``) rather
    than wholesale substitutions.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # Three rolling rows are enough for the restricted (optimal string
    # alignment) variant, which is the one we want: no re-editing a substring.
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(
                prev[j] + 1,        # deletion
                cur[j - 1] + 1,     # insertion
                prev[j - 1] + cost,  # substitution
            )
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + cost)
        prev2, prev = prev, cur
    return prev[len(b)]


def similarity(a: str, b: str) -> float:
    """Edit distance rescaled to ``0.0 .. 1.0``, where 1.0 means identical."""
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return 1.0 - edit_distance(a, b) / longest


# --------------------------------------------------------------------------
# Phonetic key
# --------------------------------------------------------------------------

_NON_LETTER_RE = re.compile(r"[^a-z0-9]+")
_DOUBLE_RE = re.compile(r"(.)\1+")

#: Applied in order.  Digraphs first, then single letters, so that the hush
#: sound written ``tch``/``ch``/``sh`` is not swallowed by the ``c -> k`` rule.
#: ``C`` is a sentinel: it cannot appear in the lower-cased input.
_PHONETIC_RULES: tuple[tuple[str, str], ...] = (
    ("tch", "C"), ("sh", "C"), ("ch", "C"),
    ("ph", "f"),
    ("qu", "k"), ("q", "k"),
    ("w", "u"),
    ("ou", "u"),
    ("x", "ks"),
    ("c", "k"),
    ("z", "s"),
    ("y", "i"),
    ("h", ""),
    ("C", "c"),
)


def phonetic_key(text: str) -> str:
    """Return a spelling-insensitive key for *text*.

    Transcribers of unwritten speech disagree about consonants far more than
    about the sound itself.  Collapsing those disagreements lets ``tchop`` and
    ``chop`` compare equal without loosening the edit-distance threshold for
    genuinely different words.
    """
    out = _NON_LETTER_RE.sub("", fold(text))
    for src, dst in _PHONETIC_RULES:
        out = out.replace(src, dst)
    out = _DOUBLE_RE.sub(r"\1", out)
    trimmed = out.rstrip("es")
    return trimmed or out


_VOWEL_RE = re.compile(r"[aeiou]+")


def consonant_key(text: str) -> str:
    """Return the consonant skeleton of *text*.

    Dropping vowels models the one thing transcribers agree on least.  It is a
    weaker signal than :func:`phonetic_key`, so it carries a smaller bonus and
    can only promote a candidate that already scored reasonably on letters.
    """
    out = _DOUBLE_RE.sub(r"\1", _NON_LETTER_RE.sub("", fold(text)))
    return _VOWEL_RE.sub("", out)


# --------------------------------------------------------------------------
# Candidate pool
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    """One proposed replacement for an unknown lexeme."""

    form: str
    token_type: str
    languages: tuple[str, ...]
    gloss: str
    score: float
    reason: str
    source: str

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.form} ({self.token_type}, {self.score:.2f})"


def _entries() -> list[tuple[str, tuple, str]]:
    """Every declared lexical entry as ``(form, spec, source)``."""
    rows = [(form, spec, "vocabulary") for form, spec in WORDS.items()]
    rows += [(form, spec, "phrase") for form, spec in PHRASES.items()]
    return rows


#: ``phonetic key -> declared forms``, built once because the specification is
#: immutable at run time.
_PHONETIC_INDEX: dict[str, list[str]] = {}

#: ``consonant skeleton -> declared forms``, built alongside it.
_SKELETON_INDEX: dict[str, list[str]] = {}

for _form, _spec, _src in _entries():
    _PHONETIC_INDEX.setdefault(phonetic_key(_form), []).append(_form)
    _SKELETON_INDEX.setdefault(consonant_key(_form), []).append(_form)


def _candidate(form: str, spec: tuple, score: float, reason: str,
               source: str) -> Candidate:
    ttype, langs, _slang, gloss = spec
    return Candidate(
        form=form,
        token_type=str(ttype),
        languages=tuple(str(l) for l in langs),
        gloss=gloss,
        score=round(min(score, 1.0), 4),
        reason=reason,
        source=source,
    )


def suggest_lexeme(lexeme: str, *, limit: int = MAX_SUGGESTIONS) -> list[Candidate]:
    """Rank declared entries by how plausibly *lexeme* was meant to be one."""
    key = fold(lexeme)
    if not key:
        return []
    same_sound = set(_PHONETIC_INDEX.get(phonetic_key(lexeme), ()))
    same_bones = set(_SKELETON_INDEX.get(consonant_key(lexeme), ()))

    scored: list[Candidate] = []
    for form, spec, source in _entries():
        base = similarity(key, form)
        if base < MIN_BASE:
            continue
        heard = form in same_sound
        boned = form in same_bones
        score = base
        if heard:
            score += PHONETIC_BONUS
        if boned:
            score += SKELETON_BONUS
        if score < MIN_SIMILARITY:
            continue
        if base >= 0.999:
            reason = "already declared"
        elif heard and base < 0.8:
            reason = "same sound, different spelling"
        elif heard:
            reason = "one or two letters out, and it sounds the same"
        elif boned:
            reason = "same consonants, the vowels were written differently"
        else:
            reason = f"{edit_distance(key, form)} letter edit(s) away"
        scored.append(_candidate(form, spec, score, reason, source))

    # Highest score first; ties resolved alphabetically so output is stable.
    scored.sort(key=lambda c: (-c.score, c.form))
    return scored[:limit]


def split_repair(lexeme: str) -> tuple[str, str] | None:
    """Return two declared words that *lexeme* appears to have run together.

    ``quartierla`` is the canonical case: both halves are in the vocabulary,
    but the transcriber did not leave a space.  Only splits where *both* parts
    are declared are returned, so this never invents a reading.
    """
    key = fold(lexeme)
    if len(key) < 4:
        return None
    for cut in range(2, len(key) - 1):
        left, right = key[:cut], key[cut:]
        if left in WORDS and right in WORDS:
            return left, right
    return None


# --------------------------------------------------------------------------
# Report objects
# --------------------------------------------------------------------------

@dataclass
class Suggestion:
    """Advice about one unknown lexeme."""

    lexeme: str
    line: int
    column: int
    candidates: list[Candidate] = field(default_factory=list)
    split: tuple[str, str] | None = None

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def confident(self) -> bool:
        """True when we are willing to put this into a rewritten sentence."""
        return self.best is not None and self.best.score >= CONFIDENT

    @property
    def replacement(self) -> str | None:
        """The text to substitute, preferring a split over a respelling."""
        if self.split is not None:
            return " ".join(self.split)
        return self.best.form if self.confident else None

    @property
    def advice(self) -> str:
        if self.split is not None:
            return (
                f'"{self.lexeme}" is two declared words written together; '
                f'separate them as "{" ".join(self.split)}".'
            )
        if self.confident:
            best = self.best
            assert best is not None
            return (
                f'"{self.lexeme}" is not declared; the closest entry is '
                f'"{best.form}" ({best.token_type}) \u2014 {best.reason}.'
            )
        if self.candidates:
            forms = ", ".join(f'"{c.form}"' for c in self.candidates[:3])
            return (
                f'"{self.lexeme}" is not declared and no entry is close enough '
                f"to assume; the nearest are {forms}."
            )
        return (
            f'"{self.lexeme}" is not declared and resembles nothing in the '
            "specification. If it is genuine Yaounde speech it belongs in the "
            "lexicon, not in a correction."
        )


@dataclass
class SyntaxHint:
    """Advice about a statement whose words are known but whose order is not."""

    message: str
    at_lexeme: str = ""
    line: int = 0
    column: int = 0
    expected: list[str] = field(default_factory=list)
    examples: dict[str, list[str]] = field(default_factory=dict)

    @property
    def advice(self) -> str:
        if not self.expected:
            return self.message
        shown = []
        for term in self.expected[:4]:
            sample = self.examples.get(term, [])
            if sample:
                shown.append(f'{term} (e.g. "{sample[0]}")')
            else:
                shown.append(term)
        where = f' before "{self.at_lexeme}"' if self.at_lexeme else ""
        return (
            f"The grammar expects one of {', '.join(shown)}{where}. "
            f"{self.message}"
        )


@dataclass
class CorrectionReport:
    """Everything the correction engine has to say about one analysis."""

    text: str
    accepted: bool
    kind: str                      # "none" | "lexical" | "syntax"
    headline: str
    suggestions: list[Suggestion] = field(default_factory=list)
    hint: SyntaxHint | None = None
    proposal: str = ""
    proposal_accepted: bool | None = None
    proposal_note: str = ""

    @property
    def has_proposal(self) -> bool:
        return bool(self.proposal) and self.proposal != self.text

    def lines(self) -> list[str]:
        """Plain-text rendering shared by the CLI and the desktop GUI."""
        out = [self.headline]
        for s in self.suggestions:
            out.append("  - " + s.advice)
            for c in s.candidates[:3]:
                gloss = f" \u2014 {c.gloss}" if c.gloss else ""
                out.append(
                    f"      {c.form:<18} {c.token_type:<7} {c.score:.2f}{gloss}"
                )
        if self.hint is not None:
            out.append("  - " + self.hint.advice)
        if self.has_proposal:
            out.append(f'  Proposed: "{self.proposal}"')
            if self.proposal_note:
                out.append("  " + self.proposal_note)
        return out


# --------------------------------------------------------------------------
# Examples per terminal, used to make an expected-set readable
# --------------------------------------------------------------------------

def _examples_by_type(limit: int = 3) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for form, spec, _source in _entries():
        name = str(spec[0])
        bucket = out.setdefault(name, [])
        if len(bucket) < limit:
            bucket.append(form)
    # Punctuation terminals are produced by regex rules, not the lexicon.
    out.setdefault(str(TokenType.TERM), ["."])
    out.setdefault(str(TokenType.SEP), [","])
    return out


EXAMPLES = _examples_by_type()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def _rewrite(text: str, tokens, suggestions: list[Suggestion]) -> str:
    """Splice confident replacements back into the original transcription."""
    by_lexeme = {
        s.lexeme: s.replacement for s in suggestions if s.replacement is not None
    }
    if not by_lexeme:
        return ""

    pieces: list[str] = []
    cursor = 0
    changed = False
    for tok in tokens:
        if str(tok.type) != str(TokenType.UNKNOWN):
            continue
        swap = by_lexeme.get(tok.lexeme)
        if swap is None:
            continue
        pieces.append(text[cursor:tok.start])
        pieces.append(swap)
        cursor = tok.end
        changed = True
    if not changed:
        return ""
    pieces.append(text[cursor:])
    return "".join(pieces)


def corrections(result, analyzer=None) -> CorrectionReport:
    """Explain *result* and, where possible, propose a corrected statement.

    *result* is a :class:`~yca.pipeline.StatementResult`.  Passing *analyzer*
    lets the engine verify its own proposal by re-analyzing it, which is the
    difference between advice and a checked claim.
    """
    if result.accepted:
        return CorrectionReport(
            text=result.text,
            accepted=True,
            kind="none",
            headline=(
                "Accepted. The statement is in the language; nothing to correct."
            ),
        )

    if not result.lex_ok:
        suggestions: list[Suggestion] = []
        for err in result.lex.errors:
            suggestions.append(
                Suggestion(
                    lexeme=err.lexeme,
                    line=err.line,
                    column=err.column,
                    candidates=suggest_lexeme(err.lexeme),
                    split=split_repair(err.lexeme),
                )
            )
        n = len(suggestions)
        headline = (
            f"Rejected in the lexical phase: {n} lexeme"
            f"{'' if n == 1 else 's'} outside the specification."
        )
        report = CorrectionReport(
            text=result.text,
            accepted=False,
            kind="lexical",
            headline=headline,
            suggestions=suggestions,
        )
        report.proposal = _rewrite(result.text, result.lex.tokens, suggestions)
        if report.has_proposal and analyzer is not None:
            retry = analyzer.analyze_text(report.proposal, trace=False)
            report.proposal_accepted = retry.accepted
            report.proposal_note = (
                "Re-analyzed: the proposal is accepted."
                if retry.accepted
                else f"Re-analyzed: still rejected \u2014 {retry.reason}"
            )
        elif report.has_proposal:
            report.proposal_note = "Not re-analyzed."
        return report

    tok = result.parse.error_token
    hint = SyntaxHint(
        message=result.parse.error,
        at_lexeme=tok.lexeme if tok is not None else "",
        line=tok.line if tok is not None else 0,
        column=tok.column if tok is not None else 0,
        expected=list(result.parse.expected),
        examples={t: EXAMPLES.get(t, []) for t in result.parse.expected},
    )
    return CorrectionReport(
        text=result.text,
        accepted=False,
        kind="syntax",
        headline=(
            "Rejected in the syntactic phase: every word is declared, but this "
            "order is not generated by the grammar."
        ),
        hint=hint,
    )
