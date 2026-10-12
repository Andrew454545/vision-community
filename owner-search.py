"""Operator entrypoint. No registration or activation is performed here."""
from pathlib import Path
import sys

# Supports a pinned private Python launched with -I -B: ignore PYTHONPATH/user
# packages and import only this deliberately selected checkout's application.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from community.owner_search_service import main

if __name__ == '__main__':
    raise SystemExit(main())
