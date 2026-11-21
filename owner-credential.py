"""Explicit interactive operator setup. Importing this file starts nothing."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from community.owner_credential_provision import main

if __name__ == '__main__':
    raise SystemExit(main())
