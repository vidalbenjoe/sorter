"""
Allow running the package as: python -m photo_sorter
"""

from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
