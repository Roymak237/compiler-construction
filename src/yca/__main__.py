"""Entry point for ``python -m yca``.

This module also tolerates being run as a plain script -- pressing Run in an
editor on this file, for instance.  In that case Python does not know the
file belongs to the ``yca`` package, so ``from .cli import main`` has no
parent package to resolve against and raises ImportError.  The fallback
below puts ``src`` on the path and re-imports absolutely, so both of these
work:

    python -m yca gui                 # the normal way
    python src/yca/__main__.py gui    # pressing Run in an editor
"""

from __future__ import annotations

try:
    from .cli import main
except ImportError:  # run as a script: there is no parent package
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from yca.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
