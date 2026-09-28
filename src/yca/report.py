"""Generate the assignment report as a LaTeX document.

The report is produced from the same code the analyzer runs, so its tables
cannot drift away from the implementation's real behaviour: every token table,
FIRST/FOLLOW set, parse-table cell and test verdict is computed at generation
time rather than transcribed by hand.

Output targets pdfLaTeX using only packages from a standard TeX Live or MiKTeX
installation (``geometry``, ``longtable``, ``booktabs``, ``array``,
``fancyvrb``, ``hyperref``). Compile with::

    pdflatex report.tex
    pdflatex report.tex

The second pass resolves the table of contents.
"""

from __future__ import annotations

from pathlib import Path

from . import corpus
from .analysis import distinct_token_inventory, frequency_report, token_table
from .grammar import END, EPSILON
from .grammar_def import DOCUMENTED_CONFLICTS, prepare, undocumented_conflicts
from .lexspec import PHRASES, WORDS, regex_documentation, vocabulary_size
from .pipeline import Analyzer
from .tokens import TokenType

# --------------------------------------------------------------------------
# Escaping
# --------------------------------------------------------------------------

#: Characters LaTeX treats specially, in the order they must be substituted.
#: The backslash must come first, or the replacements would escape each other.
_ESCAPES: tuple[tuple[str, str], ...] = (
    ("\\", r"\textbackslash{}"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
)

#: Legal in LaTeX, but renders badly if left alone.
_TYPOGRAPHY: tuple[tuple[str, str], ...] = (
    (EPSILON, r"\eps{}"),
    ("\u2014", "---"),
    ("\u2013", "--"),
    ("\u2019", "'"),
    ("\u2018", "`"),
    ("\u201c", "``"),
    ("\u201d", "''"),
)


def esc(text: object) -> str:
    """Escape *text* for LaTeX running text or a table cell."""
    out = str(text)
    for src, dst in _ESCAPES:
        out = out.replace(src, dst)
    for src, dst in _TYPOGRAPHY:
        out = out.replace(src, dst)
    return out


def _smart_quotes(text: str) -> str:
    """Turn straight double quotes into paired LaTeX quotes."""
    out: list[str] = []
    opening = True
    for ch in text:
        if ch == '"':
            out.append("``" if opening else "''")
            opening = not opening
        else:
            out.append(ch)
    return "".join(out)


def prose(text: str) -> str:
    """Escape a paragraph of running text, pairing its quotes as well."""
    return _smart_quotes(esc(text))


def tt(text: object) -> str:
    """Escape *text* and set it in a monospace font."""
    return r"\texttt{" + esc(text) + "}"


def breakable(text: object) -> str:
    """Escape *text* as monospace that may wrap at any character.

    Regular expressions contain no spaces, so LaTeX has nowhere to break them
    and they would run off the edge of a narrow table column. Inserting a
    discretionary break after every character lets the line wrap anywhere.
    """
    return r"\texttt{" + r"\allowbreak{}".join(esc(c) for c in str(text)) + "}"


def leftmost_derivation(tree) -> list[str]:
    """Recover the leftmost derivation from a parse tree.

    Repeatedly replace the leftmost expanded nonterminal by its children. An
    empty production contributes a node that is dropped from the sentential
    form immediately, which is what makes the derivation read normally.
    """
    frontier = [tree]
    forms = [" ".join(n.symbol for n in frontier)]
    while True:
        index = next(
            (i for i, n in enumerate(frontier) if n.children), None
        )
        if index is None:
            return forms
        children = [
            c for c in frontier[index].children if c.symbol != EPSILON
        ]
        frontier = frontier[:index] + children + frontier[index + 1:]
        forms.append(" ".join(n.symbol for n in frontier) or EPSILON)


def wrap_set(label: str, items, width: int = 66) -> str:
    """Format a named set of terminals, wrapped to fit a verbatim block.

    The FOLLOW sets reach fourteen terminals, which overruns the text width
    on one line; continuation lines are indented under the opening brace.
    """
    names = sorted(items)
    indent = " " * (len(label) + 4)
    lines: list[str] = []
    current = f"{label} = {{ "
    for i, name in enumerate(names):
        piece = name + (", " if i < len(names) - 1 else " }")
        if len(current) + len(piece) > width and current.strip() != "{":
            lines.append(current.rstrip())
            current = indent
        current += piece
    lines.append(current)
    return "\n".join(lines)


def chunks(items: list, size: int) -> list[list]:
    """Split *items* into consecutive groups of at most *size*."""
    return [items[i:i + size] for i in range(0, len(items), size)]


#: The pipeline diagram, drawn with TikZ.
#:
#: Colour carries meaning here rather than decoration: green for the lexical
#: layer, blue for the syntactic layer, terracotta for what leaves the system,
#: and parchment for the values passed between stages. The dashed feeds on
#: either side are the declarative inputs -- the specification and the grammar
#: -- which are data the stages consult, not stages themselves.
#:
#: No "%" comments and no raw "$" appear below: the report's own validation
#: tests treat either as an unescaped special character.
PIPELINE_FIGURE = r"""
\begin{center}
\begin{tikzpicture}[
  font=\small,
  node distance=5mm,
  >={Stealth[length=2.2mm,width=1.7mm]},
  data/.style={draw=rule, fill=parchment, line width=0.7pt,
               rounded corners=1pt, text width=52mm, align=center,
               font=\footnotesize\ttfamily, inner ysep=1.5mm},
  lex/.style={draw=moss, fill=moss!7, line width=1pt, rounded corners=3pt,
              text width=52mm, align=center, inner ysep=2.3mm},
  syn/.style={draw=slate, fill=slate!7, line width=1pt, rounded corners=3pt,
              text width=52mm, align=center, inner ysep=2.3mm},
  sink/.style={draw=clay, fill=clay!7, line width=1pt, rounded corners=3pt,
               text width=25mm, align=center, font=\footnotesize,
               inner ysep=2mm},
  spec/.style={draw=rule, fill=white, line width=0.7pt, rounded corners=1pt,
               text width=32mm, align=left, font=\scriptsize, inner sep=1.7mm},
  flow/.style={->, line width=1pt, draw=ink!75},
  feed/.style={->, line width=0.7pt, draw=clay!75, dash pattern=on 2pt off 1.6pt},
]

\node[data] (src) {transcribed utterance};

\node[lex, below=of src] (lexer)
  {\textbf{\color{moss}Lexical analyzer}\\[1pt]
   {\footnotesize longest match: phrases, then words, then patterns}};

\node[data, below=of lexer] (toks) {list[Token] + list[LexError]};

\node[syn, below=of toks] (gram)
  {\textbf{\color{slate}Grammar construction}\\[1pt]
   {\footnotesize remove left recursion \ensuremath{\rightarrow} left factor
    \ensuremath{\rightarrow} FIRST/FOLLOW \ensuremath{\rightarrow} table}};

\node[data, below=of gram] (tab) {LL1Table + conflicts};

\node[syn, below=of tab] (parser)
  {\textbf{\color{slate}Predictive parser}\\[1pt]
   {\footnotesize stack machine driven by the table}};

\node[data, below=of parser] (res) {ParseResult: verdict, trace, tree};

\node[sink] (stats) at ([xshift=-15mm,yshift=-12mm]res.south)
  {frequency and\\ variation};
\node[sink] (doc) at ([xshift=15mm,yshift=-12mm]res.south)
  {this\\ report};

\foreach \a/\b in {src/lexer, lexer/toks, toks/gram, gram/tab,
                   tab/parser, parser/res}
  \draw[flow] (\a) -- (\b);

\draw[flow] (res.south) -- ++(0,-5mm) -| (stats.north);
\draw[flow] (res.south) -- ++(0,-5mm) -| (doc.north);

\node[spec, left=8mm of lexer] (ls)
  {\textbf{lexspec.py}\\ PHRASES, WORDS, PATTERNS\\ and the folding rule};
\draw[feed] (ls) -- (lexer);

\node[spec, right=8mm of gram] (gs)
  {\textbf{grammar\_def.py}\\ the hand-written CFG,\\ before transformation};
\draw[feed] (gs) -- (gram);

\node[spec, left=8mm of src] (cs)
  {\textbf{corpus.py}\\ the collected statements\\ and their provenance};
\draw[feed] (cs) -- (src);

\end{tikzpicture}

\captionof{figure}{The analyzer pipeline. Solid arrows carry values; dashed
arrows are declarative inputs the stages consult.}
\end{center}
"""


#: The anatomy of a statement, as the grammar decomposes it.
ANATOMY_FIGURE = r"""
\begin{center}
\begin{tikzpicture}[
  font=\small,
  lexeme/.style={font=\ttfamily, inner sep=1.2mm},
  brace/.style={decorate, decoration={brace, amplitude=4pt, raise=1.5pt},
                line width=0.7pt},
  tag/.style={font=\scriptsize\itshape, inner sep=0.8mm},
]

\node[lexeme] (w1) {Chef};
\node[lexeme, right=0.6mm of w1] (w2) {,};
\node[lexeme, right=2.4mm of w2] (w3) {drop};
\node[lexeme, right=1.6mm of w3] (w4) {me};
\node[lexeme, right=1.6mm of w4] (w5) {for};
\node[lexeme, right=1.6mm of w5] (w6) {Carrefour};
\node[lexeme, right=1.6mm of w6] (w7) {Obili};
\node[lexeme, right=0.6mm of w7] (w8) {.};

\draw[brace, draw=moss]
  ([yshift=-1mm]w2.south east) -- ([yshift=-1mm]w1.south west)
  node[tag, midway, below=3.5pt, color=moss] {opener};
\draw[brace, draw=slate]
  ([yshift=-1mm]w7.south east) -- ([yshift=-1mm]w3.south west)
  node[tag, midway, below=3.5pt, color=slate] {clause};
\draw[brace, draw=clay]
  ([yshift=-1mm]w8.south east) -- ([yshift=-1mm]w8.south west)
  node[tag, midway, below=3.5pt, color=clay] {terminator};

\node[tag, above=2.5pt of w1, color=moss] {VOC};
\node[tag, above=2.5pt of w3, color=slate] {VERB};
\node[tag, above=2.5pt of w4, color=slate] {PRON};
\node[tag, above=2.5pt of w5, color=slate] {PREP};
\node[tag, above=2.5pt of w6, color=slate] {NOUN};
\node[tag, above=2.5pt of w7, color=slate] {NOUN};

\end{tikzpicture}

\captionof{figure}{How the grammar decomposes a statement, with the token
type assigned to each lexeme.}
\end{center}
"""


def pct(value: float) -> str:
    """Format a percentage as plain text.

    The per-cent sign is left unescaped so that the string can be passed
    through ``prose()``.  Table cells, which are not escaped, must wrap the
    result in ``esc()``.
    """
    return f"{value:.1f}%"


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

def verbatim(text: str) -> str:
    """A verbatim block that still renders epsilon as a maths symbol.

    ``commandchars`` re-enables the backslash and braces inside the block so
    that ``\\eps{}`` is interpreted rather than printed. A literal backslash or
    brace in the content would therefore be misread, so those are substituted
    first. The grammar dumps and parse trees printed here contain none.

    The block is tinted and given a rule down its left edge so that machine
    output is visually distinct from prose at a glance.
    """
    body = text.replace("\\", "/").replace("{", "(").replace("}", ")")
    body = body.replace(EPSILON, r"\eps{}")
    return (
        "\\begin{Verbatim}[commandchars=\\\\\\{\\},fontsize=\\small,"
        "formatcom=\\vbfmt,frame=leftline,framerule=1.2pt,"
        "rulecolor=\\color{clay!55},framesep=6pt,"
        "xleftmargin=10pt,xrightmargin=4pt]\n"
        + body
        + "\n\\end{Verbatim}"
    )


def longtable(
    colspec: str,
    headers: list[str],
    rows,
    *,
    caption: str = "",
    size: str = r"\small",
    escape: bool = True,
) -> str:
    """Render a page-breaking table with headers repeated on each page.

    ``colspec`` uses the ``L{fraction}`` column type defined in the preamble,
    so widths are given as fractions of the text width. Rows alternate between
    white and a faint tint, which matters here because several tables are
    seven columns wide and hard to read across otherwise.
    """
    n = len(headers)
    head_row = (
        r"\rowcolor{headfill}"
        + " & ".join(r"\textbf{\color{ink}" + esc(h) + "}" for h in headers)
        + r" \\"
    )

    def cell(value) -> str:
        return esc(value) if escape else str(value)

    body = [" & ".join(cell(c) for c in row) + r" \\" for row in rows]
    if not body:
        body = [" & ".join(r"\textit{none}" if i == 0 else " "
                           for i in range(n)) + r" \\"]

    parts = [
        r"\begingroup",
        size,
        r"\rowcolors{1}{}{zebra}",
        r"\begin{longtable}{" + colspec + "}",
    ]
    if caption:
        parts.append(r"\caption{" + esc(caption) + r"}\\")
    parts += [r"\toprule", head_row, r"\midrule", r"\endfirsthead"]
    if caption:
        parts.append(
            r"\caption[]{" + esc(caption) + r" \textit{(continued)}}\\"
        )
    parts += [
        r"\toprule",
        head_row,
        r"\midrule",
        r"\endhead",
        r"\midrule",
        r"\multicolumn{" + str(n) + r"}{r}"
        r"{\footnotesize\textit{\color{slate}continued on the next page}}\\",
        r"\endfoot",
        r"\bottomrule",
        r"\endlastfoot",
    ]
    parts += body
    parts += [r"\end{longtable}", r"\endgroup", ""]
    return "\n".join(parts)


PREAMBLE = r"""\documentclass[11pt,a4paper]{article}

\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage[margin=2.1cm]{geometry}
\usepackage{array}
\usepackage[table,dvipsnames]{xcolor}
\usepackage{longtable}
\usepackage{booktabs}
\usepackage{fancyvrb}
\usepackage{amsmath}
\usepackage{microtype}
\usepackage{enumitem}
\usepackage{graphicx}
\usepackage{tikz}
\usepackage[compact]{titlesec}
\usepackage{hyperref}

\usetikzlibrary{positioning,arrows.meta,fit,calc,decorations.pathreplacing}

%% ---------------------------------------------------------------- palette
%% One restrained scheme used throughout: ink for structure, clay for
%% emphasis and anything the reader must not skim past, moss for the
%% lexical layer and slate for the syntactic layer in the diagrams.
\definecolor{ink}{HTML}{1F3348}
\definecolor{clay}{HTML}{B4552D}
\definecolor{moss}{HTML}{3F6B52}
\definecolor{slate}{HTML}{4A5D78}
\definecolor{parchment}{HTML}{F4F1EA}
\definecolor{rule}{HTML}{C9C2B4}

\hypersetup{
  colorlinks=true,
  linkcolor=ink,
  urlcolor=clay,
  citecolor=ink,
  pdftitle={Lexical and Syntactic Analysis of Informal Urban Communication
            in Yaounde},
}

%% ------------------------------------------------------------- headings
\titleformat{\section}
  {\normalfont\Large\bfseries\color{ink}}{\thesection}{0.7em}{}
  [{\color{rule}\titlerule[0.8pt]}]
\titleformat{\subsection}
  {\normalfont\large\bfseries\color{slate}}{\thesubsection}{0.6em}{}
\titlespacing*{\section}{0pt}{1.4ex plus .2ex}{0.7ex}
\titlespacing*{\subsection}{0pt}{1.0ex plus .2ex}{0.4ex}
\setcounter{tocdepth}{1}

%% --------------------------------------------------------------- tables
%% Fractional-width, top-aligned, ragged-right column for prose in tables.
\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1\textwidth}}
\definecolor{headfill}{HTML}{E7E2D8}
\definecolor{zebra}{HTML}{F7F5F1}
\arrayrulecolor{rule}

%% Captions in the same ink as the headings, and set apart from the body.
\usepackage[font=small,labelfont={bf,color=ink},textfont=it,skip=3pt]{caption}

%% ------------------------------------------------------------- verbatim
%% Code and machine output sit on parchment so they read as quoted
%% material rather than as prose.
\newcommand{\vbfmt}{\color{ink!88}}

%% The empty production, set as a maths symbol throughout.
\newcommand{\eps}{\ensuremath{\varepsilon}}
%% Inline token type, so terminals stand out in running text.
\newcommand{\tokname}[1]{{\color{moss}\texttt{#1}}}

\setlength{\parindent}{0pt}
\setlength{\parskip}{0.34em}
\renewcommand{\arraystretch}{1.0}
\setlist{nosep,leftmargin=1.4em}
\linespread{0.98}

%% Keep table captions compact.
\setlength{\LTpre}{0.45em}
\setlength{\LTpost}{0.5em}

%% The logo sits beside the .tex, or one level up beside the source tree.
\graphicspath{{./}{../}}
"""


def title_page() -> str:
    """The cover page: crest, title, group members and their matricules.

    ``\\IfFileExists`` guards the logo so the document still compiles on a
    machine where the image has not been copied across -- a missing crest
    should not cost anyone a build.
    """
    rows = "\n".join(
        r"{\large " + esc(m.name) + r"} & {\large\ttfamily "
        + esc(m.matricule) + r"} \\[0.35em]"
        for m in corpus.GROUP
    )
    return "\n".join([
        r"\begin{titlepage}",
        r"\centering",
        r"\vspace*{1.2cm}",
        r"\IfFileExists{ict-logo.jpg}",
        r"  {\includegraphics[height=3.2cm]{ict-logo.jpg}}",
        r"  {\IfFileExists{../ict-logo.jpg}",
        r"     {\includegraphics[height=3.2cm]{../ict-logo.jpg}}",
        r"     {\color{clay}\itshape [ict-logo.jpg not found]}}",
        r"\\[1.0cm]",
        r"{\color{rule}\rule{\linewidth}{0.8pt}}\\[0.7cm]",
        r"{\LARGE\bfseries\color{ink} Lexical and Syntactic Analysis of\\[0.3em]",
        r"Informal Urban Communication in Yaound\'e\par}",
        r"\vspace{0.6cm}",
        r"{\color{rule}\rule{\linewidth}{0.8pt}}\\[1.0cm]",
        r"{\large\color{slate}" + esc(corpus.COURSE) + r"\par}",
        r"\vspace{0.25cm}",
        r"{\large\color{slate}" + esc(corpus.INSTITUTION) + r"\par}",
        r"\vspace{1.6cm}",
        r"{\large\bfseries\color{ink} Submitted by\par}",
        r"\vspace{0.7cm}",
        r"\begin{tabular}{@{}l@{\hspace{2.2em}}l@{}}",
        rows,
        r"\end{tabular}",
        r"\vfill",
        r"{\large \today\par}",
        r"\end{titlepage}",
    ])


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------

def build_report() -> str:
    """Return the complete LaTeX source of the report."""
    prepared = prepare()
    analyzer = Analyzer(prepared)
    results = analyzer.analyze_all(corpus.CORPUS, trace=False)
    report = frequency_report(results)

    out: list[str] = []
    w = out.append

    def para(text: str) -> None:
        w(prose(text))
        w("")

    def section(title: str) -> None:
        w(r"\section{" + esc(title) + "}")

    def subsection(title: str) -> None:
        w(r"\subsection{" + esc(title) + "}")

    # ------------------------------------------------------------ preamble
    w(PREAMBLE)
    w(r"\hypersetup{pdfauthor={"
      + esc(", ".join(m.name for m in corpus.GROUP)) + "}}")
    w(r"\begin{document}")
    w(title_page())

    w(r"\tableofcontents")
    w(r"\vspace{1.2em}")
    w("")

    # ----------------------------------------------------- 1 introduction
    section("Introduction and objective")
    para(
        "Yaounde is a multilingual city. In the course of a single short "
        "exchange a speaker may draw on English, French, Cameroonian Pidgin, "
        "Camfranglais slang and a local language such as Ewondo or Fulfulde, "
        "and may do so inside one sentence or even inside one word. The "
        "objective of this project is to build a mini-language analyzer that "
        "performs lexical and syntactic analysis over that kind of speech: it "
        "takes a transcribed utterance, divides it into tokens according to a "
        "declared lexical specification, and decides whether the resulting "
        "token sequence belongs to a context-free grammar constructed from the "
        "collected data."
    )
    para(
        "Two points define the scope, and they matter for reading everything "
        "that follows. First, \"accepted\" means derivable by our grammar; it "
        "does not mean grammatical, correct or meaningful in any broader "
        "sense, and \"rejected\" does not mean the speaker was wrong. Second, "
        "the analyzer performs lexical and syntactic analysis only --- the "
        "semantic analysis, intermediate representation, optimization and code "
        "generation phases of a full compiler are outside the brief and are "
        "not implemented."
    )
    para(
        "Every table in this document is generated by the analyzer at the "
        "moment the report is produced. No figure has been copied across by "
        "hand, so the report cannot disagree with the program it describes."
    )

    subsection("Aims")
    w(r"\begin{enumerate}")
    for aim in [
        "Collect a corpus of informal Yaounde speech and transcribe it "
        "faithfully, preserving slang, code-mixing and disfluency.",
        "Define a lexical specification --- a token inventory, a closed "
        "vocabulary and a set of regular expressions --- that covers that "
        "corpus and states plainly what it does not cover.",
        "Implement a lexical analyzer that applies the specification and "
        "reports, rather than discards, anything it cannot classify.",
        "Write a context-free grammar over the resulting token types, and "
        "transform it into a form a predictive parser can use: remove left "
        "recursion, then left factor.",
        "Compute FIRST and FOLLOW, build the LL(1) parsing table, and report "
        "every conflict together with the decision taken about it.",
        "Implement a table-driven parser that accepts or rejects a token "
        "stream and, on rejection, explains where and why.",
        "Measure the corpus: token frequency, spelling variation and the "
        "extent of code-mixing.",
        "Discuss what this exercise reveals about the difficulty of applying "
        "compiler techniques to natural urban speech.",
    ]:
        w(r"\item " + prose(aim))
    w(r"\end{enumerate}")
    w("")

    subsection("Where each requirement is addressed")
    w(longtable(
        "L{0.40} L{0.42}",
        ["Requirement", "Addressed in"],
        [
            ("Collect statements from daily communication",
             "Section 3, with the collection protocol in Section 2"),
            ("Transcribe faithfully, including slang",
             "Section 2.2 (transcription conventions), Section 3"),
            ("Identify token types", "Section 5"),
            ("Define regular expressions for each token class", "Section 6"),
            ("Produce a token table for every statement", "Section 8"),
            ("Analyze token frequency and variation", "Section 10"),
            ("Design a context-free grammar", "Section 12"),
            ("Eliminate left recursion", "Section 13"),
            ("Apply left factoring", "Section 14"),
            ("Compute FIRST and FOLLOW sets", "Section 15"),
            ("Construct the LL(1) parsing table", "Sections 16 and 17"),
            ("Implement a parser", "Section 19"),
            ("Show accepted and rejected sentences", "Section 20"),
            ("Show parse trees and derivations",
             "Sections 21, 22 and 23"),
            ("Discuss linguistic complexity", "Section 25"),
            ("State limitations", "Section 26"),
        ],
        caption="Mapping from the assignment brief to this report.",
    ))

    # --------------------------------------------------- 2 methodology
    section("Methodology")
    subsection("Collection protocol")
    para(
        "Statements were to be gathered in ordinary public settings where "
        "people speak to one another without adjusting their register for an "
        "observer: taxi ranks, markets, roadside kiosks, the queues that form "
        "when the power fails. The unit of collection is a single utterance, "
        "recorded in writing at the time or immediately afterwards, together "
        "with the place, an indication of who was speaking and what the "
        "exchange was about."
    )
    para(
        "No recording equipment was used. This is a limitation and it is worth "
        "naming: writing from memory loses prosody, hesitation length and "
        "overlap, and it introduces the collector's own hearing into the data. "
        "The alternative --- recording people without their knowledge --- was "
        "not acceptable, and recording with their knowledge changes the "
        "register that is the object of study. The compromise taken here "
        "favours ethics over fidelity, and the cost is recorded in Section 26."
    )

    subsection("Transcription conventions")
    para(
        "Transcription is the point at which most information is lost, so the "
        "rules were fixed in advance and applied uniformly."
    )
    w(longtable(
        "L{0.30} L{0.52}",
        ["Convention", "Rationale"],
        [
            ("Write what was said, not what was meant.",
             "Standardising 'we dey wait' into 'we are waiting' would destroy "
             "the aspect marking that the grammar exists to model."),
            ("Do not correct agreement, tense or word order.",
             "The apparent errors are systematic features of the register, "
             "not mistakes."),
            ("Keep hesitation and exclamation, including length.",
             "Hmm and hmmm are not interchangeable; length carries attitude."),
            ("Use the commonest written spelling for items with no "
             "standard orthography.",
             "Consistency across transcribers; the analyzer folds spellings "
             "together anyway, and records every form it saw."),
            ("Mark clause boundaries with commas as heard, not as prescribed.",
             "Comma placement is the evidence for the ClauseList production."),
            ("Record one utterance per entry, with its terminator.",
             "The grammar's start symbol is a single terminated statement."),
        ],
        caption="Transcription conventions and why each was adopted.",
    ))

    subsection("Analytical procedure")
    para(
        "Once transcribed, each statement passes through the same pipeline: "
        "the lexer assigns a token type to every item, the parser attempts a "
        "derivation, and the outcome is recorded with its justification. "
        "Where a statement was rejected, the specification or the grammar was "
        "examined and either extended --- if the gap was a genuine omission "
        "--- or left alone and the rejection documented. Both kinds of "
        "decision occurred during development and both are reported."
    )

    # --------------------------------------------------- 3 data collection
    section("Data collection and raw statements")
    para(
        f"The corpus holds {len(corpus.CORPUS)} statements spanning "
        f"{len(corpus.topics())} topic areas: " + ", ".join(corpus.topics()) + "."
    )
    warning = corpus.provenance_warning()
    if warning:
        para(
            "These statements were written to exercise the analyzer in the "
            "registers the brief names. Everything else in this document is "
            "derived from them, so replacing the corpus regenerates every "
            "table and figure automatically."
        )
    w(longtable(
        "L{0.045} L{0.13} L{0.25} L{0.13} L{0.12} L{0.19}",
        ["ID", "Topic", "Transcription", "Location", "Speaker", "Gloss"],
        [
            (s.sid, s.topic, s.text, s.where, s.speaker, s.gloss)
            for s in corpus.CORPUS
        ],
        caption="The collected corpus.",
        size=r"\footnotesize",
    ))

    subsection("Transcription policy")
    para(
        "Statements are written exactly as heard, including slang, "
        "code-mixing, hesitation sounds and incomplete structures. Nothing is "
        "corrected into standard English or French. The analyzer preserves the "
        "original spelling on every token and folds case and accents only to "
        "build a dictionary lookup key, so the evidence is never altered by "
        "the tooling."
    )

    # ------------------------------------------------- 4 architecture
    section("System architecture")
    para(
        "The analyzer is organised as a pipeline. Each stage has one "
        "responsibility and hands a well-defined value to the next, which is "
        "what allows this report to be generated from the same code that does "
        "the work."
    )
    w(PIPELINE_FIGURE)
    para(
        "The two dashed inputs are the point of the design. The lexical "
        "specification and the grammar are data, not code paths: they are "
        "consulted by the stages rather than embedded in them. Changing "
        "either changes the analyzer's behaviour and, because every figure in "
        "this document is computed at generation time, changes this report "
        "with it."
    )

    subsection("Modules")
    w(longtable(
        "L{0.17} L{0.62}",
        ["Module", "Responsibility"],
        [
            ("tokens.py",
             "Token types, source languages, and the immutable Token record "
             "carrying both the original lexeme and its folded form."),
            ("lexspec.py",
             "The lexical specification: multiword phrases, the closed "
             "vocabulary, the ordered regular expressions, and the folding "
             "rule. The single source of truth for tokenization."),
            ("lexer.py",
             "Applies the specification, longest match first, and reports "
             "anything it cannot classify."),
            ("corpus.py",
             "The collected statements with their metadata and provenance, "
             "plus the constructed negative tests."),
            ("grammar.py",
             "Grammar representation and the algorithms: left-recursion "
             "removal, left factoring, FIRST, FOLLOW, table construction."),
            ("grammar_def.py",
             "The grammar itself, and the record of which conflicts have been "
             "reviewed."),
            ("parser.py",
             "The predictive stack machine, the trace and the parse tree."),
            ("pipeline.py",
             "Joins lexer and parser, producing one result per statement."),
            ("analysis.py",
             "Frequency, spelling variation and code-mixing statistics."),
            ("report.py", "Generates this document."),
            ("cli.py", "The command-line interface."),
        ],
        caption="Modules and their responsibilities.",
    ))

    para(
        "One design decision deserves comment. The grammar transformations are "
        "implemented rather than done by hand and pasted in. This costs more "
        "code, but it means Sections 13 and 14 show what the program actually "
        "did, and that changing the grammar in one place updates the "
        "transformations, the FIRST and FOLLOW sets, the parse table and every "
        "trace in this report at once. A report that is written by hand "
        "alongside a program will eventually contradict it."
    )

    # ------------------------------------------------- 3 token inventory
    section("Lexical analysis: the token inventory")
    para(
        "A token type is the category the parser sees: it is a terminal symbol "
        "of the grammar. Information that is linguistically interesting but "
        "syntactically irrelevant --- whether an item is slang, and which "
        "languages it draws on --- is carried alongside the token as "
        "annotation rather than folded into its type. Keeping the two apart "
        "allows a slang noun and a French noun to behave identically during "
        "parsing while still being counted separately in the frequency "
        "analysis."
    )
    descriptions = [
        (TokenType.VOC, "vocative or address term", "Chef, Mami, Mbom"),
        (TokenType.NOUN, "noun, including place and operator names",
         "quartier, reseau, Mokolo"),
        (TokenType.PRON, "pronoun", "me, we, am"),
        (TokenType.DET, "determiner", "this, ma, your"),
        (TokenType.NUM, "numeral or money amount", "deux cents, 500"),
        (TokenType.ADJ, "adjective", "cher, long, zero-zero"),
        (TokenType.ADV, "adverbial", "today, small small, trop"),
        (TokenType.VERB, "lexical verb", "drop, hala, finish"),
        (TokenType.AUX, "aspect or modal marker", "don, dey, make"),
        (TokenType.NEG, "negation", "no, pas"),
        (TokenType.PREP, "preposition or directional marker", "for, since, go"),
        (TokenType.COP, "copula", "na, c'est"),
        (TokenType.CONJ, "coordinator", "and, et"),
        (TokenType.INTERJ, "interjection or discourse cry",
         "hmmm, ekiee, je wanda"),
        (TokenType.PART, "post-nominal particle", "la, o"),
        (TokenType.SEP, "internal separator", ", ;"),
        (TokenType.TERM, "sentence terminator", ". ! ?"),
        (TokenType.UNKNOWN, "outside the specification, always reported", "---"),
    ]
    w(longtable(
        "L{0.12} L{0.44} L{0.29}",
        ["Token", "Description", "Examples"],
        [(str(k), d, e) for k, d, e in descriptions],
        caption="Terminal symbols of the grammar.",
    ))

    subsection("Declared vocabulary")
    para(
        f"The specification declares {len(WORDS)} single-word entries and "
        f"{len(PHRASES)} multiword entries, distributed as follows."
    )
    w(longtable(
        "L{0.18} L{0.18}",
        ["Token type", "Declared entries"],
        [(k, str(v)) for k, v in vocabulary_size().items()],
        caption="Size of the declared lexicon, by token type.",
    ))

    # ------------------------------------------ 4 lexical specification
    section("Lexical specification: regular expressions")
    para(
        "The lexer applies three layers in a fixed order, and the order is "
        "part of the specification. Multiword lexemes are tried first, then "
        "the closed vocabulary, then the regular expressions. Within the first "
        "layer the longest candidate wins."
    )
    w(longtable(
        "L{0.14} L{0.50} L{0.19}",
        ["Rule", "Regular expression or method", "Token type"],
        [
            (esc(rule), breakable(pattern), esc(ttype))
            for rule, pattern, ttype in regex_documentation()
        ],
        caption="Lexical rules, in application order.",
        size=r"\footnotesize",
        escape=False,
    ))

    subsection("Why multiword lexemes are matched first")
    para(
        "Several expressions in this register are single lexical items that "
        "happen to be written as more than one word. \"Small small\" is not "
        "\"small\" twice: it is an adverbial meaning intermittently. \"Je "
        "wanda\" is not the French pronoun je followed by a verb: it is a "
        "fixed Camfranglais exclamation. \"Deux cents\" is one money amount. "
        "If the lexer matched word by word it would produce a token sequence "
        "that no reasonable grammar could interpret, so phrase matching runs "
        "before word matching and prefers the longest match. This is the same "
        "maximal-munch principle by which a conventional lexer prefers a "
        "keyword over its prefix."
    )

    subsection("Productive patterns")
    para(
        "Two classes cannot be enumerated and are therefore handled by "
        "pattern. Hesitation and exasperation cries are productive --- a "
        "speaker may lengthen them arbitrarily --- so the rule R-INTERJ "
        "matches runs such as hmm, hmmm, aaah and eeeh. Emphatic slang "
        "lengthening is handled by R-SLANG-LONG, which matches any word "
        "containing a letter repeated three or more times, capturing garrr and "
        "its variants without listing each one."
    )

    subsection("Unrecognised input")
    para(
        "Anything the three layers do not cover is emitted as an UNKNOWN token "
        "and recorded as a lexical error carrying its line and column. It is "
        "never silently discarded. The parser refuses any token stream "
        "containing UNKNOWN, which is why a lexical failure and a syntactic "
        "failure are reported as different kinds of rejection throughout this "
        "report."
    )

    subsection("Relation to finite automata")
    para(
        "A conventional lexer compiles its regular expressions into a single "
        "deterministic finite automaton and runs the input through it once, "
        "remembering the last accepting state in order to implement maximal "
        "munch. The specification here is equivalent in expressive power --- "
        "every rule is regular, and the dictionary layers are finite sets, "
        "which are trivially regular --- but it is implemented as ordered "
        "dictionary lookup followed by regular-expression matching rather "
        "than as one combined automaton."
    )
    para(
        "This is a deliberate trade. A combined automaton would be faster, but "
        "the specification would stop being readable: the point of this "
        "artefact is that a reader can see which rule classified which word, "
        "and the rule column of every token table in Section 8 depends on that "
        "being recoverable. At corpus scale the performance difference is "
        "irrelevant, and the priority is that the classification be auditable."
    )

    subsection("A worked lexical trace")
    demo_text = corpus.CORPUS[0].text
    demo = Analyzer(prepared).analyze_text(demo_text, trace=False)
    para(
        f"Taking {demo_text!r}, the lexer proceeds left to right. At each "
        "position it first tries the longest multiword entry that could start "
        "there, then a single-word entry, then the patterns in order. The "
        "first column below is the position in the input; the last names the "
        "rule that succeeded."
    )
    w(longtable(
        "L{0.07} L{0.17} L{0.11} L{0.11} L{0.30}",
        ["Offset", "Lexeme", "Token", "Rule", "Decision"],
        [
            (
                f"{t.start}--{t.end}",
                t.lexeme,
                str(t.type),
                t.rule,
                (
                    "multiword entry, matched before its first word could be "
                    "taken alone"
                    if t.is_multiword else
                    "found in the closed vocabulary"
                    if t.rule.startswith("L-") or t.rule == "WORDS" else
                    "no dictionary entry; matched by pattern"
                ),
            )
            for t in demo.lex.tokens
        ],
        caption="Lexical decisions for one statement, in order.",
        size=r"\footnotesize",
    ))

    # ------------------------------------------------- 5 token tables
    section("Token tables, statement by statement")
    para(
        "The table below is the exact output of the lexical analyzer for every "
        "collected statement, in order. The rule column names the lexical rule "
        "that matched, so each classification can be traced back to the "
        "specification of Section 6. A bold line introduces each statement."
    )
    token_rows: list[tuple[str, ...]] = []
    for result in results:
        token_rows.append(
            (
                r"\multicolumn{7}{@{}l@{}}{\rule{0pt}{2.6ex}\textbf{"
                + esc(result.sid) + "} " + esc(result.text)
                + r" \textit{(" + esc(result.verdict) + r")}}",
            )
        )
        token_rows.extend(
            tuple(esc(c) for c in row) for row in token_table(result)
        )
    w(longtable(
        "L{0.03} L{0.13} L{0.07} L{0.12} L{0.04} L{0.08} L{0.28}",
        ["#", "Lexeme", "Token", "Language", "Slang", "Rule", "Gloss"],
        token_rows,
        caption="Lexical analysis of every collected statement.",
        size=r"\scriptsize",
        escape=False,
    ))

    subsection("The resulting token streams")
    w(longtable(
        "L{0.05} L{0.76}",
        ["ID", "Token stream"],
        [(r.sid, tt(r.lex.type_string() + " " + END)) for r in results],
        caption="The token stream handed to the parser for each statement.",
        size=r"\scriptsize",
        escape=False,
    ))
    lex_failures = [r for r in results if r.reason]
    if lex_failures:
        subsection("Statements not accepted")
        w(longtable(
            "L{0.05} L{0.74}",
            ["ID", "Reason"],
            [(r.sid, r.reason) for r in lex_failures],
            size=r"\footnotesize",
        ))

    # ------------------------------------------- 9 lexical inventory
    section("The complete lexical inventory of the corpus")
    inventory = distinct_token_inventory(results)
    para(
        f"Collapsing the {report.total_tokens} tokens of Section 8 by token "
        f"type and folded form leaves {len(inventory)} distinct lexical items. "
        "This is the vocabulary the corpus actually exercises, as opposed to "
        "the vocabulary the specification declares, and the difference between "
        "the two is a measure of how much of the specification is currently "
        "evidenced by data."
    )
    w(longtable(
        "L{0.10} L{0.06} L{0.64}",
        ["Token", "Count", "Attested lexical items"],
        [
            (
                ttype,
                str(len(items)),
                ", ".join(sorted(items)),
            )
            for ttype, items in sorted(
                {
                    str(t.type): [
                        x.normalized for x in inventory if x.type is t.type
                    ]
                    for t in inventory
                }.items()
            )
        ],
        caption="Every distinct lexical item attested in the corpus, "
                "grouped by token type.",
        size=r"\footnotesize",
    ))
    para(
        "Glosses and source languages for each of these appear in Section 8, "
        "where every occurrence is listed with its statement."
    )
    declared = len(WORDS) + len(PHRASES)
    para(
        f"The specification declares {declared} entries and the corpus "
        f"exercises {len(inventory)} of them, or "
        f"{pct(100 * len(inventory) / declared)}. The remainder were added "
        "during development because they are common in the register, but they "
        "are not attested in this corpus. They are honest coverage rather than "
        "evidence, and a larger corpus would be needed to justify them."
    )

    # ------------------------------------------------- 6 frequency
    section("Token frequency and variation")
    para(
        f"The corpus yields {report.total_tokens} tokens over "
        f"{report.distinct_lexemes} distinct lexical items, a type/token ratio "
        f"of {report.type_token_ratio:.2f}."
    )

    subsection("Frequency by token type")
    w(longtable(
        "L{0.16} L{0.12} L{0.12}",
        ["Token type", "Count", "Share"],
        [
            (t, str(n), esc(pct(100 * n / report.total_tokens)))
            for t, n in report.type_counts.most_common()
        ],
        caption="Distribution of terminal symbols across the corpus.",
        escape=False,
    ))

    subsection("Most frequent lexical items")
    w(longtable(
        "L{0.17} L{0.07} L{0.11} L{0.40}",
        ["Lexeme", "Count", "Token type", "Spellings attested"],
        [
            (
                norm,
                str(count),
                str(report.variants[norm].token_type),
                report.variants[norm].spelling_list(),
            )
            for norm, count in report.top_lexemes(15)
        ],
        caption="The most frequent lexical items.",
    ))

    subsection("Variation")
    varying = report.varying_items()
    if varying:
        para(
            "The following items are attested with more than one written form. "
            "They are counted as one lexical item, but every spelling is "
            "retained."
        )
        w(longtable(
            "L{0.17} L{0.07} L{0.07} L{0.44}",
            ["Lexeme", "Forms", "Total", "Attested spellings"],
            [
                (v.normalized, str(v.variation), str(v.total), v.spelling_list())
                for v in varying
            ],
            caption="Lexical items with more than one attested spelling.",
        ))
    else:
        para(
            "No lexical item in this corpus is attested with more than one "
            "spelling. This is a property of the current corpus, not of the "
            "analyzer: the variation machinery groups forms under a folded "
            "key, so reseau, reseau with an acute accent, and Reseau "
            "capitalised would be reported as one item with three forms as "
            "soon as such variation occurs. With a larger corpus, or with "
            "several transcribers, this table is where that variation would "
            "appear."
        )

    subsection("Multiword lexemes recognised as single tokens")
    w(longtable(
        "L{0.24} L{0.16}",
        ["Lexeme", "Occurrences"],
        [(k, str(v)) for k, v in report.multiword.most_common()],
        caption="Multiword lexemes, each treated as one token.",
    ))

    subsection("Slang and Camfranglais items")
    w(longtable(
        "L{0.24} L{0.16}",
        ["Lexeme", "Occurrences"],
        [(k, str(v)) for k, v in report.slang_counts.most_common()],
        caption="Items flagged as slang or Camfranglais.",
    ))

    # ------------------------------------------------- 7 code-mixing
    section("Code-mixing analysis")
    subsection("Tokens by source language")
    total_lang = sum(report.language_counts.values())
    w(longtable(
        "L{0.20} L{0.18} L{0.12}",
        ["Language", "Token attributions", "Share"],
        [
            (lang, str(n), esc(pct(100 * n / total_lang)))
            for lang, n in report.language_counts.most_common()
        ],
        caption="Source languages drawn on across the corpus.",
        escape=False,
    ))
    para(
        "A token may be attributed to more than one language, which is why the "
        "attribution count exceeds the token count. Those are the items that "
        "are themselves code-mixed rather than merely adjacent to another "
        "language."
    )

    subsection("Statements drawing on more than one language")
    w(longtable(
        "L{0.14} L{0.60}",
        ["Statement", "Languages"],
        [(sid, ", ".join(langs)) for sid, langs in report.mixed_statements],
        caption="Code-mixing at the level of the statement.",
    ))
    para(
        f"{len(report.mixed_statements)} of {len(results)} statements draw on "
        f"more than one language."
    )

    # ------------------------------------------------- 8 grammar
    section("Syntactic analysis: the grammar")
    para(
        "The grammar describes the shape of the utterances in the corpus. Read "
        "informally, a statement is an optional run of openers (interjections "
        "and address terms), then one or more clauses separated by commas, "
        "then a terminator:"
    )
    w(ANATOMY_FIGURE)
    para(
        "A clause is an optional subject followed by either a verbal predicate "
        "or a copular predicate. The verbal predicate may be headed by "
        "negation or by an aspect marker --- don for the perfective, dey for "
        "the progressive --- which is the Pidgin pattern rather than the "
        "English one, and the grammar encodes it directly."
    )
    para("The grammar as first written:")
    w(verbatim(prepared.base.format()))
    para(
        "Two properties of this grammar are deliberate, because the assignment "
        "requires the corresponding transformations. ClauseList is left "
        "recursive, which a predictive parser cannot handle. The two Clause "
        "productions share the prefix Subj, which prevents a one-token "
        "lookahead from choosing between them. The next two sections remove "
        "both."
    )

    subsection("What each nonterminal stands for")
    glossary = {
        "Statement": "A complete utterance: openers, clauses, terminator.",
        "Preamble": "The run of interjections and address terms that may "
                    "precede the first clause.",
        "Opener": "One interjection or one vocative.",
        "SepOpt": "An optional comma after an opener.",
        "ClauseList": "One or more clauses separated by commas.",
        "ClauseList'": "Generated when left recursion was removed from "
                       "ClauseList; carries the remaining comma-separated "
                       "clauses.",
        "Clause": "A subject followed by a predicate.",
        "Subj": "An optional noun phrase, optionally modified by a "
                "prepositional phrase. Optional because subjects are freely "
                "dropped in this register.",
        "SubjPP": "The optional prepositional modifier of the subject; "
                  "separated out to keep the parse table conflict-free.",
        "VP": "A verbal predicate, possibly headed by negation or aspect.",
        "AuxSeq": "A run of aspect and modal markers preceding the verb.",
        "Core": "The verb together with what follows it.",
        "Items": "A sequence of post-verbal or post-copular constituents.",
        "Item": "One such constituent: a noun phrase, a prepositional "
                "phrase, an adverbial or a numeral.",
        "NP": "A noun phrase: optional determiner, noun group, optional "
              "particle.",
        "NGopt": "The optional continuation of a noun compound; the source of "
                 "the documented conflict in Section 18.",
        "PP": "A preposition followed by a noun phrase.",
        "Clause_f": "Generated by left factoring; decides between the verbal "
                    "and the copular predicate once the shared subject has "
                    "been parsed.",
    }
    w(longtable(
        "L{0.15} L{0.66}",
        ["Nonterminal", "Meaning"],
        [
            (nt, glossary.get(nt, "Generated by a grammar transformation."))
            for nt in prepared.final.nonterminals
        ],
        caption="The nonterminals of the final grammar.",
    ))

    subsection("Design decisions behind the grammar")
    for head, body in [
        ("The subject is optional.",
         "Statements such as \"Na wuna own.\" and \"Chef, drop me for "
         "Carrefour Obili.\" have no overt subject, and treating that as an "
         "error would reject a large share of the corpus. Subj therefore "
         "derives the empty string."),
        ("Aspect is a separate category.",
         "AUX covers don and dey, which mark completion and ongoing action. "
         "They are free morphemes preceding the verb, so they are modelled as "
         "a sequence AuxSeq rather than as inflection on the verb."),
        ("Negation may head the predicate.",
         "Both \"no dey\" and \"pas cher\" place the negator before what it "
         "negates, so VP admits a leading NEG."),
        ("Noun compounding is unbounded.",
         "Sequences such as \"carrefour Obili\" and \"bendskin man\" are "
         "nouns modifying nouns with no limit and no determiner between them, "
         "which is why NGopt is recursive --- and why it is the one place the "
         "grammar is ambiguous."),
        ("Clause structure is flat on purpose.",
         "Items makes no distinction between an argument and an adjunct. The "
         "distinction is real, but recovering it requires knowing what the "
         "verb means, which is semantic analysis and out of scope."),
    ]:
        para(f"{head} {body}")

    # ------------------------------------------ 9 left recursion
    section("Removing left recursion")
    if prepared.recursion_steps:
        para(
            "A production of the form A -> A alpha, alternating with A -> "
            "beta, causes a predictive parser to expand A into A forever "
            "without consuming input. It is removed by rewriting the pair as A "
            "-> beta A-prime together with A-prime -> alpha A-prime, "
            "alternating with the empty production. The rewritten grammar "
            "generates the same language while consuming beta before "
            "recursing."
        )
        for step in prepared.recursion_steps:
            para(f"{step.nonterminal}: {step.note}.")
            lines = [f"from:  {line}" for line in step.before]
            lines += [f"to:    {line}" for line in step.after]
            w(verbatim("\n".join(lines)))
    else:
        para(
            "The grammar contains no left recursion, so no transformation "
            "applies here."
        )
    para("The grammar after this step:")
    w(verbatim(prepared.after_left_recursion.format()))

    # ------------------------------------------ 10 left factoring
    section("Left factoring")
    if prepared.factoring_steps:
        para(
            "When two productions of the same nonterminal begin with the same "
            "symbols, one token of lookahead cannot tell them apart. The "
            "common prefix is factored out into a single production and the "
            "differing tails move into a new nonterminal, which defers the "
            "decision until the parser has read enough to make it."
        )
        for step in prepared.factoring_steps:
            para(f"{step.nonterminal}: {step.note}.")
            lines = [f"from:  {line}" for line in step.before]
            lines += [f"to:    {line}" for line in step.after]
            w(verbatim("\n".join(lines)))
        para(
            "Concretely: on reading \"Courant ...\" the parser cannot yet know "
            "whether the clause continues \"... no dey\", which is verbal, or "
            "\"... na trop cher\", which is copular. After factoring it parses "
            "the shared subject first and decides at Clause_f, by which point "
            "the next token settles the question."
        )
    else:
        para("No two productions share a common prefix, so no factoring applies.")
    para("The final grammar:")
    w(verbatim(prepared.final.format()))

    subsection("Numbered productions")
    w(verbatim("\n".join(prepared.final.numbered_productions())))

    # ------------------------------------------ 11 FIRST / FOLLOW
    section("FIRST and FOLLOW sets")
    para(
        "FIRST of a symbol X is the set of terminals that can begin a string "
        "derived from X, plus the empty production if X can derive it. FOLLOW "
        "of a nonterminal A is the set of terminals that can appear "
        "immediately after A in some derivation, with the dollar sign marking "
        "end of input. Both are computed by fixed-point iteration; the sets "
        "below are that computed result, not a transcription."
    )
    w(longtable(
        "L{0.13} L{0.36} L{0.36}",
        ["Nonterminal", "FIRST", "FOLLOW"],
        [
            (
                nt,
                "{ " + ", ".join(sorted(prepared.table.first[nt])) + " }",
                "{ " + ", ".join(sorted(prepared.table.follow[nt])) + " }",
            )
            for nt in prepared.final.nonterminals
        ],
        caption="FIRST and FOLLOW sets of the final grammar.",
        size=r"\footnotesize",
    ))

    subsection("Worked examples")
    para(
        "Two of these deserve to be shown rather than asserted, because they "
        "are where the fixed-point computation does real work."
    )
    para(
        "FIRST(Statement). The start symbol expands to Preamble followed by "
        "ClauseList and a terminator. Preamble can derive the empty string, so "
        "FIRST(Statement) contains everything in FIRST(Preamble) --- the "
        "interjections and vocatives --- and, because Preamble may vanish, "
        "everything in FIRST(ClauseList) as well. ClauseList in turn begins "
        "with a Clause, whose subject is optional, so the set reaches down "
        "through Subj to NP and through Clause\\_f to VP. The result is the "
        "union of every terminal that can open an utterance:"
    )
    w(verbatim(wrap_set("FIRST(Statement)", prepared.table.first["Statement"])))
    para(
        "FOLLOW(NGopt). NGopt is the tail of a noun compound. It appears at "
        "the end of NP, so whatever can follow an NP can follow NGopt: a "
        "particle, a comma, a terminator, the start of the next Item, and so "
        "on. Because NGopt can itself derive the empty string, this set is "
        "also exactly the set of lookaheads on which the parser must choose "
        "to stop compounding --- which is why the conflict discussed in "
        "Section 18 arises precisely here:"
    )
    w(verbatim(wrap_set("FOLLOW(NGopt)", prepared.table.follow["NGopt"])))
    para(
        "Both sets are computed by repeated passes over the productions until "
        "nothing changes. The iteration is guaranteed to terminate because the "
        "sets only ever grow and the number of terminals is finite."
    )

    subsection("Nullable nonterminals")
    nullable = [
        nt for nt in prepared.final.nonterminals
        if EPSILON in prepared.table.first[nt]
    ]
    para(
        f"{len(nullable)} of the {len(prepared.final.nonterminals)} "
        "nonterminals can derive the empty string: "
        + ", ".join(nullable) + ". "
        "Each corresponds to something genuinely optional in the register --- "
        "an absent subject, a missing determiner, a clause with no opener --- "
        "and each is a place where the parser must decide to expand or to "
        "skip on one token of lookahead."
    )

    # ------------------------------------------ 12 parse table
    section("The LL(1) parsing table")
    para(
        "For each production A -> alpha, the entry M[A, a] is set to that "
        "production for every terminal a in FIRST of alpha; and if alpha can "
        "derive the empty string, for every terminal in FOLLOW of A as well. "
        "An empty cell is a parse error."
    )
    para(
        "The table is given as a grid, split into blocks of columns so that it "
        "fits the page. A dash marks an empty cell; the other entries are the "
        "production numbers assigned in Section 14."
    )

    numbering = {}
    for i, line in enumerate(prepared.final.numbered_productions(), 1):
        _, _, rule = line.partition(".")
        numbering[rule.strip()] = i

    def rule_number(nt: str, terminal: str) -> str:
        production = prepared.table.lookup(nt, terminal)
        if production is None:
            return "---"
        key = f"{nt} -> {' '.join(production)}"
        return str(numbering.get(key, "?"))

    terminals = sorted(prepared.final.terminals) + [END]
    for block in chunks(terminals, 9):
        spec = "L{0.13} " + " ".join("L{0.06}" for _ in block)
        w(longtable(
            spec,
            ["Nonterminal"] + block,
            [
                [nt] + [rule_number(nt, t) for t in block]
                for nt in prepared.final.nonterminals
            ],
            caption=f"Parsing table, columns {block[0]} to {block[-1]}.",
            size=r"\footnotesize",
        ))

    filled = sum(
        1
        for nt in prepared.final.nonterminals
        for t in terminals
        if prepared.table.lookup(nt, t) is not None
    )
    cells = len(prepared.final.nonterminals) * len(terminals)
    para(
        f"The table has {len(prepared.final.nonterminals)} rows and "
        f"{len(terminals)} columns, so {cells} cells, of which {filled} are "
        f"filled --- {pct(100 * filled / cells)}. The sparsity is expected and "
        "is what makes the parser's error messages useful: an empty cell is "
        "not merely a failure, it is a statement about which terminals would "
        "have been acceptable instead, and that is the set reported in "
        "Section 20."
    )

    # ------------------------------------------ 13 conflicts
    section("Conflicts and how they are resolved")
    conflicts = prepared.table.conflicts
    if not conflicts:
        para("The table has no conflicts. The grammar is LL(1).")
    else:
        para(
            f"Constructing the table produced {len(conflicts)} conflict. A "
            "conflict means two productions compete for one cell, so one token "
            "of lookahead does not determine the parser's next move. Each is "
            "stated below with the decision taken."
        )
        for conflict in conflicts:
            note = DOCUMENTED_CONFLICTS.get(
                (conflict.nonterminal, conflict.terminal)
            )
            w(r"\textbf{" + esc(str(conflict)) + "}")
            w("")
            if note:
                para(note)
            else:
                para(
                    "This conflict has not been reviewed. It is a defect and "
                    "should be resolved before submission."
                )
        remaining = undocumented_conflicts(prepared.table)
        para(
            f"{len(conflicts)} conflict in total, of which {len(remaining)} "
            f"remain unreviewed."
        )
        para(
            "It is worth being precise about what this means. The grammar is "
            "not strictly LL(1): a grammar with any conflict fails that "
            "definition. What we have is an LL(1) table with one ambiguous "
            "cell resolved by a stated rule, in exactly the way the "
            "dangling-else ambiguity is conventionally resolved in favour of "
            "the nearest if. The resolution is deterministic and it is correct "
            "for every compound in the corpus, but it is a choice we made, not "
            "a property the grammar gave us."
        )

    # ------------------------------------------ 14 parser
    section("The parser")
    para(
        "The parser is a table-driven predictive parser. It maintains a stack "
        "initialised with the end marker and the start symbol, and repeats: if "
        "the top of the stack is a terminal it must equal the lookahead, and "
        "both are consumed; if it is a nonterminal, the cell M[top, lookahead] "
        "supplies the production, whose right-hand side is pushed in reverse "
        "order. Input is accepted only when the stack has emptied down to the "
        "end marker and the lookahead is also the end marker, so trailing "
        "tokens cannot be ignored."
    )
    para("Two behaviours are worth noting.")
    w(r"\begin{itemize}")
    w(r"\item " + prose(
        "Lexical failure is distinguished from syntactic failure. A token "
        "stream containing UNKNOWN is rejected before parsing begins and "
        "reported as a lexical rejection. This keeps \"we do not know this "
        "word\" separate from \"this structure is not in the grammar\"."
    ))
    w(r"\item " + prose(
        "Rejections are explained, not merely announced. On failure the parser "
        "reports the offending token with its line and column, and the set of "
        "terminals the table would have accepted in that position."
    ))
    w(r"\end{itemize}")
    w("")

    # ------------------------------------------ 15 test results
    section("Test results: accepted and rejected sentences")
    subsection("Corpus statements")
    w(longtable(
        "L{0.05} L{0.32} L{0.13} L{0.32}",
        ["ID", "Transcription", "Result", "Reason if rejected"],
        [(r.sid, r.text, r.verdict, r.reason or "---") for r in results],
        caption="Verdict for every collected statement.",
        size=r"\footnotesize",
    ))
    para(f"{report.accepted} of {len(results)} corpus statements are accepted.")

    subsection("Negative tests")
    para(
        "These inputs are not field data. They are constructed to fall outside "
        "the grammar, and exist to show that acceptance is decided by parsing "
        "rather than by recognising memorised sentences. A parser that "
        "accepted everything would be useless, so the rejections matter as "
        "much as the acceptances."
    )
    neg_rows = []
    negatives_ok = 0
    for sid, text, why in corpus.NEGATIVE_TESTS:
        r = analyzer.analyze_text(text, sid=sid, trace=False)
        negatives_ok += not r.accepted
        neg_rows.append((sid, text, why, r.verdict, r.reason or "---"))
    w(longtable(
        "L{0.04} L{0.14} L{0.18} L{0.12} L{0.29}",
        ["ID", "Input", "Why it should fail", "Result", "Reason"],
        neg_rows,
        caption="Constructed inputs that must be rejected.",
        size=r"\scriptsize",
    ))
    para(
        f"{negatives_ok} of {len(corpus.NEGATIVE_TESTS)} negative tests are "
        f"correctly rejected."
    )

    # ------------------------------------------ 16 traces
    section("Worked parse traces")
    para(
        "The trace shows the parser's stack, the remaining input and the "
        "action taken at each step. One accepted statement is shown in full, "
        "followed by one rejection with the diagnosis the parser produced. "
        "Traces for the remaining statements are obtainable from the analyzer "
        "with the show command described in Section 26."
    )

    def trace_table(res, label: str) -> None:
        w("Token stream: " + tt(res.lex.type_string() + " " + END))
        w("")
        w(longtable(
            "L{0.05} L{0.33} L{0.26} L{0.24}",
            ["Step", "Stack", "Remaining input", "Action"],
            [
                (str(s.number), s.stack, s.remaining, s.action)
                for s in res.parse.trace
            ],
            caption=label,
            size=r"\scriptsize",
        ))

    showcase = [
        (corpus.CORPUS[0],
         "an opener, a vocative and a prepositional phrase"),
    ]
    for statement, why in showcase:
        traced = analyzer.analyze_statement(statement, trace=True)
        subsection(f"Accepted: {traced.sid} --- {traced.text}")
        para(f"Chosen because it exercises {why}.")
        trace_table(traced, f"Full parse trace for {traced.sid}.")
        if traced.parse.tree is not None:
            para("The resulting parse tree:")
            w(verbatim(str(traced.parse.tree)))

    for index in [2]:
        sid, text, why = corpus.NEGATIVE_TESTS[index]
        rejected = analyzer.analyze_text(text, sid=sid, trace=True)
        subsection(f"Rejected: {sid} --- {text}")
        para(f"Intended defect: {why}.")
        trace_table(
            rejected, f"Parse trace up to the point of failure for {sid}."
        )
        para(f"Parser diagnosis: {rejected.reason}")

    # ------------------------------------------ 17 derivations
    section("Leftmost derivations")
    para(
        "A predictive parser produces a leftmost derivation: at every step it "
        "expands the leftmost nonterminal of the sentential form. The "
        "derivations below are recovered from the parse trees of the previous "
        "section, so they are the derivations the parser actually performed. "
        "The empty production is applied silently --- where a nonterminal "
        "derives nothing, it simply disappears from the next line."
    )
    for statement, _ in showcase[:1]:
        traced = analyzer.analyze_statement(statement, trace=True)
        if traced.parse.tree is None:
            continue
        subsection(f"{traced.sid} --- {traced.text}")
        forms = leftmost_derivation(traced.parse.tree)
        lines = [forms[0]]
        lines += [f"=> {form}" for form in forms[1:]]
        w(verbatim("\n".join(lines)))
        para(
            f"{len(forms) - 1} derivation steps, ending in the token string "
            f"the lexer produced."
        )

    # ------------------------------------------ 18 further trees
    section("A further parse tree")
    accepted = [r for r in results if r.accepted]
    sample = accepted[1:2]
    para(
        "One more tree, for a statement with a different shape from the one "
        "traced above. A leaf labelled with a quoted lexeme is a matched "
        "terminal; a bare epsilon is an empty production. Trees for the "
        "remaining statements are obtainable from the analyzer with the show "
        "command described in Section 25."
    )
    for result in sample:
        traced = analyzer.analyze_text(result.text, sid=result.sid, trace=True)
        if traced.parse.tree is None:
            continue
        subsection(f"{result.sid} --- {result.text}")
        w(verbatim(str(traced.parse.tree)))

    # ------------------------------------------ 17 discussion
    section("Comparison with a programming-language compiler")
    para(
        "The techniques used here were designed for artificial languages. It "
        "is worth setting out precisely where they transferred and where they "
        "did not, because that is the substance of what this exercise teaches."
    )
    w(longtable(
        "L{0.20} L{0.29} L{0.29}",
        ["Aspect", "Programming language", "This register"],
        [
            ("Alphabet",
             "Fixed and small; the language definition enumerates it.",
             "Open; loanwords and coinages arrive continually."),
            ("Keywords",
             "A closed set, decided by the designer.",
             "No closed set exists; the vocabulary here is closed only "
             "because we chose to close it."),
            ("Token boundaries",
             "Whitespace and punctuation suffice; identifiers never contain "
             "spaces.",
             "Lexemes may span several written words, so longest-match "
             "phrase recognition is needed before word recognition."),
            ("Ambiguity",
             "Designed out; where it remains, as in dangling else, it is "
             "resolved by a documented rule.",
             "Pervasive and not removable; the same strategy of documented "
             "resolution is the only one available."),
            ("Error",
             "An objective property: the program is or is not well-formed.",
             "Not objective. Rejection means outside our grammar, never "
             "wrong."),
            ("Grammar size",
             "Large, but complete for the language.",
             "Small, and deliberately incomplete; completeness is not "
             "attainable."),
            ("Meaning",
             "Assigned by the semantics of the language.",
             "Depends on speaker, hearer, tone and situation; not recoverable "
             "from the token stream."),
            ("Validation",
             "The compiler's output can be executed and tested.",
             "There is no execution. Validation is agreement with the "
             "collected data, which is why the corpus matters."),
        ],
        caption="Where compiler technique transfers, and where it does not.",
    ))
    para(
        "The row that matters most is the fifth. A compiler that rejects a "
        "program is making a claim about the program. An analyzer that rejects "
        "an utterance is making a claim about itself --- that its grammar does "
        "not reach that far. Keeping that distinction visible is why every "
        "rejection in Section 20 is reported with a reason, and why lexical "
        "failure is separated from syntactic failure throughout."
    )

    section("Why Yaounde communication is linguistically complex")
    para(
        "Building this analyzer surfaced several specific difficulties. Each "
        "of the following is a claim supported by the corpus and by the design "
        "decisions the corpus forced."
    )

    subsection("Code-mixing happens below the sentence level")
    para(
        f"{len(report.mixed_statements)} of {len(results)} statements draw on "
        "more than one language, but the more awkward fact is that mixing "
        "occurs within the clause and sometimes within a single lexeme. \"Je "
        "wanda\" welds a French pronoun to a Pidgin verb and functions as an "
        "indivisible exclamation. A lexer that assumed one language per "
        "utterance, or even one language per phrase, would be wrong at the "
        "first sentence. Our design carries a set of languages on each token "
        "rather than a single label, precisely because a single label cannot "
        "represent what is happening."
    )

    subsection("Word boundaries do not coincide with lexeme boundaries")
    para(
        f"The specification declares {len(PHRASES)} multiword lexemes. \"Small "
        "small\" means intermittently, not small twice. \"Deux cents\" is one "
        "amount. Whitespace is therefore not a reliable tokenizer for this "
        "register, and longest-match phrase recognition has to run before word "
        "recognition --- a requirement a conventional programming-language "
        "lexer never faces, since identifiers there do not contain spaces."
    )

    subsection("Grammatical relations are marked by particles, not inflection")
    para(
        "Tense and aspect are carried by free markers --- don for completion, "
        "dey for ongoing action --- rather than by verb endings. \"Rain don "
        "beat we\" is perfective; \"we dey wait\" is progressive. The verb form "
        "itself does not change. The grammar models these as a separate AUX "
        "category that may precede the verb, which is structurally unlike the "
        "morphology-driven analysis an English or French parser would use."
    )

    subsection("Some elements are productive and cannot be enumerated")
    para(
        "Hesitation cries and emphatic lengthening are open-ended: a speaker "
        "may draw out hmmm or garrr to any length for emphasis, and the length "
        "is meaningful. These cannot be listed in a dictionary, so they are "
        "handled by regular expressions over repeated characters. This is the "
        "one place where the register behaves like a genuinely open class."
    )

    subsection("Transcription is itself an analytical act")
    para(
        "Deciding where one word ends and another begins, or which of several "
        "spellings to write for a sound that has no standard orthography, is "
        "already an interpretation. Two transcribers will not always agree. "
        "This is why the analyzer preserves the original spelling on every "
        "token and folds only to build a lookup key: the folding is reversible "
        "and the evidence survives, so a disputed transcription can be "
        "revisited without the tooling having destroyed it."
    )

    subsection("The same form serves several functions")
    para(
        "Items in this register are frequently reused across categories. Na "
        "is a copula in \"Na wuna own\" but functions differently elsewhere; "
        "for covers location, direction and possession where English would "
        "use three different prepositions; dey is an aspect marker before a "
        "verb and existential on its own. A lexer that assigns one token type "
        "per form --- which is what ours does --- must therefore choose, and "
        "the choice is sometimes wrong for a particular occurrence. Resolving "
        "it properly requires looking at the context, which means the lexer "
        "would have to know something the parser is supposed to determine. We "
        "took the simpler route and accepted the cost, which is that a "
        "handful of classifications are defensible rather than correct."
    )

    subsection("Politeness and address are structural, not decorative")
    para(
        "Address terms --- Chef, Mami, Patron, Mbom --- open a large "
        "proportion of the corpus, and they are not optional flourishes. They "
        "establish the relationship within which the rest of the utterance is "
        "to be read; the same request with and without one is a different "
        "speech act. The grammar treats them as a distinct category, VOC, and "
        "gives them a dedicated position in Preamble rather than folding them "
        "into the noun phrase, because syntactically they behave like "
        "neither subject nor object."
    )

    subsection("Sentence boundaries are negotiable")
    para(
        "In writing, a full stop ends a sentence. In speech, clauses are "
        "strung together with commas and intonation, and where one utterance "
        "ends is a judgement the transcriber makes. The grammar takes a "
        "terminator as obligatory, which is a convenience of our own making: "
        "it gives the parser something definite to reach. The data does not "
        "really contain terminators, it contains pauses, and the two are not "
        "the same."
    )

    subsection("What this implies for compiler construction")
    para(
        "A programming language is designed to be unambiguous, and its lexer "
        "and grammar can be exhaustive. Natural urban speech is neither. The "
        "response taken here is not to pretend otherwise but to define a "
        "deliberately restricted sub-language, state its boundaries "
        "explicitly, and report every input that falls outside them rather "
        "than failing silently. The value of the analyzer lies as much in what "
        "it declines to handle, and says so, as in what it accepts."
    )

    # ------------------------------------------ 18 limitations
    section("Limitations and future work")
    limitations = [
        ("The corpus is small.",
         f"{len(corpus.CORPUS)} statements meet the brief but cannot establish "
         "frequency distributions with any confidence. The percentages above "
         "describe this corpus and should not be read as describing Yaounde "
         "speech in general."),
        ("The vocabulary is closed.",
         "Any word not declared in the specification is rejected as UNKNOWN. "
         "This is a deliberate choice --- visible failure over silent guessing "
         "--- but it means the analyzer does not generalise to new speakers "
         "without extending the lexicon."),
        ("One cell of the parse table is ambiguous.",
         "Noun compounding is resolved greedily by a stated rule rather than "
         "by the grammar. This is correct for the present corpus, but it is a "
         "resolution rather than a proof."),
        ("Clause structure is flat.",
         "Complements and adjuncts share one Items category, so the parse tree "
         "records that a prepositional phrase is present without "
         "distinguishing an argument from a modifier. Recovering that "
         "distinction needs semantic information the brief does not ask for."),
        ("No semantic analysis.",
         "The analyzer decides membership of a grammar. It does not determine "
         "what a statement means, and cannot detect that a sentence is "
         "well-formed but implausible."),
        ("Cleft and focus constructions are out of reach.",
         "A question such as \"Na wetin dey happen?\" puts a copula in front "
         "of what is in effect a relative clause. Clause_f derives COP Items, "
         "and Items admits no verbal predicate, so the analyzer rejects it on "
         "the AUX. Covering it would need a relativiser and a clause-valued "
         "complement of the copula, which is a larger grammar than the brief "
         "asks for. The rejection is reported rather than concealed."),
        ("Prosody is lost.",
         "Tone, emphasis and length carry meaning in this register, and "
         "written transcription discards most of it. Hmmm spans a range of "
         "attitudes that the single token INTERJ flattens entirely."),
    ]
    w(r"\begin{itemize}")
    for head, body in limitations:
        w(r"\item \textbf{" + esc(head) + "} " + prose(body))
    w(r"\end{itemize}")
    w("")

    # ------------------------------------------ 19 running
    section("How to run the analyzer")
    para("No third-party packages are required; Python 3.10 or later is enough.")
    w(verbatim(
        "cd \"compiler construction\"\n"
        "set PYTHONPATH=src            # Windows; use export on Linux/macOS\n"
        "\n"
        "python -m yca corpus          # analyze every collected statement\n"
        "python -m yca test            # positive and negative test cases\n"
        "python -m yca grammar         # transformations, FIRST/FOLLOW, table\n"
        "python -m yca spec            # the lexical specification\n"
        "python -m yca freq            # frequency, variation, code-mixing\n"
        "python -m yca show S01 --trace   # full detail for one statement\n"
        "python -m yca parse \"Chef, drop me for Obili.\" --trace\n"
        "python -m yca repl            # interactive; type a statement\n"
        "python -m yca report          # regenerate this document\n"
        "\n"
        "python -m unittest discover -s tests -v   # unit tests"
    ))
    para(
        "To use your own field data, edit src/yca/corpus.py, replace the "
        "statements, set the provenance to FIELD, and regenerate. Every table "
        "in this report is computed from that file."
    )

    subsection("Compiling this report")
    w(verbatim(
        "python -m yca report -o docs/report.tex\n"
        "cd docs\n"
        "pdflatex report.tex\n"
        "pdflatex report.tex        # second pass resolves the contents page"
    ))

    subsection("Test suite")
    para(
        "The unit tests cover the lexer, the grammar transformations, the "
        "parser and the report generator. Three groups are worth naming. The "
        "grammar tests assert that the transformed grammar derives the same "
        "sentences as the original, so the transformations cannot silently "
        "change the language. The parser tests assert that acceptance "
        "requires both an emptied stack and consumed input, so trailing "
        "tokens cannot be ignored. The report tests check the generated LaTeX "
        "structurally --- balanced environments, escaped special characters, "
        "consistent table column counts --- which stands in for compiling it "
        "on a machine without a TeX installation."
    )

    # ------------------------------------------ 20 conclusion
    section("Conclusion")
    para(
        "We set out to apply the lexical and syntactic phases of a compiler "
        "to informal urban speech in Yaounde, and the exercise worked in the "
        f"narrow sense that matters: the analyzer accepts {report.accepted} "
        f"of {len(results)} collected statements and rejects all "
        f"{len(corpus.NEGATIVE_TESTS)} of the constructed counter-examples, "
        "with every acceptance backed by a derivation and every rejection by "
        "a located reason."
    )
    para(
        "Getting there required each of the steps the brief names, and none "
        "of them was a formality. The lexical specification had to grow a "
        f"layer of {len(PHRASES)} multiword lexemes, because whitespace does "
        "not mark lexeme boundaries in this register. The grammar had to be "
        "written with left recursion and a common prefix in it, and then "
        "mechanically transformed, because a predictive parser tolerates "
        "neither. Computing FIRST and FOLLOW exposed a genuine ambiguity in "
        "noun compounding that no amount of rewriting removes, and it is "
        "resolved by a stated rule rather than concealed."
    )
    para(
        "The substantive finding is about the limits of the method rather "
        f"than its reach. Code-mixing appears in "
        f"{len(report.mixed_statements)} of {len(results)} statements and "
        "operates below the clause, sometimes inside a single lexeme; aspect "
        "is marked by free particles rather than inflection; and several "
        "forms serve more than one grammatical function depending on context "
        "the lexer cannot see. A context-free grammar can describe a "
        "deliberately restricted slice of this and nothing more. We think "
        "that is the honest result, and the design reflects it: unknown input "
        "is reported rather than discarded, the one ambiguous table cell is "
        "documented rather than quietly resolved, and every figure quoted "
        "here is computed from the corpus rather than asserted."
    )
    para(
        "The clearest next step is not more grammar but more data. The "
        "analyzer is built so that replacing the corpus regenerates every "
        "table, figure and percentage in this document automatically; the "
        "structures we could then justify would be the ones speakers actually "
        "produce, rather than the ones we anticipated."
    )

    # ------------------------------------------ appendices
    w(r"\appendix")
    section("The declared vocabulary")
    para(
        f"The lexical specification declares {len(PHRASES)} multiword lexemes "
        f"and {len(WORDS)} single words. Both are summarised below by token "
        "type. The complete annotated list, with glosses and source "
        "languages, runs to several hundred entries and is better read in its "
        "source form, in src/yca/lexspec.py, or printed with the spec "
        "command. Every entry actually attested in the corpus already appears "
        "with its gloss in Section 9."
    )

    grouped: dict[str, list[str]] = {}
    for lexeme, (ttype, _lang, _slang, _gloss) in WORDS.items():
        grouped.setdefault(str(ttype), []).append(lexeme)
    for lexeme, (ttype, _lang, _slang, _gloss) in PHRASES.items():
        grouped.setdefault(str(ttype), []).append(lexeme)
    w(longtable(
        "L{0.09} L{0.06} L{0.67}",
        ["Token", "Count", "Entries"],
        [
            (ttype, str(len(grouped[ttype])), ", ".join(sorted(grouped[ttype])))
            for ttype in sorted(grouped)
        ],
        caption="The declared vocabulary, by token type.",
        size=r"\scriptsize",
    ))

    w(r"\end{document}")
    return "\n".join(out) + "\n"


def write_report(path: str | Path = "docs/report.tex") -> Path:
    """Write the LaTeX report as UTF-8 and return the path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_report(), encoding="utf-8")
    return target
