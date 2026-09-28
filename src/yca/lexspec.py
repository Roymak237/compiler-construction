"""Lexical specification for informal Yaounde urban speech.

This module is the single source of truth for *what counts as a token*.  It
holds three layers, applied in this order:

1. ``PHRASES``  - multiword lexemes that must be recognised as one unit
                  (``je wanda``, ``small small``, ``cinq cents``).
2. ``WORDS``    - the closed vocabulary, one entry per normalized word form.
3. ``PATTERNS`` - regular expressions for open classes and punctuation.

Keeping the vocabulary declarative means the analyzer can be retargeted to a
different corpus by editing data, not code.

Normalization used for lookup
-----------------------------
Lookup keys are lower-cased, accent-folded and apostrophe-unified.  The *raw*
lexeme is always preserved on the token, so folding never destroys evidence of
how the speaker actually said it -- it only lets ``réseau`` and ``reseau`` be
recognised as the same dictionary entry.
"""

from __future__ import annotations

import re
import unicodedata

from .tokens import Language, TokenType

# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------

#: Apostrophe-like characters that transcribers mix freely.
_APOSTROPHES = "\u2018\u2019\u02bc\u00b4`"

_WS_RE = re.compile(r"\s+")


def fold(text: str) -> str:
    """Return the lookup key for *text*.

    Lower-cases, replaces curly apostrophes with ``'``, strips combining
    accents and collapses internal whitespace.
    """
    out = text.strip().lower()
    for ch in _APOSTROPHES:
        out = out.replace(ch, "'")
    out = unicodedata.normalize("NFKD", out)
    out = "".join(c for c in out if not unicodedata.combining(c))
    return _WS_RE.sub(" ", out)


# --------------------------------------------------------------------------
# Shorthand language tuples
# --------------------------------------------------------------------------

EN = (Language.ENGLISH,)
FR = (Language.FRENCH,)
PID = (Language.PIDGIN,)
CAM = (Language.CAMFRANGLAIS,)
EWO = (Language.EWONDO,)
FUL = (Language.FULFULDE,)
PROP = (Language.PROPER,)
EN_FR = (Language.ENGLISH, Language.FRENCH)
PID_FR = (Language.PIDGIN, Language.FRENCH)
PID_EN = (Language.PIDGIN, Language.ENGLISH)


# --------------------------------------------------------------------------
# 1. Multiword lexemes (longest match wins; order here is irrelevant because
#    the lexer sorts by descending word count).
# --------------------------------------------------------------------------

#: ``normalized phrase -> (type, languages, is_slang, gloss)``
PHRASES: dict[str, tuple[TokenType, tuple[Language, ...], bool, str]] = {
    # --- slang / interjections -------------------------------------------
    "je wanda": (TokenType.INTERJ, PID_FR, True, "I am amazed / unbelievable"),
    "zero zero": (TokenType.ADJ, CAM, True, "worthless, good for nothing"),
    "zero-zero": (TokenType.ADJ, CAM, True, "worthless, good for nothing"),
    "on est ensemble": (TokenType.INTERJ, FR, True, "we are together, solidarity"),
    "no wahala": (TokenType.INTERJ, PID, True, "no problem"),
    # --- adverbial reduplication -----------------------------------------
    "small small": (TokenType.ADV, PID, False, "little by little, intermittently"),
    "sharp sharp": (TokenType.ADV, PID, True, "immediately"),
    "quick quick": (TokenType.ADV, PID, False, "very quickly"),
    "na so": (TokenType.ADV, PID, False, "that is how it is"),
    # --- time expressions -------------------------------------------------
    "hier soir": (TokenType.NOUN, FR, False, "yesterday evening"),
    "ce matin": (TokenType.NOUN, FR, False, "this morning"),
    "la nuit": (TokenType.NOUN, FR, False, "the night"),
    # --- money ------------------------------------------------------------
    "cinq cents": (TokenType.NUM, FR, False, "five hundred francs"),
    "deux cents": (TokenType.NUM, FR, False, "two hundred francs"),
    "deux mille": (TokenType.NUM, FR, False, "two thousand francs"),
    "mille cinq": (TokenType.NUM, FR, False, "one thousand five hundred francs"),
    "trois mille": (TokenType.NUM, FR, False, "three thousand francs"),
    # --- address terms ----------------------------------------------------
    "bendskin man": (TokenType.VOC, PID_FR, True, "motorbike taxi rider"),
    "mon frere": (TokenType.VOC, FR, False, "my brother"),
    # --- compound nouns that behave as one unit ---------------------------
    "carte nationale": (TokenType.NOUN, FR, False, "national identity card"),
    "chop house": (TokenType.NOUN, PID_EN, False, "cheap eating house"),
    # --- interrogative amount, one unit in the numeral slot ----------------
    "how much": (TokenType.NUM, EN, False, "what price"),
    "combien": (TokenType.NUM, FR, False, "how much"),
    # --- multiword copula --------------------------------------------------
    "ce n'est pas": (TokenType.COP, FR, False, "it is not"),
}


# --------------------------------------------------------------------------
# 2. Closed vocabulary
# --------------------------------------------------------------------------

#: ``normalized word -> (type, languages, is_slang, gloss)``
WORDS: dict[str, tuple[TokenType, tuple[Language, ...], bool, str]] = {}


def _add(
    words: str,
    ttype: TokenType,
    languages: tuple[Language, ...],
    *,
    slang: bool = False,
    gloss: str = "",
) -> None:
    """Register every space-separated form in *words* under *ttype*."""
    for raw in words.split():
        WORDS[fold(raw)] = (ttype, languages, slang, gloss)


# --- vocatives -------------------------------------------------------------
_add("chef patron", TokenType.VOC, FR, gloss="boss, sir")
_add("mami", TokenType.VOC, PID, gloss="market woman, mother")
_add("boss", TokenType.VOC, EN, gloss="boss")
_add("mbom mola", TokenType.VOC, CAM, slang=True,
     gloss="Camfranglais address term: my friend, mate")
_add("ashia", TokenType.INTERJ, PID, gloss="sorry / well done")

# --- pronouns --------------------------------------------------------------
_add("i we you they he she it", TokenType.PRON, EN)
_add("me us them him her", TokenType.PRON, EN)
_add("am dem wuna", TokenType.PRON, PID, gloss="it/him, them, you (plural)")
_add("wetin", TokenType.PRON, PID, gloss="what (interrogative)")
_add("je tu il elle nous vous on", TokenType.PRON, FR)

# --- determiners -----------------------------------------------------------
_add("this that these those the my your our their his its", TokenType.DET, EN)
_add("ce cette ces le la les un une des mon ma mes ton ta tes son sa notre",
     TokenType.DET, FR)

# --- numerals (words; digits are handled by a pattern) ---------------------
_add("one two three four five ten", TokenType.NUM, EN)
_add("un deux trois quatre cinq dix cent cents mille", TokenType.NUM, FR)

# --- nouns -----------------------------------------------------------------
_add("taxi taximan driver road money market rain light water fuel queue "
     "student students phone network data price morning night time week "
     "problem people man woman place work compiler test",
     TokenType.NOUN, EN)
_add("carrefour quartier reseau connexion forfait courant carburant station "
     "boue chemin tomate beignets haricot devoir resultats lundi essence "
     "prof police controle facture marche moto bendskin",
     TokenType.NOUN, FR)
_add("tchop nga ndoss njoh", TokenType.NOUN, CAM, slang=True,
     gloss="Camfranglais everyday noun")
_add("wahala pikin dross", TokenType.NOUN, PID, gloss="trouble, child, clothes")
_add("own", TokenType.NOUN, PID, gloss="one's own, the thing belonging to")
_add("eneo camwater mtn orange nexttel camtel", TokenType.NOUN, PROP,
     gloss="utility or telecom operator")
_add("yaounde bastos nsimeyong mokolo mvog-ada mvan biyem-assi essos "
     "melen ngoa-ekelle obili damas etoudi", TokenType.NOUN, PROP,
     gloss="Yaounde neighbourhood or landmark")

# --- adjectives ------------------------------------------------------------
_add("long full sweet new old bad good fine hot cold ready last",
     TokenType.ADJ, EN)
_add("cher chere chaud froid plein vide nationale gros petit", TokenType.ADJ, FR)
_add("small", TokenType.ADJ, PID, gloss="small, a little")

# --- adverbs ---------------------------------------------------------------
_add("today tomorrow yesterday now here there again always quick "
     "well still", TokenType.ADV, EN)
_add("trop encore deja vraiment", TokenType.ADV, FR)
_add("sef", TokenType.ADV, PID, slang=True, gloss="even, emphatic")

# --- verbs -----------------------------------------------------------------
_add("drop come carry bring give take wait buy sell pay put cut "
     "finish die beat refuse reduce open close start stop use call send "
     "write read work find lose help understand talk hear see know happen",
     TokenType.VERB, EN)
_add("sabi waka", TokenType.VERB, PID,
     gloss="to know / to walk, to go")
_add("hala chop wanda tchatcher gomna", TokenType.VERB, CAM, slang=True,
     gloss="shout at / eat / wonder / chat / govern")
_add("commencer arreter payer acheter vendre", TokenType.VERB, FR)

# --- auxiliaries and aspect markers ---------------------------------------
_add("don dey de bin", TokenType.AUX, PID,
     gloss="perfective / progressive aspect marker")
_add("make fit must can will should would may", TokenType.AUX, EN)

# --- negation --------------------------------------------------------------
_add("no not never", TokenType.NEG, EN)
_add("pas", TokenType.NEG, FR)

# --- prepositions ----------------------------------------------------------
_add("for since with from at in on to about like without", TokenType.PREP, EN)
_add("pour depuis avec dans sur chez", TokenType.PREP, FR)
_add("go", TokenType.PREP, PID,
     gloss="directional marker in serial verb constructions: carry me go Mokolo")

# --- copula ----------------------------------------------------------------
_add("na", TokenType.COP, PID, gloss="equative copula: it is")
_add("be is are was were", TokenType.COP, EN)
WORDS[fold("c'est")] = (TokenType.COP, FR, False, "it is")

# --- conjunctions ----------------------------------------------------------
_add("and but or so because", TokenType.CONJ, EN)
_add("et mais ou donc", TokenType.CONJ, FR)

# --- interjections and discourse slang ------------------------------------
_add("hmmm hmm mmm ehh eh ah aah oh ooh wooh", TokenType.INTERJ, PID, slang=True,
     gloss="hesitation or exasperation cry")
_add("garrr garr", TokenType.INTERJ, CAM, slang=True,
     gloss="emphatic street exclamation")
_add("ekiee ekie", TokenType.INTERJ, EWO, slang=True,
     gloss="Ewondo cry of shock or dismay")
_add("weh wehh", TokenType.INTERJ, PID, slang=True, gloss="cry of pity")
_add("allo", TokenType.INTERJ, FR, gloss="hello")
_add("jamana", TokenType.INTERJ, FUL, slang=True, gloss="Fulfulde: the world / life")

# --- post-nominal particles ------------------------------------------------
_add("la", TokenType.PART, FR, gloss="deictic particle: that one there")
_add("o", TokenType.PART, PID, gloss="emphatic final particle")


# --------------------------------------------------------------------------
# 3. Regular-expression layer
# --------------------------------------------------------------------------

#: Ordered ``(rule name, compiled pattern, type, languages, slang)``.
#: The first pattern that matches at the current position wins, so the order
#: is part of the specification.
PATTERNS: list[tuple[str, re.Pattern[str], TokenType, tuple[Language, ...], bool]] = [
    (
        "R-MONEY",
        re.compile(r"\d{1,3}(?:[ .]\d{3})+|\d+\s*(?:frs?|fcfa|francs?)\b", re.I),
        TokenType.NUM,
        FR,
        False,
    ),
    ("R-NUM", re.compile(r"\d+"), TokenType.NUM, (Language.SYMBOL,), False),
    ("R-TERM", re.compile(r"[.!?]+"), TokenType.TERM, (Language.SYMBOL,), False),
    ("R-SEP", re.compile(r"[,;:]"), TokenType.SEP, (Language.SYMBOL,), False),
    (
        # Hesitation cries are productive: any long run of a vowel counts.
        "R-INTERJ",
        re.compile(r"(?:h?m{2,}|a{2,}h+|e{2,}h+|h+m+|w[eo]{2,}h*)", re.I),
        TokenType.INTERJ,
        PID,
        True,
    ),
    (
        # Reduplicated slang: garrr, waaah, yoooo
        "R-SLANG-LONG",
        re.compile(r"[a-z]*([a-z])\1{2,}[a-z]*", re.I),
        TokenType.INTERJ,
        CAM,
        True,
    ),
    (
        "R-WORD",
        re.compile(r"[A-Za-zÀ-ÿ]+(?:['\u2019-][A-Za-zÀ-ÿ]+)*"),
        TokenType.UNKNOWN,
        (Language.UNKNOWN,),
        False,
    ),
]

#: Characters the lexer silently skips (whitespace is handled separately).
IGNORE_RE = re.compile(r"[\"()\[\]]+")


# --------------------------------------------------------------------------
# Derived views used by the report
# --------------------------------------------------------------------------

def regex_documentation() -> list[tuple[str, str, str]]:
    """Return ``(rule, pattern, token type)`` rows for the report."""
    rows = [
        ("R-PHRASE", "longest multiword entry from PHRASES", "various"),
        ("R-VOCAB", "exact match against WORDS after folding", "various"),
    ]
    rows += [(name, pat.pattern, str(ttype)) for name, pat, ttype, _, _ in PATTERNS]
    return rows


def vocabulary_size() -> dict[str, int]:
    """Count declared lexical entries per token type."""
    counts: dict[str, int] = {}
    for ttype, *_ in WORDS.values():
        counts[str(ttype)] = counts.get(str(ttype), 0) + 1
    for ttype, *_ in PHRASES.values():
        counts[str(ttype)] = counts.get(str(ttype), 0) + 1
    return dict(sorted(counts.items()))
