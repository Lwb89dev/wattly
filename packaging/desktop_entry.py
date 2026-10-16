"""PyInstaller entry point — frozen ``wattly`` binary.

Building ``python -m wattly`` directly would name the artifact ``__main__``;
this thin wrapper keeps the binary name stable across platforms and opens
the standalone pywebview window (no launcher scripts involved).
"""

import sys

from wattly.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
