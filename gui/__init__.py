# gui/__init__.py
import sys as _sys
from . import main_window as _mw
_sys.modules.setdefault("main_window", _mw)