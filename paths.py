"""
Centralized path resolution for Backlog Reaper.
Handles both development mode and packaged (PyInstaller) mode.
"""

import sys
import os
import shutil
from pathlib import Path

def is_packaged():
    """Check if running as PyInstaller executable."""
    packaged = getattr(sys, 'frozen', False)
    if packaged:
        print("paths.py [DEBUG]: Running in packaged mode (PyInstaller)")
    return packaged

def get_base_dir():
    """
    Get directory for writable user data (database, settings, exports, characters).

    In packaged mode: Directory containing the .exe file
    In development mode: Project root directory
    """
    if is_packaged():
        base_dir = Path(sys.executable).parent
        print(f"paths.py [DEBUG]: Writable base directory resolved to {base_dir}")
        return base_dir
    return Path(__file__).parent

def get_asset_path(*parts):
    """
    Get path to bundled read-only assets (icons, fonts, default images).

    In packaged mode: Path to _MEIPASS bundle directory
    In development mode: Relative path from project root
    """
    if is_packaged() and hasattr(sys, '_MEIPASS'):
        asset_path = Path(sys._MEIPASS).joinpath(*parts)
        print(f"paths.py [DEBUG]: Asset path resolved to MEIPASS: {asset_path}")
        return asset_path
    return get_base_dir().joinpath(*parts)

def get_data_dir():
    """
    Get directory for user data (chats, exports).
    For portable mode, same as base directory.
    """
    return get_base_dir()

def ensure_dirs():
    """
    Create necessary directories on first run.
    Copies default Reaper.png from bundled assets to user characters directory.
    """
    base = get_base_dir()

    # Create required subdirectories
    directories = [
        base / "data" / "chats",
        base / "exports",
        base / "characters"
    ]

    for dir_path in directories:
        dir_path.mkdir(parents=True, exist_ok=True)

    # Copy default Reaper.png from bundled assets to user characters directory
    # Only if characters directory is empty and default character doesn't exist
    characters_dir = base / "characters"
    default_char_src = get_asset_path("assets", "characters", "Reaper.png")
    default_char_dst = characters_dir / "Reaper.png"

    if (default_char_src.exists() and
        not default_char_dst.exists() and
        len(list(characters_dir.glob("*"))) == 0):
        try:
            shutil.copy2(default_char_src, default_char_dst)
            print(f"Copied default character to: {default_char_dst}")
        except Exception as e:
            print(f"Warning: Could not copy default character: {e}")

    return True
