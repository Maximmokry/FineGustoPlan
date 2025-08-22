# services/gui_helpers.py
from __future__ import annotations
from typing import Callable, Optional, Tuple

import PySimpleGUIQt as sg
QtCore = sg.QtCore

# ---- jednoduchý on/off debug ----
_DEBUG_ENABLED = False
def dbg_set_enabled(flag: bool) -> None:
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = bool(flag)

def _dbg(msg: str) -> None:
    if _DEBUG_ENABLED:
        try:
            print(msg, flush=True)
        except Exception:
            pass

# ---- drobné utility ----
def get_window_location(win) -> Optional[Tuple[int, int]]:
    try:
        x, y = win.current_location()
        return int(x), int(y)
    except Exception:
        return None

def get_column_scroll(win, col_key: str) -> Optional[int]:
    try:
        col = win[col_key]
        return col.Widget.verticalScrollBar().value()
    except Exception:
        return None

def set_column_scroll(win, col_key: str, value: Optional[int]) -> None:
    try:
        if value is not None:
            win[col_key].Widget.verticalScrollBar().setValue(int(value))
    except Exception:
        pass

def _schedule(delay_ms: int, fn) -> None:
    try:
        sg.QtCore.QTimer.singleShot(int(delay_ms), fn)
        _dbg(f"[GUI-HELPERS] schedule({delay_ms}ms, {getattr(fn,'__name__','lambda')})")
    except Exception as e:
        _dbg(f"[GUI-HELPERS] schedule fail @ {delay_ms}ms: {e!r}")

def _compensated_move(win, target_xy: Tuple[int, int], *, after_scroll_restore=None) -> None:
    """
    Dvoustupňové až vícestupňové 'dorovnání' pozice okna – tlumí chvění/offset,
    které dělá WM/Qt těsně po vytvoření. Bezpečné i když nic nepohne.
    """
    tx, ty = int(target_xy[0]), int(target_xy[1])

    def attempt(stage: str):
        loc = get_window_location(win)
        _dbg(f"[GUI-HELPERS] move[{stage}]: current={loc}, target={(tx,ty)}")
        if not loc:
            return
        dx, dy = loc[0] - tx, loc[1] - ty
        if dx == 0 and dy == 0:
            _dbg(f"[GUI-HELPERS] move[{stage}]: already at target")
            return
        try:
            win.move(tx - dx, ty - dy)
            _dbg(f"[GUI-HELPERS] move[{stage}]: applying (-dx,-dy)=({-dx},{-dy}) -> move({tx-dx},{ty-dy})")
        except Exception as e:
            _dbg(f"[GUI-HELPERS] move[{stage}]: move failed: {e!r}")

    attempt("t0")
    _schedule(15, lambda: attempt("t+15ms"))
    _schedule(35, lambda: attempt("t+35ms"))
    _schedule(75, lambda: (attempt("t+75ms"), after_scroll_restore and after_scroll_restore()))

# ---- veřejné API ----
# builder: funkce, která VIŽDY vytvoří nové okno na zadané lokaci a vrátí (window, *any_state)
#          signatura: builder(location: Optional[Tuple[int,int]]) -> tuple
def recreate_window_preserving(
    old_win,
    builder: Callable[[Optional[Tuple[int,int]]], tuple],
    *,
    col_key: str = "-COL-",
    target_loc: Optional[Tuple[int,int]] = None,
) -> tuple:
    """
    Zavře staré okno, postaví nové stejné okno (pomocí builderu) a
    dorovná jeho pozici (až ve 3–4 krocích), potom obnoví scroll Columnu.

    Vrací: (new_window, *rest_builder_values)
    """
    old_loc = target_loc if target_loc else get_window_location(old_win)
    old_scroll = None
    try:
        old_scroll = get_column_scroll(old_win, col_key)
    except Exception:
        pass

    _dbg(f"[GUI-HELPERS] recreate: old_loc={old_loc}, old_scroll={old_scroll}")

    try:
        _dbg("[GUI-HELPERS] recreate: closing old window…")
        old_win.close()
    except Exception as e:
        _dbg(f"[GUI-HELPERS] recreate: close exception: {e!r}")

    # Builder MUSÍ akceptovat 'location' a postavit nové okno.
    new_tuple = builder(old_loc)
    if not new_tuple:
        _dbg("[GUI-HELPERS] recreate: builder returned empty/None")
        return (None,)

    new_win = new_tuple[0]
    if new_win is None:
        _dbg("[GUI-HELPERS] recreate: builder window is None")
        return (None,)

    _dbg(f"[GUI-HELPERS] recreate: new window created at {get_window_location(new_win)}")

    # po dorovnání pozice obnovíme scroll
    def _restore_scroll():
        try:
            set_column_scroll(new_win, col_key, old_scroll)
            _dbg(f"[GUI-HELPERS] restore scroll -> {old_scroll}")
        except Exception as e:
            _dbg(f"[GUI-HELPERS] restore scroll failed: {e!r}")

    if old_loc:
        try:
            # první rychlý move + doladění ve vteřinových krocích
            new_win.move(int(old_loc[0]), int(old_loc[1]))
        except Exception:
            pass
        _compensated_move(new_win, (int(old_loc[0]), int(old_loc[1])), after_scroll_restore=_restore_scroll)
    else:
        _restore_scroll()

    return new_tuple
