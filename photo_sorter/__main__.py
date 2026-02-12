"""
Allow running the package as: python -m photo_sorter

Copyright (c) 2026 Benjoe Vidal
Licensed under the MIT License.
"""

from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
