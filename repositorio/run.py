"""Hoshu Cockpit entry point."""

import sys
from pathlib import Path

# Ensure repository root is on sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from source.app import create_app

if __name__ == "__main__":
    app = create_app()
    print("\n" + "=" * 60)
    print("  Hoshu (保守) — Operations Cockpit")
    print("  Acesse a interface web em: http://127.0.0.1:5000")
    print("=" * 60 + "\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
