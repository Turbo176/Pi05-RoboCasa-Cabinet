"""Process-local compatibility for a venv based on an older Anaconda.

Anaconda 2024's private MSVC 14.27 DLL can initialize MuJoCo plugins
incorrectly. Loading the installed System32 C++ runtime BEFORE MuJoCo
fixes this machine. This does not copy DLLs or edit the system or packages.
"""
import ctypes
import os
import sys
from pathlib import Path


def prepare_runtime():
    if sys.platform == "win32":
        library = Path(os.environ["SystemRoot"]) / "System32" / "msvcp140.dll"
        return ctypes.WinDLL(str(library))
    return None
