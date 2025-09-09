# gui/smoke_plan_window.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from datetime import date, timedelta
from typing import Dict, List, Tuple, Optional
from math import floor
from services import graph_store
from services.semi_excel_service import ensure_output_semis_excel
from services.smoke_sync_service import apply_plan_flags
from services.smoke_engine import build_default_engine
from services.smoke_rules import RuleViolation


import PySimpleGUIQt as sg
import pandas as pd

# ==== NOVÉ IMPORTY PRO EXCEL SERVICE ====
from services.smoke_excel_service import write_smoke_plan_excel
from services.smoke_paths import smoke_plan_excel_path


RULES_ENGINE = build_default_engine(
    base_per_smoker=[400.0, 300.0, 400.0, 400.0],   # default limity (kg syrového) pro udírny 1..4
    per_type_overrides={
        # příklady:
        # "veprove": [420, 320, 420, 420],
        # "hovezi":  [300, 250, 300, 300],
    },
)

# ====== Globální škálování ======
SCALE_X = 0.37   # užší šířky (ponecháno)
SCALE_Y = 0.40   # agresivní stažení svislých rozestupů

# helper – škáluje jen svislou složku padu
def VPad(p: Tuple[int,int]) -> Tuple[int,int]:
    h, v = p
    return (h, int(round(v * SCALE_Y)))

# ====== Konfigurace ======
SMOKERS = 4
ROWS_PER_SMOKER = 7
DAYS = 6  # Po–So
DAY_LABELS = ["Po", "Út", "St", "Čt", "Pá", "So"]

# Vzhled / kompaktnost
BG = "#ffffff"
SLOT_PICK_BG   = "#fff7cc"   # vybraný (drag)
SLOT_FILLED_BG = "#eef8e9"   # obsazený
HDR_COLORS = ["#FFF2A8", "#D1F5D3", "#D1E6FF", "#FFE6CC"]  # 1..4
SLOT_OVER_BG = "#FFD6D6"  

# agresivně malé pady
PAD_ELEM = (0, 0)
PAD_CELL = (0, 0)
BTN_PAD  = ((4, 0), (0, 0))  # sjednoceno se zbytkem projektu

# Vzhled / kompaktnost
FONT_BASE   = ("Any", 8)
FONT_LABEL  = ("Any", 7)
FONT_HDR    = ("Any", 9, "bold")
FONT_TITLE  = ("Any", 12, "bold")


# ====== Datové typy ======
@dataclass
class Item:
    rc: str
    sk: str
    name: str
    qty: float
    unit: str
    source_id: str

CellKey = Tuple[int, int, int]  # (day_idx, smoker_idx, row_idx)

# ====== Utility ======

def _confirm_rule(msg: str) -> bool:
    try:
        return sg.popup_yes_no(msg, title="Potvrzení") == "Yes"
    except Exception:
        return False

def _next_week_monday(today: Optional[date] = None) -> date:
    d = today or date.today()
    offs = (7 - d.weekday()) % 7
    offs = 7 if offs == 0 else offs
    return d + timedelta(days=offs)

def _tighten_layout(elem: sg.Element, *, hgap: int = 0, vgap: int = 0,
                    margins: Tuple[int,int,int,int] = (0,0,0,0)) -> None:
    """Nastaví spacing/margins přímo na Qt layoutu daného Columnu."""
    try:
        lay = elem.Widget.layout()
        lay.setHorizontalSpacing(hgap)
        lay.setVerticalSpacing(vgap)
        l, t, r, b = margins
        lay.setContentsMargins(l, t, r, b)
    except Exception:
        pass


def _items_df_from_items(items: List[Item]) -> pd.DataFrame:
    """DF všech vybraných polotovarů – tak, jak je čeká semi_excel_service/apply_plan_flags."""
    if not items:
        return pd.DataFrame(columns=[
            "polotovar_sk","polotovar_rc","polotovar_nazev","mnozstvi","jednotka"
        ])
    recs = []
    for it in items:
        recs.append(dict(
            polotovar_sk = it.sk,
            polotovar_rc = it.rc,
            polotovar_nazev = it.name,
            mnozstvi = it.qty,
            jednotka = it.unit,
        ))
    return pd.DataFrame(recs)

def _plan_df_for_sync(grid: Dict[CellKey, List[Item]], week_monday: date) -> pd.DataFrame:
    """
    Jeden řádek na KAŽDÝ naplánovaný polotovar (tj. každý Item v gridu),
    s klíči + datem, aby šlo nastavit planned_for_smoking a smoking_date.
    """
    rows = []
    for (d, _s, _r), items in grid.items():
        day_date = week_monday + timedelta(days=d)
        for it in items:
            rows.append(dict(
                datum = day_date,                 # důležité pro smoking_date
                polotovar_sk = it.sk,
                polotovar_rc = it.rc,
                polotovar_nazev = it.name,
                mnozstvi = it.qty,
                jednotka = it.unit,
            ))
    return pd.DataFrame(rows)



def _coerce_item(row: dict) -> Item:
    return Item(
        rc=str(row.get("polotovar_rc") or row.get("rc") or ""),
        sk=str(row.get("polotovar_sk") or row.get("sk") or ""),
        name=str(row.get("polotovar_nazev") or row.get("name") or row.get("nazev") or ""),
        qty=float(str(row.get("potreba") or row.get("qty") or row.get("mnozstvi") or 0).replace(",", ".") or 0),
        unit=str(row.get("jednotka") or row.get("unit") or row.get("mj") or ""),
        source_id=str(row.get("source_id") or row.get("id") or row.get("row_id") or row.get("guid") or ""),
    )

def _prefill_with_rules(items: List[Item]) -> Dict[CellKey, List[Item]]:
    return RULES_ENGINE.prefill(items, DAYS, SMOKERS, ROWS_PER_SMOKER, confirm_cb=_confirm_rule)


def _fmt_qty2_cz(v: float) -> str:
    try: return f"{float(v):.2f}".replace(".", ",")
    except Exception: return str(v)

def _cell_text(items: List[Item], name_chars: int) -> str:
    if not items: return "—"
    first, extra = items[0].name, len(items) - 1
    suffix = f" (+{extra})" if extra > 0 else ""
    return first[:max(8, name_chars)] + suffix

def _slot_rc_and_qty(items: List[Item]) -> Tuple[str, str]:
    if not items: return "", ""
    rcs = ",".join(sorted({it.rc for it in items if it.rc}))
    qty_sum = sum((it.qty or 0) for it in items)
    return rcs, _fmt_qty2_cz(qty_sum)

def _popup_ok_safe(message: str, title: str) -> None:
    try: sg.popup_ok(message, title=title, keep_on_top=True, image=None)
    except Exception:
        try: sg.popup(message, title=title, keep_on_top=True)
        except Exception: pass

def _px_per_char() -> int:
    try:
        from PySide6 import QtWidgets, QtGui
        app = QtWidgets.QApplication.instance()
        fm = QtGui.QFontMetrics(app.font())
        w = fm.horizontalAdvance("0123456789") / 10.0
        return max(6, int(round(w)))
    except Exception:
        return 8

# ====== Update slotů ======
def _update_cell_widgets(window: sg.Window, d: int, s: int, r: int, items: List[Item], name_chars: int) -> None:
    try: window[("CELL_TEXT", d, s, r)].update(_cell_text(items, name_chars))
    except Exception: pass
    rc_str, qty_str = _slot_rc_and_qty(items)
    try: window[("RC_TXT", d, s, r)].update(rc_str)
    except Exception: pass
    try: window[("QTY_TXT", d, s, r)].update(qty_str)
    except Exception: pass

def _update_all_cells(window: sg.Window, grid: Dict[CellKey, List[Item]], name_chars: int) -> None:
    for (d, s, r), items in grid.items():
        if ("CELL_TEXT", d, s, r) in window.AllKeysDict:
            _update_cell_widgets(window, d, s, r, items, name_chars)
        _paint_slot_bg(window, d, s, r, items, False)

# ====== Kurzory (PySide6) ======
def _set_grab_cursors(window: sg.Window, dragging: bool) -> None:
    try:
        from PySide6 import QtWidgets, QtCore, QtGui
        app = QtWidgets.QApplication.instance()
        if app is None: return
        shape = QtCore.Qt.CursorShape.SizeAllCursor if dragging else QtCore.Qt.CursorShape.PointingHandCursor
        qcursor = QtGui.QCursor(shape)
        def _apply_cursor(widget):
            try: widget.setCursor(qcursor)
            except Exception: pass
            try:
                for child in widget.findChildren(QtWidgets.QWidget):
                    try: child.setCursor(qcursor)
                    except Exception: pass
            except Exception: pass
        for k, elem in window.AllKeysDict.items():
            if isinstance(k, tuple) and k and k[0] in ("SLOT", "GRAB"):
                w = getattr(elem, "Widget", None)
                if w is not None: _apply_cursor(w)
    except Exception: pass

# ====== Drag vizuál ======
BTN_NORMAL    = ("⠿", ("black", "#eaeaea"))
BTN_DISABLED  = ("",   ("#999999", "#f3f3f3"))
BTN_SRC_PICK  = ("✖",  ("white", "#d9534f"))
BTN_DST_SWAP  = ("⇄",  ("white", "#0275d8"))
BTN_DST_MOVE  = ("⬇",  ("white", "#5cb85c"))

def _is_slot_draggable(grid: Dict[CellKey, List[Item]], d: int, s: int, r: int) -> bool:
    return bool(grid.get((d, s, r), []))

def _set_handle(window: sg.Window, d: int, s: int, r: int, *, text: str, color: Tuple[str,str], disabled: bool) -> None:
    key = ("GRAB", d, s, r)
    if key in window.AllKeysDict:
        try: window[key].update(text=text, button_color=color, disabled=disabled)
        except Exception:
            try: window[key].update(text=text, disabled=disabled)
            except Exception: pass

def _refresh_handles(window: sg.Window, grid: Dict[CellKey, List[Item]], dragging: Optional[CellKey]) -> None:
    for d in range(DAYS):
        for s in range(1, SMOKERS+1):
            for r in range(1, ROWS_PER_SMOKER+1):
                draggable = _is_slot_draggable(grid, d, s, r)
                if dragging is None:
                    _set_handle(window, d, s, r,
                                text=BTN_NORMAL[0] if draggable else BTN_DISABLED[0],
                                color=BTN_NORMAL[1] if draggable else BTN_DISABLED[1],
                                disabled=not draggable)
                else:
                    if dragging == (d, s, r):
                        _set_handle(window, d, s, r, text=BTN_SRC_PICK[0], color=BTN_SRC_PICK[1], disabled=False)
                    else:
                        _set_handle(window, d, s, r,
                                    text=BTN_DST_SWAP[0] if draggable else BTN_DST_MOVE[0],
                                    color=BTN_DST_SWAP[1] if draggable else BTN_DST_MOVE[1],
                                    disabled=False)

# ====== Slot background ======
def _paint_slot_bg(window: sg.Window, d: int, s: int, r: int, items: List[Item], picked: bool) -> None:
    key_slot = ("SLOT", d, s, r)
    try:
        elem = window[key_slot]; w = elem.Widget
        if picked:
            col = SLOT_PICK_BG
        elif items:
            info = RULES_ENGINE.paint_info(s, items)  # s = smoker index (1-based)
            col = SLOT_OVER_BG if info.get("over") else SLOT_FILLED_BG
        else:
            col = BG
        w.setStyleSheet(f"background-color: {col}; border-radius: 2px;")
    except Exception:
        pass

def _refresh_slot_bgs(window: sg.Window, grid: Dict[CellKey, List[Item]], dragging: Optional[CellKey]) -> None:
    for (d, s, r), items in grid.items():
        _paint_slot_bg(window, d, s, r, bool(items), dragging == (d, s, r))

def _swap_dose_inputs(window: sg.Window, src: CellKey, dst: CellKey) -> None:
    ksrc = ("DOSE",) + src; kdst = ("DOSE",) + dst
    try:
        v_src = window[ksrc].get() if ksrc in window.AllKeysDict else ""
        v_dst = window[kdst].get() if kdst in window.AllKeysDict else ""
        if ksrc in window.AllKeysDict: window[ksrc].update(v_dst)
        if kdst in window.AllKeysDict: window[kdst].update(v_src)
    except Exception: pass

def _move_or_swap(window: sg.Window, grid: Dict[CellKey, List[Item]], src: CellKey, dst: CellKey) -> None:
    if src == dst or src not in grid or dst not in grid:
        return
    ok, viol = RULES_ENGINE.try_move(grid, src, dst, confirm_cb=_confirm_rule, allow_split_on_move=True)
    if not ok:
        msg = "Přesun není povolen."
        if isinstance(viol, RuleViolation):
            # Jasná hláška s názvem a ID pravidla
            msg = f"{viol.title} [{viol.rule_id}]\n\n{viol.message}"
        _popup_ok_safe(msg, "Pravidla plánování")
        return

    # refresh obou slotů
    _update_cell_widgets(window, src[0], src[1], src[2], grid[src], NAME_WIDTH_CHARS)
    _update_cell_widgets(window, dst[0], dst[1], dst[2], grid[dst], NAME_WIDTH_CHARS)
    _paint_slot_bg(window, src[0], src[1], src[2], grid[src], False)
    _paint_slot_bg(window, dst[0], dst[1], dst[2], grid[dst], False)


# ====== (POUZE TADY ZMĚNA) Převod do DF pro NOVÝ Excel service ======
def _flatten_for_excel_from_ui(grid: Dict[CellKey, List[Item]], week_monday: date, values: dict) -> pd.DataFrame:
    """
    Připraví DataFrame očekávaný write_smoke_plan_excel:
      datum, udirna, pozice, polotovar_nazev, mnozstvi, jednotka, davka, shift, poznamka

    - Vytváří 1 řádek pro KAŽDÝ slot (i když je prázdný), aby šlo uložit "jen Dávku".
    - 'poznamka' a 'shift' necháváme vždy prázdné (nový export je stejně ignoruje).
    """
    rows = []
    for d in range(DAYS):
        for s in range(1, SMOKERS + 1):
            for r in range(1, ROWS_PER_SMOKER + 1):
                items = grid.get((d, s, r), [])
                # název může být prázdný; když něco je, použijeme první název
                name = items[0].name if items else ""
                rc_first = items[0].rc if items else ""
                # součet množství jen jako informativní podklad (může zůstat NaN)
                qty_sum = sum((it.qty or 0) for it in items) if items else None
                unit = items[0].unit if (items and items[0].unit) else ""
                dose_val = str(values.get(("DOSE", d, s, r), "")).strip()

                rows.append({
                    "datum": (week_monday + timedelta(days=d)),  # date pro Po–So
                    "udirna": s,
                    "pozice": r,
                    "rc": rc_first,   
                    "polotovar_nazev": name,     # může zůstat prázdné
                    "mnozstvi": qty_sum,         # může být None/NaN
                    "jednotka": unit or "",      # může být prázdné
                    "davka": dose_val,           # může být jediné vyplněné pole
                    "shift": "",                 # vždy prázdné
                    "poznamka": "",              # vždy prázdné
                })
    df = pd.DataFrame(rows)
    # korektní typy
    df["datum"] = pd.to_datetime(df["datum"]).dt.date
    df["udirna"] = pd.to_numeric(df["udirna"], errors="coerce").astype("Int64")
    df["pozice"] = pd.to_numeric(df["pozice"], errors="coerce").astype("Int64")
    df["mnozstvi"] = pd.to_numeric(df["mnozstvi"], errors="coerce")
    return df

# ====== Metriky ======
def _slot_metrics(block_px: int, px_char: int) -> Dict[str, int]:
    A_px_base = 10
    margin_base = 2
    COL_MIN_CH_base  = 5
    NAME_MIN_CH_base = 14

    A_px   = max(5, int(round(A_px_base * SCALE_X)))
    margin = max(1, int(round(margin_base * SCALE_X)))

    COL_MIN_CH  = max(3, int(round(COL_MIN_CH_base * SCALE_X)))
    NAME_MIN_CH = max(8, int(round(NAME_MIN_CH_base * SCALE_X)))

    W_MIN = max(NAME_MIN_CH * px_char, 3 * COL_MIN_CH * px_char + 2 * margin)
    W_px  = max(W_MIN, block_px - (A_px + margin))
    W_ch  = max(NAME_MIN_CH, W_px // px_char)

    col_px = (W_px - 2 * margin) // 3
    COL_CH = max(COL_MIN_CH, col_px // px_char)

    return dict(
        A_px=A_px, W_px=W_px, margin=margin,
        A_ch=max(2, A_px // px_char),
        W_ch=W_ch,
        NAME_LINES=1,
        COL_CH=COL_CH
    )

# ====== UI KOMPOZITY ======
def _mini_labeled_input(label: str, key, size_ch: int, *, disabled=False, justify=None) -> sg.Column:
    return sg.Column(
        [
            [sg.Text(label, font=FONT_LABEL, background_color=BG, pad=PAD_ELEM)],
            [sg.Input(key=key, size=(size_ch, 1), pad=PAD_ELEM, disabled=disabled,
                      justification=justify or "left", font=FONT_BASE)],
        ],
        background_color=BG, pad=PAD_ELEM
    )

def _make_slot_widget(grid: Dict[CellKey, List[Item]], d: int, s: int, r: int,
                      m: Dict[str,int]) -> sg.Column:
    items_here = grid[(d, s, r)]

    key_slot = ("SLOT", d, s, r)
    key_name = ("CELL_TEXT", d, s, r)
    key_regc = ("RC_TXT",    d, s, r)
    key_qty  = ("QTY_TXT",   d, s, r)
    key_dose = ("DOSE",      d, s, r)
    key_grab = ("GRAB",      d, s, r)

    # Levý sloupec: číslo + úchyt NA JEDNOM ŘÁDKU (ať nezvyšuje výšku slotu)
    colA = sg.Column([[
        sg.Text(f"{r}.", size=(max(2, m["A_ch"]), 1), pad=PAD_ELEM, background_color=BG, font=FONT_LABEL),
        sg.Button("⠿", key=key_grab, size=(2, 1), pad=PAD_ELEM,
                  button_color=("black", "#eaeaea"), font=FONT_BASE),
    ]], size=(m["A_px"], None), pad=(0, 0), background_color=BG)

    # Pravá část: 2 velmi nízké vrstvy (label nad polem)
    layer1 = sg.Column([
        [sg.Text("Druh výrobku", font=FONT_LABEL, background_color=BG, pad=PAD_ELEM)],
        [sg.Input(_cell_text(items_here, m["W_ch"]), key=key_name,
                  size=(m["W_ch"], 1), disabled=True, pad=PAD_ELEM, font=FONT_BASE)],
    ], background_color=BG, pad=(0, 0), size=(m["W_px"], None))

    col_reg  = _mini_labeled_input("Reg.č.",    key_regc, m["COL_CH"], disabled=True)
    col_qty  = _mini_labeled_input("Množství",  key_qty,  m["COL_CH"], disabled=True, justify="right")
    col_dose = _mini_labeled_input("Dávka",     key_dose, m["COL_CH"])
    layer2 = sg.Column([[col_reg, col_qty, col_dose]], background_color=BG, pad=(0, 0), size=(m["W_px"], None))

    right_col = sg.Column([[layer1], [layer2]], pad=(0, 0), background_color=BG, size=(m["W_px"], None),key=("RIGHT", d, s, r))

    slot_col = sg.Column([[colA, right_col]], key=key_slot, pad=PAD_CELL, background_color=BG)
    try:
        slot_col.Widget.setStyleSheet(f"background-color: {SLOT_FILLED_BG if items_here else BG}; border-radius: 2px;")
    except Exception: pass
    return slot_col

def _make_smoker_block(grid: Dict[CellKey, List[Item]], d: int, s: int,
                       block_px: int, px_char: int) -> sg.Column:
    m = _slot_metrics(block_px, px_char)
    header_bar = sg.Text(
        f"Udírna číslo {s}",
        justification="center",
        background_color=HDR_COLORS[(s - 1) % len(HDR_COLORS)],
        text_color="black",
        pad=PAD_ELEM,
        size=(int((block_px-6)/8), 1),
        font=FONT_HDR,
    )
    slots = [[_make_slot_widget(grid, d, s, r, m)] for r in range(1, ROWS_PER_SMOKER + 1)]
    return sg.Column([[header_bar], *slots], background_color=BG, pad=PAD_CELL, size=(block_px, None), key=("SMB", d, s))

# ====== Stylování tabů ======
def _apply_tabbar_style(window: sg.Window) -> None:
    try:
        qtab = window["-TABGROUP-"].Widget
        qbar = qtab.tabBar() if qtab is not None else None
        if qbar is None: return
        vpad = max(1, int(round(2 * SCALE_Y)))  # ještě menší
        qbar.setStyleSheet(f"""
            QTabBar::tab {{
                background: #F5F5F5;
                border: 1px solid #D1D1D1;
                padding: {vpad}px 6px;
                margin: 1px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 10px;
            }}
            QTabBar::tab:hover {{ background: #FFF1C6; }}
            QTabBar::tab:selected {{ background: #FFE8A3; font-weight: 600; }}
        """)
    except Exception: pass

# ====== Potlačení horizontálního scrollu ======
def _disable_horizontal_scrollbars(window: sg.Window) -> None:
    try:
        from PySide6 import QtCore
    except Exception:
        return
    for d in range(DAYS):
        key = ("DAYSCROLL", d)
        if key not in window.AllKeysDict: continue
        try:
            elem = window[key]; w = getattr(elem, "Widget", None)
            if w is not None: w.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        except Exception: pass

# ====== Hlavní okno ======
def open_smoke_plan_window(selected_df: pd.DataFrame) -> None:
    """
    Extrémně kompaktní vertikální layout:
      • globálně element_padding=(0,0)
      • malé fonty
      • číslo a úchyt na jednom řádku vlevo
      • minimální pady mezi sloty
    """
    items: List[Item] = [_coerce_item(rec) for rec in selected_df.to_dict("records")]
    week_monday = _next_week_monday()
    grid: Dict[CellKey, List[Item]] = _prefill_with_rules(items)

    # Globální odebrání implicitních rozestupů
    sg.set_options(element_padding=(0, 0))

    sg.theme("SystemDefault")

    try: scr_w, scr_h = sg.Window.get_screen_size()
    except Exception: scr_w, scr_h = (1600, 900)

    px_char = _px_per_char()

    # Šířky
    SAFETY = 220
    GAP_BASE = 4
    GAP_PX = max(1, int(round(GAP_BASE * SCALE_X)))
    work_w = max(1000, scr_w - SAFETY)

    gap_total_full = GAP_BASE * (SMOKERS - 1)
    block_px_full = floor((work_w - gap_total_full) / SMOKERS)
    block_px = max(80, int(round(block_px_full * SCALE_X)))

    gap_total = GAP_PX * (SMOKERS - 1)
    container_w = ((block_px * SMOKERS) + gap_total) * 3  # zachováno

    # ----- Hlavicka bez tlačítek (sjednocení se zbytkem projektu) -----
    header = [
        [sg.Text("Plán uzení (Po–So)", font=FONT_TITLE, background_color=BG, pad=PAD_ELEM)],
        [sg.Text(f"Týden od (pondělí): {week_monday:%d.%m.%Y}", background_color=BG, font=FONT_BASE, pad=PAD_ELEM)],
    ]

    def _make_day_tab_content(d: int) -> List[List[sg.Element]]:
        blocks = [_make_smoker_block(grid, d, s, block_px, px_char) for s in range(1, SMOKERS + 1)]
        viewport_h = max(240, int(scr_h * 0.70))
        # bez spacerů, jen 4 Columns vedle sebe:
        day_row = sg.Column([[blocks[0], blocks[1], blocks[2], blocks[3]]],
                            background_color=BG, pad=(0, 0), key=("DAYROW", d))
        day_column = sg.Column(
            [[day_row]],
            background_color=BG,
            pad=(0, 0),
            scrollable=True,
            size=(container_w, viewport_h),
            key=("DAYSCROLL", d),
        )
        return [[day_column]]

    day_tabs: List[sg.Tab] = []
    for d in range(DAYS):
        d_date = week_monday + timedelta(days=d)
        day_label = f"{DAY_LABELS[d]} {d_date:%d.%m.}"
        day_tabs.append(sg.Tab(day_label, _make_day_tab_content(d), key=("TAB", d), background_color=BG, pad=PAD_ELEM))

    tabs = sg.TabGroup([day_tabs], key="-TABGROUP-", background_color=BG, pad=PAD_ELEM, enable_events=False)

    # ----- Kontrolní lišta dole (tlačítka) -----
    controls = [
        sg.Button("Uložit", key="SAVE", size=(14, 1), pad=BTN_PAD),
        sg.Button("Zavřít", key="-CLOSE-", size=(14, 1), pad=((12, 0), 0)),
    ]
    controls_col = sg.Column([controls], element_justification='center', pad=(0, 6), background_color=BG)

    layout = [*header, [tabs], [controls_col]]

    window = sg.Window(
        "Plán uzení (Po–So)",
        layout,
        finalize=True,
        resizable=True,
        background_color=BG,
        use_default_focus=False,
        margins=(6, 4),
    )

    _apply_tabbar_style(window)
    _disable_horizontal_scrollbars(window)

    try:
        window.Maximize()
    except Exception:
        try: window.maximize()
        except Exception: pass

        
    # a) vodorovná mezera mezi 4 udírnami – čistě přes layout spacing
    for d in range(DAYS):
        if ("DAYROW", d) in window.AllKeysDict:
            _tighten_layout(window[("DAYROW", d)], hgap=0, vgap=0, margins=(0,0,0,0))

    # b) svislá mezera mezi jednotlivými sloty v bloku udírny
    for d in range(DAYS):
        for s in range(1, SMOKERS+1):
            k_block = ("SMB", d, s)
            if k_block in window.AllKeysDict:
                _tighten_layout(window[k_block], hgap=0, vgap=0, margins=(0,0,0,0))  # skoro nalepené

            # c) svislá mezera uvnitř slotu mezi „název“ a „Regč|Množ|Dávka“
            for r in range(1, ROWS_PER_SMOKER+1):
                k_right = ("RIGHT", d, s, r)
                if k_right in window.AllKeysDict:
                    _tighten_layout(window[k_right], hgap=0, vgap=0, margins=(0,0,0,0))

    m0 = _slot_metrics(block_px, px_char)
    _update_all_cells(window, grid, m0["W_ch"])
    _set_grab_cursors(window, dragging=False)
    _refresh_handles(window, grid, dragging=None)
    _refresh_slot_bgs(window, grid, dragging=None)

    dragging: Optional[CellKey] = None
    picked_slot_key: Optional[Tuple[str,int,int,int]] = None

    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, "-CLOSE-", "CLOSE"): break

        if isinstance(event, tuple) and event and event[0] == "GRAB":
            _d, _s, _r = event[1], event[2], event[3]
            cur = (_d, _s, _r); slot_key = ("SLOT", _d, _s, _r)
            if dragging is None:
                if not _is_slot_draggable(grid, _d, _s, _r): continue
                dragging = cur; picked_slot_key = slot_key
                _paint_slot_bg(window, _d, _s, _r, True, True)
                _set_grab_cursors(window, dragging=True)
                _refresh_handles(window, grid, dragging)
            else:
                if picked_slot_key:
                    _paint_slot_bg(window,
                                   picked_slot_key[1], picked_slot_key[2], picked_slot_key[3],
                                   bool(grid.get((picked_slot_key[1], picked_slot_key[2], picked_slot_key[3]), [])),
                                   False)
                if cur != dragging:
                    _move_or_swap(window, grid, dragging, cur)
                    _update_all_cells(window, grid, _slot_metrics(block_px, _px_per_char())["W_ch"])
                dragging = None; picked_slot_key = None
                _set_grab_cursors(window, dragging=False)
                _refresh_handles(window, grid, dragging=None)
                _refresh_slot_bgs(window, grid, dragging=None)
            continue

        if event == "SAVE":
            # === ULOŽIT PLÁN DO EXCEL ŠABLONY ===
            plan_df = _flatten_for_excel_from_ui(grid, week_monday, values)
            out = smoke_plan_excel_path(week_monday)

            try:
                write_smoke_plan_excel(
                    str(out),
                    plan_df,
                    week_monday=week_monday,   # pro správné nadpisy dnů
                    sheet_name=None,           # použije se 1. list ze šablony
                )
            except Exception as e:
                _popup_ok_safe(f"Chyba při ukládání:\n{e}", "Chyba")
                continue

            # === PO ULOŽENÍ: OZNAČ VŠECHNY PŮVODNĚ VYBRANÉ POLOTOVARY JAKO VYROBENÉ ===
            try:
                from services import graph_store  # lokální import, ať není nutná změna nahoře

                # použij původní výběr předaný do okna (správné datum!)
                src = selected_df.copy()

                # sjednoť typ datumu na date (bez času), aby se přesně trefil klíč (datum, sk, rc)
                if "datum" in src.columns:
                    src["datum"] = pd.to_datetime(src["datum"], errors="coerce").dt.date

                need_cols = ["datum", "polotovar_sk", "polotovar_rc"]
                missing = [c for c in need_cols if c not in src.columns]
                if missing:
                    raise KeyError(f"Chybí sloupce: {missing}")

                # vyhoď NaN a prázdné SK/RC, odstraň duplicity
                sub = src[need_cols].dropna().copy()
                sub = sub[
                    (sub["polotovar_sk"].astype(str).str.strip() != "") &
                    (sub["polotovar_rc"].astype(str).str.strip() != "")
                ].drop_duplicates()

                # klíče pro hromadné označení
                keys = {(r["datum"], r["polotovar_sk"], r["polotovar_rc"]) for _, r in sub.iterrows()}

                if keys:
                    graph_store.set_semis_produced_many(keys, produced=True)

                _popup_ok_safe(
                    f"Uloženo do:\n{out}\n\n"
                    f"Označeno {len(keys)} polotovarů jako vyrobené.",
                    "Uloženo"
                )
            except Exception as e:
                _popup_ok_safe(f"Plán se uložil, ale označení vyrobeno selhalo:\n{e}", "Upozornění")


    try: window.close()
    except Exception: pass
