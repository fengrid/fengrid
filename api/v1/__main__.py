"""python -m api.v1 — run the Fengrid REST API server.

    python -m api.v1 --db ~/.local/share/fengrid/library.db --port 8642
"""

import sys

from .server import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
