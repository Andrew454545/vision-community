"""Pins shared by private Mac startup and safe runtime-link accounting."""
import hashlib
import json
from pathlib import Path

PYTHON_FOLDER = 'python-3.14.8-20261003-arm64'
PYTHON_RELATIVE = 'python/bin/python3.14'
INVENTORY_SHA256 = 'a0f5d70672a69e5f34433bc7f2de43a2c85443af610007711d20f00334fc0c0d'
RESOURCES = Path(__file__).resolve().parents[1] / 'macos'


def runtime_links(root):
    """Exact same-parent links from the pinned inventory; never follow them.

    This does not establish runtime approval. Startup separately checks every
    file before the interpreter runs; storage scans account file/link sizes.
    """
    from community.mac_starter import regular
    runtime = regular(Path(root) / PYTHON_FOLDER, directory=True, missing=True)
    if not runtime.exists():
        return {}
    manifest = regular(RESOURCES / 'python-arm64-inventory.json')
    if manifest.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('private_python_mismatch')
    body = manifest.read_bytes()
    if hashlib.sha256(body).hexdigest() != INVENTORY_SHA256:
        raise ValueError('private_python_mismatch')
    value = json.loads(body)
    return {PYTHON_FOLDER + '/' + name: target for name, target in value['links'].items()}
