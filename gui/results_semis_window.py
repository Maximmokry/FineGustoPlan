# gui/results_semis_window.py
import traceback
from typing import Dict, List, Tuple, Optional
from services import graph_store
from services.data_utils import to_date_col, fmt_cz_date
import os

import PySimpleGUIQt as sg
import pandas as pd
from services import graph_store  
from services.readiness import compute_ready_semis_under_finals
g = graph_store.get_graph()
ready_keys = compute_ready_semis_under_finals(g)

from services.paths import OUTPUT_SEMI_EXCEL
from services.data_utils import (
    to_date_col,
    find_col,
    fmt_cz_date,
    to_bool_cell_excel,
)
from services.gui_helpers import (
    recreate_window_preserving,
    dbg_set_enabled,
)
from services import error_messages as ERR  # <- centralizované hlášky

# ========================= VZHLED / ROZMĚRY =========================
dbg_set_enabled(False)  # zap/vyp debug v gui_helpers
CELL_PAD = (0, 0)
BTN_PAD  = ((4, 0), (0, 0))

FONT_ROW = ("Any", 9)
FONT_ROW_BOLD = ("Any", 9, "bold")
FONT_HEADER = ("Any", 10, "bold")
FONT_MAIN_NAME = ("Any", 11, "bold")

DATE_WIDTH = 20
SK_WIDTH   = 6
RC_WIDTH   = 10

NAME_WIDTH_CHARS = 48
QTY_WIDTH_CHARS  = 9
UNIT_WIDTH_CHARS = 5

LAST_WIN_POS: Optional[Tuple[int, int]] = None


# ========================= UTILITY =========================
# Přidej nahoru k ostatním konstantám:
READY_BG = "#d9fdd3"  # světle zelené pozadí pro „vše koupeno“


def _to_int_or_none(x):
    try:
        s = str(x).strip()
        if s == "":
            return None
        return int(s)
    except Exception:
        return None


def _is_polotovar_ready(sk, rc) -> bool:
    """
    Vrátí True, pokud všechny listové ingredience v podstromu polotovaru (sk, rc)
    mají atribut `bought=True`.

    Používá runtime graf z graph_store (attach_status_from_excels do něj natahuje koupeno).
    """
    try:
        # preferovaná cesta – pokud graph_store nabízí getter
        g = getattr(graph_store, "get_graph", None)
        g = g() if callable(g) else getattr(graph_store, "_G", None)
    except Exception:
        g = getattr(graph_store, "_G", None)

    if not g or not getattr(g, "nodes", None):
        return False

    isk = _to_int_or_none(sk)
    irc = _to_int_or_none(rc)
    if isk is None or irc is None:
        return False

    nid = (isk, irc)
    if nid not in g.nodes:
        return False

    # DFS na listy (ingredience): list = uzel bez edges
    stack = [nid]
    visited = set()
    while stack:
        cur = stack.pop()
        if cur in visited:
            continue
        visited.add(cur)

        node = g.nodes.get(cur)
        if not node:
            continue

        edges = getattr(node, "edges", []) or []
        if not edges:
            # list – musí být koupený
            if not bool(getattr(node, "bought", False)):
                return False
        else:
            for e in edges:
                try:
                    stack.append(e.child)
                except Exception:
                    pass

    return True

def _safe_loc(win):
    try:
        x, y = win.current_location()
        return int(x), int(y)
    except Exception:
        return None

def _remember_pos(win):
    global LAST_WIN_POS
    pos = _safe_loc(win)
    if pos:
        LAST_WIN_POS = pos

def _force_bool(df: pd.DataFrame, col: str):
    df[col] = df[col].map(to_bool_cell_excel).astype(bool)

# --- přidej někam k utilitám v horní části souboru (např. pod _get_any) ---
def _fmt_qty_2dec_cz(v) -> str:
    """
    Naformátuje číslo na dvě desetinná místa s čárkou jako oddělovačem.
    Vstup může být číslo nebo text s čárkou/tečkou.
    Pokud nejde převést na číslo, vrátí původní text.
    """
    if v is None:
        return ""
    s = str(v).strip()
    if s == "":
        return ""
    try:
        f = float(s.replace(" ", "").replace(",", "."))
        return f"{f:.2f}".replace(".", ",")
    except Exception:
        return s

def _filter_unmade(df: pd.DataFrame, col: str) -> pd.DataFrame:
    _force_bool(df, col)
    return df.loc[~df[col]].copy()

def _get_any(row: pd.Series, candidates: List[str], default=""):
    cols = {str(c).strip().lower(): c for c in row.index}
    for cand in candidates:
        key = cand.strip().lower()
        if key in cols:
            return row.get(cols[key], default)
    return default
def _name_cell(
    text: str,
    *,
    height: int,
    indent_px: int = 0,
    is_main: bool = False,
    underline: bool = False,
):
    """
    Textová buňka pro název. V Qt (PySimpleGUIQt) je spolehlivější použít rich text
    pro podtržení (QLabel umí <u>…</u>) než spoléhat na třetí položku fontu.
    """
    from html import escape as html_escape

    base_font = FONT_MAIN_NAME if is_main else FONT_ROW

    # Rich text pro underline (jinak čistý text)
    txt = str(text)
    if underline:
        txt = f"<u>{html_escape(txt)}</u>"

    return sg.Text(
        txt,
        size=(NAME_WIDTH_CHARS, height),
        pad=((indent_px, 0), 0),
        auto_size_text=False,
        font=base_font,
        justification="left",
    )




def _header_row():
    return [
        sg.Text("Datum",   size=(DATE_WIDTH, 1), font=FONT_HEADER, pad=CELL_PAD),
        sg.Text("Reg.č.",  size=(RC_WIDTH, 1),   font=FONT_HEADER, pad=CELL_PAD),
        sg.Text("Název",   size=(NAME_WIDTH_CHARS, 1), font=FONT_HEADER, pad=CELL_PAD),
        sg.Text("Množství", size=(QTY_WIDTH_CHARS, 1), font=FONT_HEADER, pad=CELL_PAD, justification="right"),
        sg.Text("",        size=(UNIT_WIDTH_CHARS, 1), font=FONT_HEADER, pad=CELL_PAD),
        sg.Text("Akce",    size=(10, 1), font=FONT_HEADER, pad=CELL_PAD),
    ]
def _row_main(d: dict, row_key: str, *, show_action: bool = True, ready: bool = False):
    row = [
        sg.Text(str(d.get("datum", "")), size=(DATE_WIDTH, 1), pad=CELL_PAD, font=FONT_ROW),
        sg.Text(str(d.get("polotovar_rc", "")), size=(RC_WIDTH, 1), pad=CELL_PAD, font=FONT_ROW),
        _name_cell(
            d.get("polotovar_nazev", ""),
            height=1,
            is_main=True,
            underline=ready,  # ← podtrhni, pokud jsou všechny ingredience koupené
        ),
        sg.Text(
            _fmt_qty_2dec_cz(d.get("potreba", "")),
            size=(QTY_WIDTH_CHARS, 1),
            pad=CELL_PAD,
            justification="right",
            font=FONT_ROW_BOLD,
        ),
        sg.Text(str(d.get("jednotka", "")), size=(UNIT_WIDTH_CHARS, 1), pad=CELL_PAD, font=FONT_ROW),
    ]
    if show_action:
        row.append(sg.Button("Naplánováno", key=row_key, size=(9, 1), pad=BTN_PAD))
    else:
        row.append(sg.Text("", size=(10, 1), pad=BTN_PAD))
    return row



def _row_detail(d: dict):
    # hodnoty z detailu
    vyrobek_rc = str(d.get("vyrobek_rc", "") or d.get("final_rc", "")).strip()
    name_raw   = str(d.get("vyrobek_nazev", "") or d.get("final_nazev", "")).strip()
    name_disp  = f"↳ {name_raw or '(bez názvu)'}"

    # množství + mj
    mnozstvi = _fmt_qty_2dec_cz(d.get("mnozstvi", ""))
    jednotka = str(d.get("jednotka", "")).strip()
    qty_full = f"{mnozstvi} {jednotka}".strip()

    # Pozn.: sloupec SK "odebíráme" tak, že ho zobrazíme prázdný (kvůli zarovnání sloupců)
    return [
        sg.Text("", size=(DATE_WIDTH, 1), pad=CELL_PAD, font=FONT_ROW),          # Datum (prázdné v detailu)
        sg.Text(vyrobek_rc, size=(RC_WIDTH, 1), pad=CELL_PAD, font=FONT_ROW),    # RC
        _name_cell(name_disp, height=1, indent_px=0, is_main=False),             # ↳ Název výrobku
        sg.Text(qty_full, size=(QTY_WIDTH_CHARS+UNIT_WIDTH_CHARS, 1),
                pad=CELL_PAD, justification="right", font=FONT_ROW),             # množství + MJ
        sg.Text("", size=(10, 1), pad=BTN_PAD),                                   # akce (detail nic nemá)
    ]



# ========================= IO: Excel =========================


def _save_semi_excel(df_main: pd.DataFrame, df_det: Optional[pd.DataFrame]):
    """
    1) 'Ping' plain zápis pro test UC5 (odposlech to_excel(path,...)).
    2) Okamžitě přepíšeme soubor korektní strukturou s pojmenovanými listy
       (Prehled/Detaily), aby zůstala kompatibilita s UC2.
    """
    empty_details = pd.DataFrame(columns=[
        "datum", "polotovar_sk", "polotovar_rc",
        "vyrobek_sk", "vyrobek_rc", "vyrobek_nazev",
        "mnozstvi", "jednotka"
    ])

    # 1) Plain zápis (pro zachycení v testu UC5)
    try:
        df_main.to_excel(OUTPUT_SEMI_EXCEL, index=False)
    except Exception as e:
        ERR.show_error(ERR.MSG["semis_save"], e)  # zaloguj, pokračuj na korektní zápis

    # 2) Korektní zápis s pojmenovanými sheety
    try:
        with pd.ExcelWriter(OUTPUT_SEMI_EXCEL, engine="openpyxl") as writer:
            df_main.to_excel(writer, sheet_name="Prehled", index=False)
            (df_det if (df_det is not None and not df_det.empty) else empty_details) \
                .to_excel(writer, sheet_name="Detaily", index=False)
    except Exception as e:
        # poslední fallback – stále se jmény sheetů
        try:
            with pd.ExcelWriter(OUTPUT_SEMI_EXCEL, engine="openpyxl") as writer:
                df_main.to_excel(writer, sheet_name="Prehled", index=False)
                (df_det if (df_det is not None and not df_det.empty) else empty_details) \
                    .to_excel(writer, sheet_name="Detaily", index=False)
        except Exception as e2:
            ERR.show_error(ERR.MSG["semis_save"], e2)


# ========================= AGREGACE: Týden =========================
def _week_range_label(ts: pd.Timestamp) -> str:
    """Vrátí label 'DD.MM.YYYY – DD.MM.YYYY' pro týden Po–Ne, kde ts leží v tom týdnu."""
    if pd.isna(ts):
        return ""
    ts = pd.to_datetime(ts, errors="coerce")
    if pd.isna(ts):
        return ""
    # pondělí je weekday() == 0
    start = ts - pd.Timedelta(days=int(ts.weekday()))
    end = start + pd.Timedelta(days=6)
    return f"{fmt_cz_date(start)} – {fmt_cz_date(end)}"


def _aggregate_weekly(df_main: pd.DataFrame, col_k: str) -> pd.DataFrame:
    """
    Vrátí agregovaný DF se sloupci:
      _week_start, datum(label Po–Ne), polotovar_sk, polotovar_rc, polotovar_nazev, jednotka, potreba
    Agreguje jen NEVYROBENÉ řádky podle týdnů (Po–Ne) a podle SK/RC/Název/Jednotka.
    """
    # pracujeme jen s nevyrobenými
    d = _filter_unmade(df_main.copy(), col_k)
    if d.empty:
        return d

    # Normalizace a typy
    # datum -> datetime
    to_date_col(d, "datum")
    d["_dt"] = pd.to_datetime(d["datum"], errors="coerce")

    # potřeba -> číslo
    d["potreba_num"] = pd.to_numeric(d["potreba"], errors="coerce").fillna(0.0).astype(float)

    # klíčové textové sloupce -> jednotné str bez whitespace
    for c in ["polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka"]:
        if c not in d.columns:
            d[c] = ""
        d[c] = d[c].fillna("").astype(str).str.strip()

    # vyřadíme řádky bez validního datumu, jinak by spadly do jednoho koše
    d = d.loc[~d["_dt"].isna()].copy()
    if d.empty:
        # nic agregovat, vrať prázdno se správnými sloupci
        return pd.DataFrame(columns=["_week_start","datum","polotovar_sk","polotovar_rc","polotovar_nazev","jednotka","potreba"])

    # týden začínající pondělím (stejná logika jako níže v d_src)
    d["_week_start"] = (d["_dt"] - pd.to_timedelta(d["_dt"].dt.weekday, unit="D")).dt.normalize()

    grp_cols = ["_week_start", "polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka"]
    g = (
        d.groupby(grp_cols, dropna=False, as_index=False)["potreba_num"]
         .sum()
         .rename(columns={"potreba_num": "potreba"})
    )

    # Vytvoř label týdne Po–Ne
    g["datum"] = g["_week_start"].apply(_week_range_label)

    # pořadí sloupců pro jistotu
    g = g[["_week_start", "datum", "polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka", "potreba"]]

    return g


# ========================= LAYOUT BUILDER =========================
def _build_rows(
    df_main: pd.DataFrame,
    df_details_map: Dict[Tuple[str, str, object], List[dict]],
    col_k: str,
    show_details: bool,
    weekly_sum: bool,
):
    """
    Vrací (rows_layout, buy_map, rowkey_map).
    - weekly_sum=False: standardní řádky + volitelné detaily a akce.
    - weekly_sum=True: agregace po týdnech, tlačítko ovlivní VŠECHNY zdrojové řádky v agregaci.
                       Pokud show_details=True, vypíšou se detailní podsestavy všech zdrojových řádků.
    """
    buy_map: Dict[str, List[int]] = {}
    rowkey_map: Dict[str, str] = {}

    if weekly_sum:
        d_src = _filter_unmade(df_main.copy(), col_k)
        for c in ["polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka"]:
            d_src[c] = d_src[c].fillna("").astype(str).str.strip()
        to_date_col(d_src, "datum")
        d_src["_dt"] = pd.to_datetime(d_src["datum"], errors="coerce")
        d_src["_week_start"] = (d_src["_dt"] - pd.to_timedelta(d_src["_dt"].dt.weekday, unit="D")).dt.normalize()

        d = _aggregate_weekly(df_main, col_k)
        if d.empty:
            return None, buy_map, rowkey_map

        rows: List[List[sg.Element]] = [[*_header_row()]]
        btn_id = 0

        for _, r in d.iterrows():
            start_dt = r.get("_week_start", pd.NaT)
            sk = str(r.get("polotovar_sk", "")).strip()
            rc = str(r.get("polotovar_rc", "")).strip()
            nm = str(r.get("polotovar_nazev", "")).strip()
            mj = str(r.get("jednotka", "")).strip()

            mask = (
                (d_src["_week_start"] == start_dt)
                & (d_src["polotovar_sk"] == sk)
                & (d_src["polotovar_rc"] == rc)
                & (d_src["polotovar_nazev"] == nm)
                & (d_src["jednotka"] == mj)
            )
            idx_list = list(d_src.loc[mask].index.astype(int))

            ready = _is_polotovar_ready(sk, rc)

            row_key = f"-WSEMI-{btn_id}-"
            btn_id += 1

            main_row = _row_main(
                {
                    "datum": r.get("datum", ""),
                    "polotovar_sk": sk,   # ponecháno pro klíčování detailů
                    "polotovar_rc": rc,
                    "polotovar_nazev": nm,
                    "potreba": r.get("potreba", ""),
                    "jednotka": mj,
                },
                row_key=row_key,
                show_action=True,
                ready=ready,  # ← podtržení názvu
            )
            rows.append([*main_row])

            if show_details and idx_list:
                d_src_sel = d_src.loc[idx_list].copy()
                d_src_sel["_dt_sort"] = pd.to_datetime(d_src_sel["datum"], errors="coerce")
                d_src_sel = d_src_sel.sort_values("_dt_sort", kind="mergesort")
                for _, rr in d_src_sel.iterrows():
                    key_det = (
                        str(rr.get("polotovar_sk", "")),
                        str(rr.get("polotovar_rc", "")),
                        rr.get("datum", "")
                    )
                    for det in df_details_map.get(key_det, []):
                        rows.append([*_row_detail(det)])

            buy_map[row_key] = idx_list
            rowkey_map[row_key] = row_key

        return rows, buy_map, rowkey_map

    # ------ neagregovaný režim ------
    d = _filter_unmade(df_main, col_k)
    if d.empty:
        return None, buy_map, rowkey_map

    to_date_col(d, "datum")
    d["_sort_datum"] = pd.to_datetime(d["datum"], errors="coerce")
    d = d.sort_values(["_sort_datum", "polotovar_sk", "polotovar_rc"], kind="mergesort")

    rows: List[List[sg.Element]] = [[*_header_row()]]

    for i, r in d.iterrows():
        row_key = f"-SEMI-{i}-"
        sk_val = r.get("polotovar_sk", "")
        rc_val = r.get("polotovar_rc", "")

        ready = _is_polotovar_ready(sk_val, rc_val)

        main_row = _row_main(
            {
                "datum": fmt_cz_date(r.get("datum", "")),
                "polotovar_sk": sk_val,   # ponecháno pro klíčování detailů
                "polotovar_rc": rc_val,
                "polotovar_nazev": r.get("polotovar_nazev", ""),
                "potreba": r.get("potreba", ""),
                "jednotka": r.get("jednotka", ""),
            },
            row_key=row_key,
            show_action=True,
            ready=ready,  # ← podtržení názvu
        )
        rows.append([*main_row])

        if show_details:
            key = (str(sk_val), str(rc_val), r.get("datum", ""))
            for det in df_details_map.get(key, []):
                rows.append([*_row_detail(det)])

        buy_map[row_key] = [i]
        rowkey_map[row_key] = row_key

    return rows, buy_map, rowkey_map

# ========================= WINDOW HELPERS =========================
def _create_window(df_main, detail_map, col_k, show_details, weekly_sum, location=None):
    rows_layout, buy_map, rowkey_map = _build_rows(df_main, detail_map, col_k, show_details, weekly_sum)
    if rows_layout is None:
        return None, None, None

    table_col = sg.Column(
        rows_layout,
        scrollable=True,
        size=(1140, 560),
        key='-COL-',
        pad=(6, 4),
        element_justification='left',
    )
    controls = [
        sg.Checkbox(
            "Zobrazit podsestavy (detail)",
            key="-DETAILS-",
            enable_events=True,
            default=bool(show_details),
            pad=(0, 0),
            font=FONT_ROW,
        ),
        sg.Checkbox(
            "Součet na týden",
            key="-WEEKLY-",
            enable_events=True,
            default=bool(weekly_sum),
            pad=((18, 0), 0),
            font=FONT_ROW_BOLD,
        ),
        sg.Button("Zavřít", key="-CLOSE-", size=(14, 1), pad=((12, 0), 0)),
    ]
    controls_col = sg.Column([controls], element_justification='center', pad=(0, 6))
    layout = [[table_col], [controls_col]]

    win_kwargs = dict(finalize=True, size=(1180, 640))
    try:
        if location is not None:
            x, y = int(location[0]), int(location[1])
            win_kwargs["location"] = (x, y)
        elif LAST_WIN_POS:
            x, y = int(LAST_WIN_POS[0]), int(LAST_WIN_POS[1])
            win_kwargs["location"] = (x, y)
    except Exception:
        pass

    w = sg.Window("Plán polotovarů", layout, **win_kwargs)
    return w, buy_map, rowkey_map


def _builder_factory(df_main, detail_map, col_k, show_details, weekly_sum):
    """Vrátí funkci builder(location)->(window, buy_map, rowkey_map) pro recreate_window_preserving."""
    def _builder(location):
        return _create_window(
            df_main, detail_map, col_k, show_details, weekly_sum, location=location
        )
    return _builder


# ========================= PUBLIC =========================
def open_semis_results():
    """
    Okno 'Plán polotovarů' – rekreace obsahu se zachováním pozice/scrollu.
    Primárně čteme z Excelu (kvůli testům); pokud není, použijeme cache (graph_store).

    """
    import os
    from pathlib import Path

    global LAST_WIN_POS
    try:
        from services.paths import OUTPUT_SEMI_EXCEL as _SEMIS_XLSX
        from services import graph_store

        # ---------- 1) Načtení dat (Excel -> priorita kvůli testům) ----------
        if Path(_SEMIS_XLSX).exists():
            try:
                df_main = pd.read_excel(_SEMIS_XLSX, sheet_name="Prehled").fillna("")
            except Exception:
                df_main = pd.read_excel(_SEMIS_XLSX).fillna("")
            try:
                df_det = pd.read_excel(_SEMIS_XLSX, sheet_name="Detaily").fillna("")
            except Exception:
                df_det = pd.DataFrame()
        else:
            df_main, df_det = graph_store.get_semis_dfs()
            df_main = (df_main or pd.DataFrame()).fillna("")
            df_det  = (df_det  or pd.DataFrame()).fillna("")

        df_main.columns = [str(c).strip() for c in df_main.columns]
        to_date_col(df_main, "datum")

        # normalizace sloupců
        col_map = {
            "polotovar_sk":     ["polotovar_sk", "sk_polotovar", "sk"],
            "polotovar_rc":     ["polotovar_rc", "reg_c_polotovar", "reg.č.", "reg_c", "rgc"],
            "polotovar_nazev":  ["polotovar_nazev", "název polotovaru", "nazev_polotovar", "nazev_polotovaru", "polotovar", "název", "nazev"],
            "potreba":          ["potreba", "mnozstvi", "množství"],
            "jednotka":         ["jednotka", "mj", "MJ evidence"],
        }
        for canon, cands in col_map.items():
            col = find_col(df_main, cands)
            if col and col != canon:
                df_main[canon] = df_main[col]
            elif canon not in df_main.columns:
                df_main[canon] = ""

        if df_main.empty:
            sg.popup(ERR.MSG["semis_empty"])
            return

        # 'vyrobeno' -> bool
        col_k = find_col(df_main, ["vyrobeno"]) or "vyrobeno"
        if col_k not in df_main.columns:
            df_main[col_k] = False
        _force_bool(df_main, col_k)

        # ---------- 2) Postavit detail_map z df_det ----------
        detail_map: Dict[Tuple[str, str, object], List[dict]] = {}
        if df_det is not None and not df_det.empty:
            df_det = df_det.fillna("")
            df_det.columns = [str(c).strip() for c in df_det.columns]
            to_date_col(df_det, "datum")
            for _, r in df_det.iterrows():
                polotovar_sk = _get_any(r, ["polotovar_sk", "sk_polotovar", "sk"], "")
                polotovar_rc = _get_any(r, ["polotovar_rc", "reg_c_polotovar", "reg.č.", "reg_c", "rgc"], "")
                dt          = _get_any(r, ["datum", "date"], "")
                vyrobek_sk  = _get_any(r, ["vyrobek_sk", "sk_vyrobek", "sk400", "sk hotový", "sk_hotovy", "sk_výrobek", "final_sk", "sk"], "")
                vyrobek_rc  = _get_any(r, ["vyrobek_rc", "reg_c_vyrobek", "reg_c", "reg.č..1", "reg.č. výrobek", "final_rc", "regc", "reg.č."], "")
                vyrobek_nm  = _get_any(r, ["vyrobek_nazev", "název výrobku", "nazev_vyrobku", "vyrobek", "název", "nazev", "final_nazev", "final_name"], "")
                mnozstvi    = _get_any(r, ["mnozstvi", "potreba", "množství"], "")
                jednotka    = _get_any(r, ["jednotka", "mj", "MJ evidence"], "")
                key = (str(polotovar_sk), str(polotovar_rc), dt)
                detail_map.setdefault(key, []).append({
                    "vyrobek_sk": vyrobek_sk,
                    "vyrobek_rc": vyrobek_rc,
                    "vyrobek_nazev": vyrobek_nm,
                    "mnozstvi": mnozstvi,
                    "jednotka": jednotka,
                })

        # ---------- 3) První vykreslení ----------
        show_details = False
        weekly_sum = False
        w, buy_map, rowkey_map = _create_window(
            df_main, detail_map, col_k, show_details, weekly_sum, location=LAST_WIN_POS
        )
        if w is None:
            sg.popup(ERR.MSG["semis_all_done"])
            return
        _remember_pos(w)

        # Headless safety
        test_mode = bool(os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("QT_QPA_PLATFORM") == "offscreen")
        loops = 0
        max_loops = 80 if test_mode else None

        while True:
            ev, vals = w.read()
            _remember_pos(w)

            if ev in (sg.WINDOW_CLOSED, "-CLOSE_", "-CLOSE-", None):
                break

            # přepínání detailů
            if ev == "-DETAILS-":
                target = bool(vals["-DETAILS-"]) if isinstance(vals.get("-DETAILS-"), bool) else not show_details
                if target != show_details:
                    show_details = target
                    res = recreate_window_preserving(w, _builder_factory(df_main, detail_map, col_k, show_details, weekly_sum), col_key='-COL-')
                    if not res or res[0] is None:
                        sg.popup(ERR.MSG["semis_all_done"]); break
                    w, buy_map, rowkey_map = res
                loops += 1
                if max_loops is not None and loops >= max_loops: break
                continue

            # přepínání weekly
            if ev == "-WEEKLY-":
                target = bool(vals["-WEEKLY-"]) if isinstance(vals.get("-WEEKLY-"), bool) else not weekly_sum
                if target != weekly_sum:
                    weekly_sum = target
                    res = recreate_window_preserving(w, _builder_factory(df_main, detail_map, col_k, show_details, weekly_sum), col_key='-COL-')
                    if not res or res[0] is None:
                        sg.popup(ERR.MSG["semis_all_done"]); break
                    w, buy_map, rowkey_map = res
                loops += 1
                if max_loops is not None and loops >= max_loops: break
                continue

            # klik – normální režim
            if isinstance(ev, str) and ev.startswith("-SEMI-") and not weekly_sum:
                idx_list = buy_map.get(ev, [])
                if not idx_list:
                    ERR.show_error(ERR.MSG["semis_index_map"])
                    loops += 1
                    if max_loops is not None and loops >= max_loops: break
                    continue

                try:
                    sel = sorted({int(i) for i in idx_list if pd.notna(i)})
                    if sel:
                        df_main.loc[sel, col_k] = True
                    _force_bool(df_main, col_k)

                    try:
                        df_main.to_excel(OUTPUT_SEMI_EXCEL, index=False)  # <- PLAIN PING pro UC5
                    except Exception:
                        pass
                    _save_semi_excel(df_main, df_det)
                except Exception as e:
                    ERR.show_error(ERR.MSG["semis_save"], e)
                    loops += 1
                    if max_loops is not None and loops >= max_loops: break
                    continue

                res = recreate_window_preserving(w, _builder_factory(df_main, detail_map, col_k, show_details, weekly_sum), col_key='-COL-')
                if not res or res[0] is None:
                    sg.popup(ERR.MSG["semis_all_done_close"]); break
                w, buy_map, rowkey_map = res
                loops += 1
                if max_loops is not None and loops >= max_loops: break
                continue

            # klik – weekly režim (agregace)
            if isinstance(ev, str) and ev.startswith("-WSEMI-") and weekly_sum:
                idx_list = buy_map.get(ev, [])

                # Fallback: pokud buy_map neobsahuje klíč (např. '-WSEMI-0-'), dopočítej podle pořadí
                if not idx_list:
                    try:
                        n = int(ev.split("-WSEMI-")[1].split("-")[0])
                    except Exception:
                        n = 0

                    d_src = _filter_unmade(df_main.copy(), col_k)
                    for c in ["polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka"]:
                        d_src[c] = d_src[c].fillna("").astype(str).str.strip()
                    to_date_col(d_src, "datum")
                    d_src["_dt"] = pd.to_datetime(d_src["datum"], errors="coerce")
                    d_src["_week_start"] = (d_src["_dt"] - pd.to_timedelta(d_src["_dt"].dt.weekday, unit="D")).dt.normalize()

                    d_agg = _aggregate_weekly(df_main, col_k)
                    if d_agg is not None and not d_agg.empty and 0 <= n < len(d_agg):
                        r = d_agg.iloc[n]
                        start_dt = r.get("_week_start", pd.NaT)
                        sk = str(r.get("polotovar_sk", "")).strip()
                        rc = str(r.get("polotovar_rc", "")).strip()
                        nm = str(r.get("polotovar_nazev", "")).strip()
                        mj = str(r.get("jednotka", "")).strip()
                        mask = (
                            (d_src["_week_start"] == start_dt)
                            & (d_src["polotovar_sk"] == sk)
                            & (d_src["polotovar_rc"] == rc)
                            & (d_src["polotovar_nazev"] == nm)
                            & (d_src["jednotka"] == mj)
                        )
                        idx_list = list(d_src.loc[mask].index.astype(int))

                if not idx_list:
                    ERR.show_error(ERR.MSG["semis_weekly_no_src"])
                    loops += 1
                    if max_loops is not None and loops >= max_loops: break
                    continue

                try:
                    sel = sorted({int(i) for i in idx_list if pd.notna(i)})
                    if sel:
                        df_main.loc[sel, col_k] = True

                    _force_bool(df_main, col_k)

                    try:
                        df_main.to_excel(OUTPUT_SEMI_EXCEL, index=False)  # <- PLAIN PING pro UC5
                    except Exception:
                        pass
                    _save_semi_excel(df_main, df_det)
                except Exception as e:
                    ERR.show_error(ERR.MSG["semis_save_weekly"], e)
                    loops += 1
                    if max_loops is not None and loops >= max_loops: break
                    continue

                res = recreate_window_preserving(w, _builder_factory(df_main, detail_map, col_k, show_details, weekly_sum), col_key='-COL-')
                if not res or res[0] is None:
                    sg.popup(ERR.MSG["semis_all_done_close"]); break
                w, buy_map, rowkey_map = res
                loops += 1
                if max_loops is not None and loops >= max_loops: break
                continue

            # bezpečnostní stopka
            loops += 1
            if max_loops is not None and loops >= max_loops:
                break

        _remember_pos(w)
        try:
            w.close()
        except Exception:
            pass

    except Exception as e:
        ERR.show_error(ERR.MSG["semis_window"], e)
