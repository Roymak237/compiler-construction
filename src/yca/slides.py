"""Beamer slide deck for the project presentation.

Like :mod:`yca.report`, the deck is *generated* by the same code that
performs the analysis. Every count, percentage and grammar production on a
slide is computed at build time from the corpus and the grammar, so the
presentation cannot drift away from the software it describes -- change the
corpus and the slides change with it.

The deck is deliberately capped at :data:`MAX_SLIDES` frames. A
presentation that runs long is a worse presentation, and the cap is
enforced in code rather than left to discipline: :func:`build_slides`
raises if the deck grows past it.

Build it with::

    python -m yca slides --pdf
"""

from __future__ import annotations

from pathlib import Path

from . import corpus
from .analysis import frequency_report, token_table
from .figures import compiler_phases, lexer_automaton, parser_machine, slide_scale
from .grammar import END, EPSILON
from .grammar_def import DOCUMENTED_CONFLICTS, prepare, undocumented_conflicts
from .lexspec import PHRASES, WORDS
from .pipeline import Analyzer
from .report import esc, pct

#: Hard cap on the number of frames. The talk was first budgeted at ten
#: pages; the three generated diagrams of the scanner, the parser and the
#: compiler phases each need most of a slide to be legible from the back of
#: a room, so the cap was raised by exactly three rather than shrinking them
#: into a corner of an existing slide, which would have made them decoration.
#: Beamer emits one page per frame when no overlays are used, so the frame
#: count and the page count are the same number.
MAX_SLIDES = 13

#: Where the deployed front end lives. Kept here rather than inline so
#: there is one place to change it when the host changes.
LIVE_URL = "https://compiler-app.duckdns.org/"

#: The statement worked through on the lexical and syntactic slides. It is
#: chosen because it is short enough to fit a slide and still shows
#: code-mixing, a multiword lexeme and a vocative.
WORKED_EXAMPLE = "Chef, drop me for Carrefour Obili."


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def mono(text: str) -> str:
    """Escape *text* as monospace, preserving leading indentation.

    LaTeX collapses runs of spaces, so indentation written with ordinary
    spaces is lost. Leading spaces become unbreakable ones; interior runs
    are left alone because the grammar dumps align on single spaces only.
    """
    stripped = text.lstrip(" ")
    indent = "~" * (len(text) - len(stripped))
    return r"{\ttfamily " + indent + esc(stripped) + "}"


def arrowed(production: str) -> str:
    """Render ``A -> B C`` with a real arrow."""
    left, _, right = production.partition("->")
    return (r"{\ttfamily " + esc(left.strip()) + r"} $\to$ {\ttfamily "
            + esc(right.strip()) + "}")


PREAMBLE = r"""\documentclass[aspectratio=169,11pt]{beamer}

\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{array}
\usepackage{booktabs}
\usepackage{graphicx}
\usepackage{tikz}
\usetikzlibrary{positioning,arrows.meta,fit}

%% The deck shares the report's palette so the two read as one piece of
%% work: ink for structure, clay for anything the audience must not skim.
\definecolor{ink}{HTML}{1F3348}
\definecolor{clay}{HTML}{B4552D}
\definecolor{moss}{HTML}{3F6B52}
\definecolor{slate}{HTML}{4A5D78}
\definecolor{parchment}{HTML}{F4F1EA}
\definecolor{rule}{HTML}{C9C2B4}

%% A plain theme, built by hand. The stock beamer themes spend a third of
%% every slide on navigation furniture nobody clicks during a talk.
\usetheme{default}
\usecolortheme{default}
\setbeamertemplate{navigation symbols}{}
\setbeamercolor{structure}{fg=ink}
\setbeamercolor{frametitle}{fg=ink,bg=}
\setbeamercolor{normal text}{fg=ink}
\setbeamercolor{itemize item}{fg=clay}
\setbeamercolor{itemize subitem}{fg=slate}
\setbeamerfont{frametitle}{series=\bfseries,size=\large}
\setbeamerfont{framesubtitle}{size=\small,shape=\itshape}
\setbeamercolor{framesubtitle}{fg=slate}
\setbeamertemplate{itemize item}{\textbullet}
\setbeamertemplate{itemize subitem}{--}

%% A rule under the frame title, matching the report's section headings.
\setbeamertemplate{frametitle}{%
  \vskip0.6em%
  \usebeamerfont{frametitle}\usebeamercolor[fg]{frametitle}%
  \insertframetitle\par%
  \ifx\insertframesubtitle\@empty\else
    {\usebeamerfont{framesubtitle}\usebeamercolor[fg]{framesubtitle}%
     \insertframesubtitle\par}%
  \fi
  \vskip0.2em{\color{clay}\hrule height 1.2pt}\vskip0.4em}

%% Slide number in the corner, so the audience can cite one in questions.
%% Set in a filled chip so it stays legible over the tinted backdrop. The
%% chip is smashed to zero height: a taller footline steals vertical space
%% from the body and pushes the fullest slides into overfull boxes.
\setbeamertemplate{footline}{%
  \hfill\smash{\setlength{\fboxsep}{2.5pt}%
    \colorbox{ink}{\color{parchment}\scriptsize
      \insertframenumber/\inserttotalframenumber}}%
  \hspace{1.2em}\vskip0.9em}

%% ------------------------------------------------------------- backdrop
%% A white slide reads as a printed document and a heavy stock template
%% reads as a sales deck. This sits between the two: a warm near-white
%% page, the report's clay as a single accent down one edge, and a soft
%% wedge in the far corner for depth. The tint is kept very light so that
%% every text colour already chosen stays at full contrast, and so the
%% parchment panels still read as raised against it.
\newcommand{\bgplain}{%
  \begin{tikzpicture}[remember picture,overlay]
    \fill[parchment!40!white]
      (current page.south west) rectangle (current page.north east);
    \fill[ink]
      (current page.north west) rectangle
      ([yshift=-5pt]current page.north east);
    \fill[clay]
      ([yshift=-5pt]current page.north west) rectangle
      ([xshift=4pt]current page.south west);
    \fill[ink!7]
      ([xshift=-3.2cm]current page.south east) --
      (current page.south east) --
      ([yshift=3.2cm]current page.south east) -- cycle;
  \end{tikzpicture}}

%% The opening slide is the fullest one, so its variant adds depth with
%% two faint wedges rather than a solid band: a printed bar at the foot
%% would run underneath the list of names.
\newcommand{\bgtitle}{%
  \begin{tikzpicture}[remember picture,overlay]
    \fill[parchment!65!white]
      (current page.south west) rectangle (current page.north east);
    \fill[ink]
      (current page.north west) rectangle
      ([yshift=-5pt]current page.north east);
    \fill[clay]
      ([yshift=-5pt]current page.north west) rectangle
      ([xshift=4pt]current page.south west);
    \fill[ink!10]
      ([xshift=-5.0cm]current page.south east) --
      (current page.south east) --
      ([yshift=3.0cm]current page.south east) -- cycle;
    \fill[clay!10]
      (current page.south west) --
      ([xshift=4.2cm]current page.south west) --
      ([yshift=2.4cm]current page.south west) -- cycle;
  \end{tikzpicture}}

\newcommand{\eps}{\ensuremath{\varepsilon}}

%% A tinted panel for machine output and grammar dumps, so generated text
%% is never mistaken for prose. It is given a hairline edge because the
%% page behind it is no longer white.
\newcommand{\panel}[1]{%
  \begingroup\setlength{\fboxsep}{7pt}\setlength{\fboxrule}{0.4pt}%
  \noindent\fcolorbox{rule}{parchment}{%
    \begin{minipage}{\dimexpr\textwidth-16pt\relax}#1\end{minipage}}%
  \endgroup}

%% Screenshots. Missing files degrade to a labelled placeholder rather
%% than failing the build -- the same policy as the report.
\newcommand{\shot}[2]{%
  \setlength{\fboxsep}{0pt}\setlength{\fboxrule}{0.4pt}%
  \IfFileExists{screenshots/#1}
    {\fcolorbox{rule}{white}{\includegraphics[width=#2\linewidth]{screenshots/#1}}}
    {\IfFileExists{../screenshots/#1}
       {\fcolorbox{rule}{white}{\includegraphics[width=#2\linewidth]{../screenshots/#1}}}
       {\fcolorbox{rule}{parchment}{\begin{minipage}[c][3cm][c]{#2\linewidth}%
          \centering\small\color{clay}\itshape screenshot missing:\\
          {\ttfamily\footnotesize\upshape #1}\end{minipage}}}}}

\graphicspath{{./}{../}}
"""


# --------------------------------------------------------------------------
# The deck
# --------------------------------------------------------------------------

def build_slides() -> str:
    """Return the complete Beamer source for the presentation."""
    analyzer = Analyzer()
    results = analyzer.analyze_all(corpus.CORPUS, trace=True)
    report = frequency_report(results)
    prepared = prepare()

    worked = analyzer.analyze_text(WORKED_EXAMPLE, trace=True)

    words, phrases = len(WORDS), len(PHRASES)
    negatives_ok = sum(
        1 for _sid, text, _why in corpus.NEGATIVE_TESTS
        if not analyzer.analyze_text(text, trace=False).accepted
    )

    out: list[str] = []
    frames = 0

    def w(line: str = "") -> None:
        out.append(line)

    def frame(title: str, subtitle: str = "") -> None:
        """Open a frame and count it against the cap."""
        nonlocal frames
        frames += 1
        w(r"\begin{frame}{" + esc(title) + "}"
          + (r"{" + esc(subtitle) + "}" if subtitle else ""))

    def end_frame() -> None:
        w(r"\end{frame}")
        w("")

    w(PREAMBLE)
    w(r"\begin{document}")
    w("")
    w(r"\usebackgroundtemplate{\bgtitle}")
    w("")

    # ---------------------------------------------------------- 1 title
    frames += 1
    names = r" \\ ".join(
        esc(m.name) + r" {\ttfamily\footnotesize " + esc(m.matricule) + "}"
        for m in corpus.GROUP
    )
    w(r"\begin{frame}[plain]")
    w(r"\centering")
    w(r"\IfFileExists{ict-logo.jpg}")
    w(r"  {\includegraphics[height=1.9cm]{ict-logo.jpg}}")
    w(r"  {\IfFileExists{../ict-logo.jpg}")
    w(r"     {\includegraphics[height=1.9cm]{../ict-logo.jpg}}{}}")
    w(r"\\[0.5em]")
    w(r"{\color{rule}\rule{0.9\linewidth}{0.8pt}}\\[0.6em]")
    w(r"{\LARGE\bfseries\color{ink} Lexical and Syntactic Analysis\\[0.2em]")
    w(r"of Informal Urban Communication in Yaound\'e\par}")
    w(r"\vspace{0.4em}")
    w(r"{\color{rule}\rule{0.9\linewidth}{0.8pt}}\\[0.8em]")
    w(r"{\small\color{slate}" + esc(corpus.COURSE) + r"\par}")
    w(r"\vspace{0.9em}")
    w(r"{\footnotesize " + names + r"\par}")
    end_frame()

    w(r"\usebackgroundtemplate{\bgplain}")
    w("")

    # ------------------------------------------------- 2 problem/objective
    frame("The problem", "Why ordinary parsing techniques do not simply apply")
    w(r"\begin{columns}[T,onlytextwidth]")
    w(r"\begin{column}{0.54\textwidth}")
    w(r"\begin{itemize}\setlength{\itemsep}{0.5em}")
    w(r"\item Everyday speech in Yaound\'e mixes French, English, Pidgin "
      r"and Camfranglais {\bfseries inside a single sentence}.")
    w(r"\item Whitespace does not mark lexeme boundaries: "
      r"{\ttfamily Carrefour Obili} is {\bfseries one} place name.")
    w(r"\item The same form changes grammatical class with context, which "
      r"a lexer cannot see.")
    w(r"\item[] ")
    w(r"\item[{\color{clay}\bfseries Goal}] Apply the {\bfseries lexical} "
      r"and {\bfseries syntactic} phases of a compiler to this register, "
      r"and report honestly where they stop working.")
    w(r"\end{itemize}")
    w(r"\end{column}")
    w(r"\begin{column}{0.44\textwidth}")
    w(r"\panel{\small")
    w(r"\textbf{One corpus statement}\\[0.4em]")
    w(mono(WORKED_EXAMPLE) + r"\\[0.6em]")
    w(r"{\color{slate}\footnotesize")
    w(r"{\ttfamily Chef} --- French, used as a vocative\\")
    w(r"{\ttfamily drop} --- English verb, Pidgin sense\\")
    w(r"{\ttfamily for} --- Pidgin preposition, not English\\")
    w(r"{\ttfamily Carrefour Obili} --- one multiword lexeme\par}")
    w("}")
    w(r"\vspace{0.7em}")
    w(r"\footnotesize{\color{clay}"
      f"{len(report.mixed_statements)} of {len(results)}"
      r"} collected statements draw on more than one language.")
    w(r"\end{column}")
    w(r"\end{columns}")
    end_frame()

    # --------------------------------------------------------- 3 method
    frame("Method", "One pipeline, built and tested phase by phase")
    w(r"\centering")
    w(r"\begin{tikzpicture}[")
    w(r"  node distance=6mm,")
    w(r"  box/.style={draw=rule,line width=0.8pt,fill=parchment,"
      r"rounded corners=2pt,minimum height=9mm,inner xsep=4mm,"
      r"align=center,font=\small},")
    w(r"  lex/.style={box,draw=moss},")
    w(r"  syn/.style={box,draw=slate},")
    w(r"  arr/.style={-{Stealth[length=2mm]},draw=ink,line width=0.7pt}]")
    w(r"\node[box]            (src)  {Raw\\statement};")
    w(r"\node[lex,right=of src] (lex)  {Lexer\\{\footnotesize longest match}};")
    w(r"\node[lex,right=of lex] (tok)  {Token\\stream};")
    w(r"\node[syn,right=of tok] (par)  {LL(1)\\parser};")
    w(r"\node[syn,right=of par] (tree) {Parse tree\\+ verdict};")
    w(r"\draw[arr] (src) -- (lex);")
    w(r"\draw[arr] (lex) -- (tok);")
    w(r"\draw[arr] (tok) -- (par);")
    w(r"\draw[arr] (par) -- (tree);")
    w(r"\node[below=7mm of lex,font=\scriptsize,text=moss,align=center]"
      r" (l1) {lexical specification\\"
      + f"{phrases} multiword + {words} single-word entries" + "};")
    w(r"\node[below=7mm of par,font=\scriptsize,text=slate,align=center]"
      r" (l2) {grammar $\to$ LL(1) table\\"
      + f"{len(prepared.final.productions())} productions" + "};")
    w(r"\draw[arr,dashed,draw=moss] (l1) -- (lex);")
    w(r"\draw[arr,dashed,draw=slate] (l2) -- (par);")
    w(r"\end{tikzpicture}")
    w(r"\vspace{0.9em}")
    w(r"\begin{itemize}\setlength{\itemsep}{0.35em}")
    w(r"\item Corpus of {\color{clay}\bfseries " + str(len(results))
      + r"} statements, plus {\color{clay}\bfseries "
      + str(len(corpus.NEGATIVE_TESTS))
      + r"} constructed counter-examples that {\itshape must} be rejected.")
    w(r"\item Unknown input is {\bfseries reported}, never silently dropped.")
    w(r"\end{itemize}")
    end_frame()

    # -------------------------------------------------- 4 compiler phases
    #
    # The three diagram slides that follow are the same pictures the report
    # prints, drawn from yca.figures, so the talk and the document cannot
    # describe the system differently. Each gets a slide of its own: shrunk
    # into a column beside bullet points they would be decoration rather
    # than evidence, and unreadable past the second row of the room.
    frame("Where this project sits",
          "A compiler has six phases; we build the first two, properly")
    w(r"\centering")
    w(compiler_phases(slide_scale("phases")))
    w(r"\vspace{0.3em}")
    w(r"{\footnotesize Analysis is implemented and measured. Synthesis is "
      r"out of scope --- and saying so precisely is part of the answer.}")
    end_frame()

    # ---------------------------------------------------- 5 lexical phase
    frame("Lexical analysis", "Longest match, with multiword lexemes tried first")
    w(r"\begin{columns}[T,onlytextwidth]")
    w(r"\begin{column}{0.46\textwidth}")
    w(r"\begin{itemize}\setlength{\itemsep}{0.45em}")
    w(r"\item {\color{clay}\bfseries " + str(phrases)
      + r"} multiword lexemes are matched {\itshape before} single words, "
        r"so a compound is never split.")
    w(r"\item {\color{clay}\bfseries " + str(words)
      + r"} single-word entries carry token type, source language, "
        r"slang flag and gloss.")
    w(r"\item Spelling variation is folded to a normal form, so "
      r"{\ttfamily wa} and {\ttfamily wah} count as one item.")
    w(r"\item Corpus yields {\color{clay}\bfseries "
      + str(report.total_tokens) + r"} tokens over {\color{clay}\bfseries "
      + str(report.distinct_lexemes) + r"} distinct items.")
    w(r"\end{itemize}")
    w(r"\end{column}")
    w(r"\begin{column}{0.52\textwidth}")
    w(r"\panel{\scriptsize")
    w(r"\textbf{" + esc(WORKED_EXAMPLE) + r"}\\[0.5em]")
    w(r"\begin{tabular}{@{}r l l@{}}")
    w(r"\textbf{\#} & \textbf{lexeme} & \textbf{token}\\[0.2em]")
    for index, lexeme, ttype, _rule in token_table(worked):
        w(esc(index) + " & " + r"{\ttfamily " + esc(lexeme) + "} & "
          + r"{\ttfamily " + esc(ttype) + r"}\\")
    w(r"\end{tabular}")
    w(r"\\[0.6em]")
    w(r"{\color{slate}token stream}\\")
    w(mono(worked.lex.type_string() + " " + END))
    w("}")
    w(r"\end{column}")
    w(r"\end{columns}")
    end_frame()

    # ------------------------------------------------- 6 lexer automaton
    frame("The scanner as an automaton",
          "Three probes, tried in this order at every position")
    w(r"\centering")
    w(lexer_automaton(slide_scale("lexer")))
    w(r"\vspace{0.2em}")
    w(r"{\footnotesize The order {\itshape is} the specification: phrase "
      r"before word, word before pattern. That is what makes "
      r"{\ttfamily small small} one adverb.}")
    end_frame()

    # ------------------------------------------------------- 7 grammar
    frame("From a natural grammar to an LL(1) one",
          "The grammar was written honestly first, then transformed")
    w(r"\begin{columns}[T,onlytextwidth]")
    w(r"\begin{column}{0.5\textwidth}")
    w(r"{\small\color{clay}\bfseries 1. Remove left recursion}")
    w(r"\vspace{0.3em}")
    for step in prepared.recursion_steps:
        w(r"\panel{\scriptsize")
        for line in step.before:
            w(arrowed(line) + r"\\")
        w(r"\vspace{0.3em}{\color{clay}$\Downarrow$ " + esc(step.note)
          + r"}\\[0.3em]")
        for line in step.after:
            w(arrowed(line) + r"\\")
        w("}")
    w(r"\end{column}")
    w(r"\begin{column}{0.5\textwidth}")
    w(r"{\small\color{clay}\bfseries 2. Left-factor the common prefix}")
    w(r"\vspace{0.3em}")
    for step in prepared.factoring_steps:
        w(r"\panel{\scriptsize")
        for line in step.before:
            w(arrowed(line) + r"\\")
        w(r"\vspace{0.3em}{\color{clay}$\Downarrow$ " + esc(step.note)
          + r"}\\[0.3em]")
        for line in step.after:
            w(arrowed(line) + r"\\")
        w("}")
    w(r"\end{column}")
    w(r"\end{columns}")
    w(r"\vspace{0.8em}")
    w(r"\footnotesize Both transformations are performed {\bfseries in code}, "
      r"not by hand: {\ttfamily remove\_left\_recursion} and "
      r"{\ttfamily left\_factor} run every time the analyzer starts, so the "
      r"grammar shown and the grammar parsed cannot diverge.")
    end_frame()

    # --------------------------------------------------- 6 table/conflict
    frame("The LL(1) table --- and the one honest conflict")
    w(r"\begin{columns}[T,onlytextwidth]")
    w(r"\begin{column}{0.48\textwidth}")
    w(r"\begin{itemize}\setlength{\itemsep}{0.45em}")
    w(r"\item FIRST and FOLLOW are computed to a fixed point, then the "
      r"table is filled from them --- nothing is transcribed by hand.")
    w(r"\item {\color{clay}\bfseries "
      + str(len(prepared.final.productions()))
      + r"} productions over {\color{clay}\bfseries "
      + str(len(prepared.final.terminals))
      + r"} terminals.")
    w(r"\item An empty cell is a parse error, and the parser says "
      r"{\itshape which} terminal it expected.")
    w(r"\end{itemize}")
    w(r"\end{column}")
    w(r"\begin{column}{0.5\textwidth}")
    for (nt, terminal), note in DOCUMENTED_CONFLICTS.items():
        w(r"\panel{\footnotesize")
        w(r"{\color{clay}\bfseries Conflict at M[" + esc(nt) + ", "
          + esc(terminal) + r"]}\\[0.4em]")
        w(esc(
            "After a noun phrase, a following NOUN could extend that phrase "
            "(Carrefour Obili as one name) or begin a new argument."
        ) + r"\\[0.4em]")
        w(r"{\color{slate}This is a genuine ambiguity --- the "
          r"dangling-else of this grammar. No rewriting removes it.}\\[0.4em]")
        w(r"{\bfseries Resolved} in favour of greedy compounding, "
          r"which is the correct reading for every compound in the corpus.")
        w("}")
        break
    w(r"\vspace{0.5em}")
    w(r"\footnotesize {\color{moss}\bfseries "
      + str(len(undocumented_conflicts(prepared.table)))
      + r"} undocumented conflicts. The one above is declared in the "
        r"source and checked by a unit test, so it cannot be quietly "
        r"forgotten.")
    w(r"\end{column}")
    w(r"\end{columns}")
    end_frame()

    # ------------------------------------------------------- 7 results
    # ------------------------------------------------- 9 parser machine
    frame("The parser as a stack machine",
          "One token of lookahead, one stack, and a table that decides")
    w(r"\centering")
    w(parser_machine(slide_scale("parser")))
    w(r"\vspace{0.2em}")
    w(r"{\footnotesize The driver contains no grammar. Change the grammar "
      r"and the table changes; the code does not.}")
    end_frame()

    # ------------------------------------------------------- 10 results
    frame("Results", "Every acceptance carries a derivation; every rejection, a reason")
    w(r"\begin{columns}[T,onlytextwidth]")
    w(r"\begin{column}{0.46\textwidth}")
    w(r"\panel{\footnotesize")
    w(r"\begin{tabular}{@{}l r@{}}")
    w(r"Statements collected & {\bfseries " + str(len(results)) + r"}\\")
    w(r"Accepted & {\color{moss}\bfseries " + str(report.accepted) + r"}\\")
    w(r"Rejected & {\color{clay}\bfseries " + str(report.rejected) + r"}\\")
    w(r"Counter-examples & {\bfseries " + str(len(corpus.NEGATIVE_TESTS)) + r"}\\")
    w(r"Correctly rejected & {\color{moss}\bfseries " + str(negatives_ok)
      + r"}\\")
    w(r"Tokens & " + str(report.total_tokens) + r"\\")
    w(r"Distinct items & " + str(report.distinct_lexemes) + r"\\")
    w(r"Type/token ratio & " + esc(pct(report.type_token_ratio * 100)) + r"\\")
    w(r"\end{tabular}")
    w("}")
    w(r"\vspace{0.4em}")
    w(r"{\footnotesize\color{clay}\bfseries A rejection, with its reason}")
    w(r"\vspace{0.2em}")
    w(r"\shot{sets-panel.png}{0.88}")
    w(r"\end{column}")
    w(r"\begin{column}{0.52\textwidth}")
    w(r"{\footnotesize\color{clay}\bfseries FIRST and FOLLOW, computed at "
      r"run time}")
    w(r"\vspace{0.25em}")
    w(r"\shot{trace-rejected.png}{0.84}")
    w(r"\vspace{0.35em}")
    w(r"\footnotesize The parser reports the stack, the remaining input and "
      r"the terminal it expected --- not merely that the sentence failed.")
    w(r"\end{column}")
    w(r"\end{columns}")
    end_frame()

    # ------------------------------------------------------ 11 software
    frame("The analyzer", "One engine, three front ends, live on the web")
    w(r"\begin{columns}[T,onlytextwidth]")
    w(r"\begin{column}{0.62\textwidth}")
    w(r"\shot{app-overview.png}{0.96}")
    w(r"\end{column}")
    w(r"\begin{column}{0.36\textwidth}")
    w(r"\begin{itemize}\setlength{\itemsep}{0.35em}\small")
    w(r"\item All three front ends construct the {\bfseries same} "
      r"{\ttfamily Analyzer}, so they cannot disagree about a verdict.")
    w(r"\item Tabs for tokens, tree, trace, derivation, FIRST/FOLLOW, "
      r"corpus, statistics --- and {\bfseries Grammar}, which proposes a "
      r"spelling when a word is rejected.")
    w(r"\item {\bfseries No third-party packages} --- the standard "
      r"library only.")
    w(r"\item Deployed over HTTPS:")
    # The URL is one unbreakable word wider than this narrow column, so it
    # is set ragged-right at a smaller size rather than left to run past
    # the column edge into the screenshot beside it.
    w(r"\item[] \raggedright{\ttfamily\tiny\color{clay} "
      + esc(LIVE_URL) + "}")
    w(r"\end{itemize}")
    w(r"\end{column}")
    w(r"\end{columns}")
    end_frame()

    # ------------------------------------------------------ 12 findings
    frame("What we found", "The interesting result is where the method stops")
    w(r"\begin{columns}[T,onlytextwidth]")
    w(r"\begin{column}{0.49\textwidth}")
    w(r"{\small\color{moss}\bfseries What worked}")
    w(r"\begin{itemize}\setlength{\itemsep}{0.35em}\small")
    w(r"\item A restricted slice of the register is genuinely context-free "
      r"and parses predictively.")
    w(r"\item Multiword lexemes solve compounding at the {\bfseries lexical} "
      r"level, where it belongs.")
    w(r"\item Normalising spelling variants makes frequency counts "
      r"meaningful across transcriptions.")
    w(r"\end{itemize}")
    w(r"\end{column}")
    w(r"\begin{column}{0.49\textwidth}")
    w(r"{\small\color{clay}\bfseries What did not}")
    w(r"\begin{itemize}\setlength{\itemsep}{0.35em}\small")
    w(r"\item Code-mixing operates {\bfseries below the clause}, sometimes "
      r"inside a single lexeme --- a CFG cannot describe that.")
    w(r"\item Aspect is marked by free particles, not inflection, so the "
      r"lexer cannot resolve class from form.")
    w(r"\item Noun compounding is {\bfseries genuinely ambiguous}; we "
      r"document the resolution rather than hide it.")
    w(r"\item The corpus is transcribed by ear, without recordings.")
    w(r"\end{itemize}")
    w(r"\end{column}")
    w(r"\end{columns}")
    end_frame()

    # --------------------------------------------------- 13 conclusion
    frame("Conclusion")
    w(r"\begin{itemize}\setlength{\itemsep}{0.55em}")
    w(r"\item The lexical and syntactic phases of a compiler {\bfseries do} "
      r"apply to informal Yaound\'e speech --- over a deliberately "
      r"restricted grammar, with "
      + f"{report.accepted} of {len(results)}"
      + r" statements accepted and all "
      + str(len(corpus.NEGATIVE_TESTS))
      + r" counter-examples rejected.")
    w(r"\item Every number in this talk and in the report is "
      r"{\bfseries computed}, not asserted: the same code that analyses the "
      r"corpus writes the document and these slides.")
    w(r"\item The clearest next step is {\bfseries more data}, not more "
      r"grammar. Replacing the corpus regenerates every table, figure and "
      r"percentage automatically.")
    w(r"\end{itemize}")
    w(r"\vspace{0.6em}")
    w(r"\panel{\small\centering Try it: "
      r"{\ttfamily\color{clay} " + esc(LIVE_URL) + r"}\\[0.3em]"
      r"{\footnotesize\color{slate}\ttfamily "
      r"python -m yca web\quad$\cdot$\quad python -m yca test"
      r"\quad$\cdot$\quad python -m yca report}}")
    w(r"\vspace{0.5em}")
    w(r"\centering{\color{ink}\large Thank you --- questions?}")
    end_frame()

    w(r"\end{document}")

    if frames > MAX_SLIDES:
        raise AssertionError(
            f"the deck has grown to {frames} frames but the talk allows "
            f"{MAX_SLIDES}; merge or drop a slide rather than raising the cap"
        )

    return "\n".join(out) + "\n"


def write_slides(path: str | Path = "docs/slides.tex") -> Path:
    """Write the Beamer source as UTF-8 and return the path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_slides(), encoding="utf-8")
    return target
