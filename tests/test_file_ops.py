"""Tests for file operations (copy, move, unique path)."""

from pathlib import Path

import pytest

from photo_sorter.file_ops import (
    ensure_directory,
    unique_destination_path,
    copy_image,
    move_image,
)


def test_ensure_directory(tmp_path):
    d = tmp_path / "a" / "b" / "c"
    ensure_directory(d)
    assert d.is_dir()
    ensure_directory(d)  # idempotent
    assert d.is_dir()


def test_unique_destination_path(tmp_path):
    (tmp_path / "photo.jpg").write_text("x")
    p = unique_destination_path(tmp_path, "photo.jpg")
    assert p == tmp_path / "photo (1).jpg"
    p.write_text("y")
    p2 = unique_destination_path(tmp_path, "photo.jpg")
    assert p2 == tmp_path / "photo (2).jpg"


def test_unique_destination_path_no_overwrite(tmp_path):
    p = unique_destination_path(tmp_path, "new.jpg")
    assert p == tmp_path / "new.jpg"


def test_copy_image(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "img.jpg").write_text("content")
    dest_dir = tmp_path / "out" / "Location"
    result = copy_image(src / "img.jpg", dest_dir)
    assert result == dest_dir / "img.jpg"
    assert result.read_text() == "content"
    assert (src / "img.jpg").read_text() == "content"  # original unchanged


def test_copy_image_avoids_overwrite(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "img.jpg").write_text("v1")
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    (dest_dir / "img.jpg").write_text("existing")
    result = copy_image(src / "img.jpg", dest_dir)
    assert result == dest_dir / "img (1).jpg"
    assert result.read_text() == "v1"
    assert (dest_dir / "img.jpg").read_text() == "existing"


def test_move_image(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "img.jpg").write_text("content")
    dest_dir = tmp_path / "out" / "Location"
    result = move_image(src / "img.jpg", dest_dir)
    assert result == dest_dir / "img.jpg"
    assert result.read_text() == "content"
    assert not (src / "img.jpg").exists()
