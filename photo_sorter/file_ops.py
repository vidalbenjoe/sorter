"""
Create destination folders and copy or move image files without overwriting.
"""

import shutil
from pathlib import Path
from typing import Optional


def ensure_directory(path: str | Path) -> Path:
    """Create the directory (and parents) if it does not exist. Return Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def unique_destination_path(dest_dir: Path, filename: str) -> Path:
    """
    Return a path under dest_dir for the given filename that does not overwrite
    an existing file. If dest_dir/filename exists, add a suffix like (1), (2), etc.
    """
    base = dest_dir / filename
    if not base.exists():
        return base

    stem = base.stem
    suffix = base.suffix
    n = 1
    while True:
        candidate = dest_dir / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def copy_image(source: Path, dest_dir: Path, dest_filename: Optional[str] = None) -> Path:
    """
    Copy the file at source into dest_dir. Use dest_filename if provided,
    otherwise source.name. Avoids overwriting by adding (1), (2), ... if needed.

    Returns the path of the copied file.
    """
    ensure_directory(dest_dir)
    name = dest_filename if dest_filename is not None else source.name
    dest_path = unique_destination_path(dest_dir, name)
    shutil.copy2(source, dest_path)
    return dest_path


def move_image(source: Path, dest_dir: Path, dest_filename: Optional[str] = None) -> Path:
    """
    Move the file at source into dest_dir. Use dest_filename if provided,
    otherwise source.name. Avoids overwriting by adding (1), (2), ... if needed.

    Returns the path of the moved file.
    """
    ensure_directory(dest_dir)
    name = dest_filename if dest_filename is not None else source.name
    dest_path = unique_destination_path(dest_dir, name)
    shutil.move(str(source), str(dest_path))
    return dest_path
