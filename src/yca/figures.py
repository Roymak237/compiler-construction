"""Generated TikZ figures explaining how the analyzer works.

Three diagrams live here, and both the report and the slide deck draw them
from this one module so the two documents can never disagree about how the
system works:

``lexer_automaton()``
    The scanner as a finite-state machine, showing the longest-match order
    (phrases, then words, then patterns) and the fact that an unrecognised
    run still produces a token rather than disappearing.

``parser_machine()``
    The predictive parser as a stack machine: input tape, stack, parse table,
    and the single joint condition under which it accepts.

``compiler_phases()``
    Where this project sits in the classical phase sequence of a compiler --
    which phases are implemented, and which are deliberately out of scope.

Every figure compiles unchanged in an ``article`` and inside a ``beamer``
frame, which imposes four rules on the source below:

* no per-cent comments and no raw dollar signs, because the report's own
  validation tests treat either as an unescaped special character;
* no colour or TikZ library that both preambles do not already declare;
* explicit coordinates rather than chained relative placement, so the
  geometry can be reasoned about and nothing silently overlaps when a label
  changes length;
* a ``scale`` argument on every figure, because a diagram sized for a page
  is unreadable at the back of a lecture theatre, and one sized for a
  projector wastes half a page.
"""

from __future__ import annotations

__all__ = [
    "lexer_automaton",
    "parser_machine",
    "compiler_phases",
    "figure_names",
    "figure_sizes",
    "slide_scale",
]


def _picture(body: str, scale: float, extra: str = "") -> str:
    """Wrap *body* in a ``tikzpicture`` at *scale* with the shared styles.

    Keeping one style block here is what lets the report and the deck render
    the same picture: between the two documents, only the scale differs.
    """
    return (
        "\\begin{tikzpicture}[\n"
        f"  scale={scale:g}, transform shape,\n"
        "  font=\\small,\n"
        "  >={Stealth[length=2.2mm,width=1.7mm]},\n"
        "  state/.style={draw=ink, fill=white, line width=0.9pt,\n"
        "                circle, minimum size=10mm, inner sep=0.3mm,\n"
        "                align=center, font=\\scriptsize\\bfseries},\n"
        "  probe/.style={draw=moss, fill=moss!8, line width=0.9pt,\n"
        "                rounded corners=2.5pt, align=center,\n"
        "                font=\\scriptsize, inner sep=1.5mm},\n"
        "  final/.style={draw=clay, fill=clay!10, line width=1pt,\n"
        "                rounded corners=2.5pt, align=center,\n"
        "                font=\\scriptsize\\bfseries, inner sep=1.5mm},\n"
        "  box/.style={draw=rule, fill=parchment, line width=0.7pt,\n"
        "              rounded corners=1.5pt, align=center,\n"
        "              font=\\scriptsize\\ttfamily, inner sep=1.3mm},\n"
        "  cell/.style={draw=rule, fill=white, line width=0.6pt,\n"
        "               minimum width=9mm, minimum height=5mm,\n"
        "               font=\\tiny\\ttfamily, inner sep=0.5mm},\n"
        "  live/.style={draw=slate, fill=slate!8, line width=1pt,\n"
        "               rounded corners=2.5pt, align=center,\n"
        "               font=\\scriptsize, inner sep=1.6mm},\n"
        "  dead/.style={draw=rule, fill=white, line width=0.7pt,\n"
        "               rounded corners=2.5pt, align=center,\n"
        "               font=\\scriptsize, inner sep=1.6mm,\n"
        "               dash pattern=on 2pt off 1.6pt, text=slate!60},\n"
        "  flow/.style={->, line width=0.9pt, draw=ink!75},\n"
        "  back/.style={->, line width=0.7pt, draw=slate!70,\n"
        "               dash pattern=on 2pt off 1.6pt},\n"
        "  feed/.style={->, line width=0.7pt, draw=clay!80,\n"
        "               dash pattern=on 2pt off 1.6pt},\n"
        "  lab/.style={font=\\tiny, inner sep=0.6mm, fill=white,\n"
        "              text=ink!85, align=center},\n"
        "  note/.style={font=\\tiny\\itshape, text=slate, align=center},\n"
        f"{extra}]\n"
        f"{body}\n"
        "\\end{tikzpicture}"
    )


# --------------------------------------------------------------------------
# 1. The lexical analyzer as an automaton
# --------------------------------------------------------------------------
#
# Coordinate plan, in centimetres.  The three probes sit in one column so
# that "tried in this order" is the shape of the picture and not merely a
# sentence in the caption:
#
#        x=0        x=2.7       x=7.2                    x=11.9
#   y=+1.7  .............. return corridor ..............
#   y=0     start ----> skip ----> phrase probe ------.
#   y=-2.0                         word probe --------> emit
#   y=-2.7  done                                       |
#   y=-4.0                         pattern probe ------'
#   y=-5.8                         UNKNOWN + LexError
#
# The return edge runs above every node at y=+1.7 and the UNKNOWN edge below
# every node at y=-6.9, so neither crosses anything.

def lexer_automaton(scale: float = 1.0) -> str:
    """Return the scanning automaton as a TikZ picture.

    The point the picture has to make is the *order* of the three probes.
    A phrase is tried before a word and a word before a regular expression,
    which is why ``small small`` becomes one adverb rather than two
    adjectives, and why ``500 frs`` becomes one numeral rather than a number
    beside a noun.  The dashed return edge is what makes this a loop over the
    input rather than a single decision.
    """
    body = r"""
\node[state] (start) at (0,0) {start};
\node[live, text width=20mm] (skip) at (2.7,0)
  {\textbf{skip}\\ spaces, quotes,\\ brackets};

\node[probe, text width=32mm] (ph) at (7.2,0)
  {\textbf{1. phrase probe}\\ longest run of two or three\\
   words listed in \texttt{PHRASES}};
\node[probe, text width=32mm] (vo) at (7.2,-2.0)
  {\textbf{2. word probe}\\ the folded word, looked up\\
   in \texttt{WORDS}};
\node[probe, text width=32mm] (re) at (7.2,-4.0)
  {\textbf{3. pattern probe}\\ first rule of \texttt{PATTERNS}\\
   that matches at this position};

\node[final, text width=17mm] (emit) at (11.9,-2.0) {emit token};
\node[final, text width=19mm] (unk) at (11.9,-5.8)
  {UNKNOWN\\ and a LexError};

\node[state] (done) at (0,-2.7) {done};

\draw[flow] (start) -- (skip);
\draw[flow] (skip) -- (ph);

\draw[flow] (ph.east) -| node[lab, pos=0.25, above] {hit} (emit.north);
\draw[flow] (vo.east) -- node[lab, above] {hit} (emit.west);
\draw[flow] (re.east) -| node[lab, pos=0.25, below] {hit} (emit.south);

\draw[flow] (ph) -- node[lab, right] {miss} (vo);
\draw[flow] (vo) -- node[lab, right] {miss} (re);
\draw[flow] (re.south) |- node[lab, pos=0.7, above] {no rule} (unk.west);

\draw[back] (emit.east) -- (13.5,-2.0) -- (13.5,1.7)
  -- node[lab, above] {advance past the match, then scan the next position}
  (2.7,1.7) -- (skip.north);
\draw[back] (unk.south) -- (11.9,-6.9) -- (13.5,-6.9) -- (13.5,-2.35);

\draw[flow] (skip.south west) -- node[lab, sloped, above] {input exhausted}
  (done.north east);

\node[note, text width=42mm] at (2.4,-5.2)
  {Longest match first: all three probes run in this order at every
   position, so a longer reading always wins, and no part of the
   transcription is ever silently discarded.};
"""
    return _picture(body.strip("\n"), scale)


# --------------------------------------------------------------------------
# 2. The parser as a stack machine
# --------------------------------------------------------------------------
#
# Coordinate plan, in centimetres.  The tape runs along the top, the three
# pieces of parser state sit in one row beneath it, and the two outcomes are
# below that:
#
#   y=0      VOC SEP VERB [PRON] PREP NOUN TERM $
#   y=-2.9   stack  ->  the driver  <-  table M
#   y=-5.4          REJECTED      ACCEPTED

def parser_machine(scale: float = 1.0) -> str:
    """Return the predictive parser as a TikZ picture.

    Three things must be visible at once for the diagram to earn its space:
    that the parser reads one token of lookahead and never backtracks, that
    the only memory it has is the stack, and that the table -- not the code --
    chooses the production.  Acceptance requires the stack and the input to
    finish together, so that is drawn as one joint condition rather than as
    two separate outcomes.
    """
    body = r"""
\node[note] at (3.4,0.75) {input, read once from left to right};

\node[box] (t1) at (0.00,0) {VOC};
\node[box] (t2) at (0.97,0) {SEP};
\node[box] (t3) at (1.94,0) {VERB};
\node[box, draw=clay, fill=clay!12, line width=1pt] (t4) at (2.91,0) {PRON};
\node[box] (t5) at (3.88,0) {PREP};
\node[box] (t6) at (4.85,0) {NOUN};
\node[box] (t7) at (5.82,0) {TERM};
\node[box] (t8) at (6.79,0) {\textdollar};

\node[note, text=clay] at (2.91,-0.52) {lookahead};

\node[live, text width=34mm] (ctrl) at (3.4,-2.9)
  {\textbf{the driver}\\[1pt]
   two actions only: pop and match a\\ terminal, or pop a nonterminal and\\
   push the right-hand side};

\node[box, text width=19mm, inner sep=1.5mm] (stk) at (0.4,-2.9)
  {Items\\ ClauseTail\\ Clause\\ \textdollar};
\node[note] at (0.4,-1.72) {stack, top first};

\node[cell] (m11) at (7.10,-2.35) {Clause};
\node[cell] (m12) at (8.00,-2.35) {--};
\node[cell] (m13) at (8.90,-2.35) {Items};
\node[cell] (m21) at (7.10,-2.85) {--};
\node[cell] (m22) at (8.00,-2.85) {Tail};
\node[cell] (m23) at (8.90,-2.85) {--};
\node[cell] (m31) at (7.10,-3.35) {Opener};
\node[cell] (m32) at (8.00,-3.35) {--};
\node[cell] (m33) at (8.90,-3.35) {--};
\node[note] at (8.00,-1.72) {the table M[A, a]};

\node[final, text width=20mm] (acc) at (5.2,-5.4) {ACCEPTED};
\node[final, text width=20mm] (rej) at (1.6,-5.4) {REJECTED};

\draw[flow] (t4.south) -- (2.91,-1.05) -- (3.4,-1.05) -- (ctrl.north);
\draw[flow] (stk.east) -- (ctrl.west);
\draw[feed] (m21.west) -- node[lab, above] {which production} (ctrl.east);

\draw[flow] (ctrl.south east) -- node[lab, sloped, above, text width=23mm]
  {stack and input empty together} (acc.north);
\draw[flow] (ctrl.south west) -- node[lab, sloped, above, text width=21mm]
  {empty cell, or a mismatch} (rej.north);

\node[note, text width=74mm] at (4.2,-6.5)
  {Every step is recorded, so a rejection is justified with the exact stack,
   the lookahead and the table cell that was empty, rather than merely
   announced.};
"""
    return _picture(body.strip("\n"), scale)


# --------------------------------------------------------------------------
# 3. The compiler phases
# --------------------------------------------------------------------------
#
# Coordinate plan, in centimetres.  Analysis runs along the top and synthesis
# along the bottom, which keeps the picture close to square instead of a
# ribbon too wide to read from the back of a room:
#
#   y=+2.1              error reporting and correction
#   y=0      utterance -> lexical -> syntax --.
#   y=-1.9      lexical spec ^      ^ grammar |
#   y=-3.0   .............. parse tree .......'
#   y=-4.2   semantic -> IR -> optimise -> code generation

def compiler_phases(scale: float = 1.0) -> str:
    """Return the classical phase sequence with this project's scope marked.

    A compiler-construction project is judged partly on knowing where it
    stops.  Solid boxes are phases this analyzer implements and tests; dashed
    boxes are the synthesis phases a full compiler would follow with, drawn so
    that the boundary is a claim the reader can check rather than an omission
    they have to notice.
    """
    body = r"""
\node[box, text width=22mm] (src) at (0,0) {transcribed\\ utterance};
\node[live, text width=25mm] (lex) at (3.4,0)
  {\textbf{lexical analysis}\\ {\tiny lexer.py}};
\node[live, text width=25mm] (syn) at (6.9,0)
  {\textbf{syntax analysis}\\ {\tiny parser.py}};

\node[dead, text width=22mm] (sem) at (0.7,-4.2) {semantic\\ analysis};
\node[dead, text width=22mm] (ir)  at (3.5,-4.2) {intermediate\\ code};
\node[dead, text width=22mm] (opt) at (6.3,-4.2) {optimisation};
\node[dead, text width=22mm] (gen) at (9.1,-4.2) {code\\ generation};

\node[box, text width=29mm] (spec) at (3.4,-1.9)
  {PHRASES, WORDS,\\ PATTERNS};
\node[box, text width=29mm] (gram) at (6.9,-1.9)
  {grammar, FIRST,\\ FOLLOW, table M};

\node[live, text width=58mm, draw=clay, fill=clay!8] (err) at (5.15,2.1)
  {\textbf{error reporting and correction}\\[1pt]
   {\tiny every unknown lexeme and every empty table cell is reported with a
    position, and answered with the closest declared spelling}};

\draw[flow] (src) -- (lex);
\draw[flow] (lex) -- node[lab, above] {tokens} (syn);
\draw[flow] (sem) -- (ir);
\draw[flow] (ir) -- (opt);
\draw[flow] (opt) -- (gen);

\draw[flow] (syn.east) -- (10.4,0) -- (10.4,-3.0)
  -- node[lab, above] {parse tree} (0.7,-3.0) -- (sem.north);

\draw[feed] (spec.north) -- (lex.south);
\draw[feed] (gram.north) -- (syn.south);

\draw[feed] (lex.north) -- (err.south west);
\draw[feed] (syn.north) -- (err.south);

\node[note, text width=86mm] at (4.6,-5.4)
  {Solid: implemented, tested and measured in this project. Dashed: the
   synthesis phases a full compiler would add, deliberately outside the scope
   of a lexical and syntactic analyzer.};
"""
    return _picture(body.strip("\n"), scale)


#: Human-readable titles, so the report caption and the slide heading name
#: the same picture the same way.
figure_names: dict[str, str] = {
    "lexer": "The lexical analyzer as a finite-state scanner",
    "parser": "The predictive parser as a stack machine",
    "phases": "Where the analyzer sits among the phases of a compiler",
}

#: Natural size in millimetres at ``scale=1``, measured by boxing each
#: picture in a test compilation rather than estimated.  Callers use it to
#: choose a scale that fits the page or the slide instead of guessing:
#: the report has about 174mm of text width, a 16:9 beamer frame has about
#: 140mm of width and 62mm of usable height below the title.
figure_sizes: dict[str, tuple[float, float]] = {
    "lexer": (141.0, 89.3),
    "parser": (100.7, 79.4),
    "phases": (116.6, 87.8),
}


def slide_scale(key: str, *, width: float = 138.0, height: float = 60.0) -> float:
    """Return the largest scale at which figure *key* fits a beamer frame.

    Rounded down to two places so the figure never sits flush against the
    frame edge, which is what turns a fitting picture into an overfull box.
    """
    natural_w, natural_h = figure_sizes[key]
    fit = min(width / natural_w, height / natural_h)
    return int(fit * 100) / 100.0
