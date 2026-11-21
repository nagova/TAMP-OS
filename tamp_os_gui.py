#!/usr/bin/env python3
"""
TAMP-OS v2 alias wrapper for tamp-os_gui.py
Allows execution via either `python tamp-os_gui.py` or `python tamp_os_gui.py`.
"""
import runpy
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).parent / "tamp-os_gui.py"
    runpy.run_path(str(target), run_name="__main__")
