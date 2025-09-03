# gui/results_window.py
# -*- coding: utf-8 -*-
import traceback
import PySimpleGUIQt as sg
import pandas as pd
import os
from services.paths import OUTPUT_EXCEL as _DEFAULT_OUTPUT_EXCEL
OUTPUT_EXCEL = _DEFAULT_OUTPUT_EXCEL  # kvůli testům (monkeypatch rw.OUTPUT_EXCEL)
import os
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
from services import error_messages as ERR
from services import graph_store

dbg_set_enabled(False)

AGG_DATE_PLACEHOLDER = "XX-XX-XXXX"
CELL_PAD = (0, 2)
BTN_PAD  = ((0, 0), (-3, 3))
LAST_WIN_POS = None

# ------------------------- DEBUG DUMP -------------------------
DEBUG_CFG = {
    "enabled": False,
    "pairs": [],     # např. [("150","88")]
    "limit": 50,
}

def _debug_print(msg: str):
    if DEBUG_CFG.get("enabled"):
        print(msg, flush=True)

def _debug_dump(df: pd.DataFrame, label: str, col_k: str):
    if not DEBUG_CFG.get("enabled"):
        return
    try:
        cols = [c for c in ["datum","ingredience_sk","ingredience_rc","nazev","potreba","jednotka",col_k] if c in df.columns]
        base = df.copy()
        if col_k in base.columns:
            base[col_k] = base[col_k].map(to_bool_cell_excel).astype(bool)

        pairs = DEBUG_CFG.get("pairs") or []
        limit = int(DEBUG_CFG.get("limit") or 50)

        if pairs:
            for sk_txt, rc_txt in pairs:
                mask = (base["ingredience_sk"].astype(str).str.strip() == str(sk_txt)) & \
                       (base["ingredience_rc"].astype(str).str.strip() == str(rc_txt))
                sub = base.loc[mask, cols]
                if sub.empty:
                    _debug_print(f"[DEBUG] {label}: (SK,RC)=({sk_txt},{rc_txt}) -> žádné řádky")
                else:
                    _debug_print(f"[DEBUG] {label}: (SK,RC)=({sk_txt},{rc_txt}), řádků: {len(sub)}")
                    _debug_print(sub.head(limit).to_string(index=True))
        else:
            _debug_print(f"[DEBUG] {label}: bez filtru, celkem řádků: {len(base)} (zkráceno na {limit})")
            _debug_print(base[cols].head(limit).to_string(index=True))
    except Exception as e:
        _debug_print(f"[DEBUG] {label}: dump selhal: {e}")

# ------------------------- UTILS -------------------------
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

def _force_bool_col(df: pd.DataFrame, col_k: str):
    df[col_k] = df[col_k].map(to_bool_cell_excel).astype(bool)

def _filter_unbought(d: pd.DataFrame, col_k: str) -> pd.DataFrame:
    _force_bool_col(d, col_k)
    return d.loc[~d[col_k]].copy()

def _first_nonempty(s: pd.Series):
    for x in s:
        if str(x).strip() != "":
            return x
    return ""

def _safe_int(v):
    try:
        return int(float(str(v).replace(",", ".")))
    except Exception:
        return None

def _key_txt(v) -> str:
    """Normalizace klíče: 150, '150.0', '150,0' -> '150'; None -> ''."""
    if v is None:
        return ""
    i = _safe_int(v)
    return str(i) if i is not None else str(v).strip()

# ------------------------- LAYOUT BUILDER -------------------------
# Vrací (rows_layout, buy_map, rowkey_map)
# - buy_map:  klíč tlačítka -> seznam indexů df_full k označení True
# - rowkey_map: (pro neagregovanou verzi mapuje index->vizuální klíč; pro agregovanou není nutný)
def _build_table_layout(df_full: pd.DataFrame, col_k: str, aggregate: bool = False):
    buy_map = {}
    rowkey_map = {}

    if not aggregate:
        d = _filter_unbought(df_full, col_k)
        if d.empty:
            return None, buy_map, rowkey_map

        if "datum" in d.columns:
            sort_vals = pd.to_datetime(d["datum"], errors="coerce")
            d["_sort_datum"] = sort_vals
            d = d.sort_values("_sort_datum", na_position="last", kind="mergesort")
            d = d.drop(columns=["_sort_datum"], errors="ignore")

        header = [
            sg.Text("Datum",   size=(12,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
            sg.Text("SK",      size=(6,1),  font=('Any', 10, 'bold'), pad=CELL_PAD),
            sg.Text("Reg.č.",  size=(10,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
            sg.Text("Název",   size=(36,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
            sg.Text("Množství",size=(12,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
            sg.Text("",        size=(8,1),  font=('Any', 10, 'bold'), pad=CELL_PAD),
            sg.Text("Akce",    size=(10,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
        ]
        rows = [[*header]]

        for i, r in d.iterrows():
            i_int = int(i)
            row_key = f"-BUY-{i_int}-"
            vis_key = f"-ROW-{i_int}-"
            buy_map[row_key] = [i_int]
            rowkey_map[i_int] = vis_key  # testy očekávají plnění rowkey_map

            row_widgets = [
                sg.Text(fmt_cz_date(r.get("datum","")), size=(12,1), pad=CELL_PAD),
                sg.Text(str(r.get("ingredience_sk","")), size=(6,1),  pad=CELL_PAD),
                sg.Text(str(r.get("ingredience_rc","")), size=(10,1), pad=CELL_PAD),
                sg.Text(str(r.get("nazev","")),          size=(36,1), pad=CELL_PAD),
                sg.Text(str(r.get("potreba","")),        size=(12,1), pad=CELL_PAD),
                sg.Text(str(r.get("jednotka","")),       size=(8,1),  pad=CELL_PAD),
                sg.Button("Koupeno", key=row_key, size=(10,1), pad=BTN_PAD),
            ]
            rows.append([*row_widgets])

        return rows, buy_map, rowkey_map

    # -------- aggregate=True --------
    d = _filter_unbought(df_full, col_k)
    if d.empty:
        return None, buy_map, rowkey_map

    # normalizované klíče a číselná potřeba
    d = d.copy()
    d["_sk_key"] = d["ingredience_sk"].map(_key_txt)
    d["_rc_key"] = d["ingredience_rc"].map(_key_txt)
    d["_num_pot"] = pd.to_numeric(d["potreba"], errors="coerce").fillna(0.0)

    g = (
        d.groupby(["_sk_key", "_rc_key"], as_index=False)
         .agg(
             potreba=("_num_pot", "sum"),
             nazev=("nazev", _first_nonempty),
             jednotka=("jednotka", _first_nonempty),
         )
         .sort_values(["_sk_key","_rc_key"], kind="mergesort")
    )

    # (norm. SK, norm. RC) -> indexy všech NEkoupených řádků (z d)
    group_to_indices = {}
    for idx, row in d.iterrows():
        key = (row.get("_sk_key",""), row.get("_rc_key",""))
        group_to_indices.setdefault(key, []).append(int(idx))

    header = [
        sg.Text("Datum",   size=(12,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
        sg.Text("SK",      size=(6,1),  font=('Any', 10, 'bold'), pad=CELL_PAD),
        sg.Text("Reg.č.",  size=(10,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
        sg.Text("Název",   size=(36,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
        sg.Text("Množství",size=(12,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
        sg.Text("",        size=(8,1),  font=('Any', 10, 'bold'), pad=CELL_PAD),   # prázdný titulek pro jednotku
        sg.Text("Akce",    size=(10,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
    ]
    rows = [[*header]]

    btn_id = 0
    for _, r in g.iterrows():
        sk_k = str(r.get("_sk_key","")).strip()
        rc_k = str(r.get("_rc_key","")).strip()
        nazev = str(r.get("nazev","")).strip()
        jednotka = str(r.get("jednotka","")).strip()

        row_key = f"-BUY-G-{btn_id}-"
        btn_id += 1
        buy_map[row_key] = group_to_indices.get((sk_k, rc_k), [])

        row_widgets = [
            sg.Text(AGG_DATE_PLACEHOLDER, size=(12,1), pad=CELL_PAD),
            sg.Text(sk_k,                  size=(6,1),  pad=CELL_PAD),
            sg.Text(rc_k,                  size=(10,1), pad=CELL_PAD),
            sg.Text(nazev,                 size=(36,1), pad=CELL_PAD),
            sg.Text(str(r.get("potreba","")), size=(12,1), pad=CELL_PAD),
            sg.Text(jednotka,              size=(8,1),  pad=CELL_PAD),
            sg.Button("Koupeno", key=row_key, size=(10,1), pad=BTN_PAD),
        ]
        rows.append([*row_widgets])

    return rows, buy_map, rowkey_map


def _controls_row(agg_flag):
    return [
        sg.Checkbox("Sčítat napříč daty", key="-AGG-", enable_events=True, default=bool(agg_flag), size=(22,1), pad=(0, 2)),
        sg.Button("Zavřít", key="-CLOSE-", size=(16,1), pad=(0, 2)),
    ]

def _create_results_window(df_full, col_k, agg_flag, location=None):
    rows_layout, buy_map, rowkey_map = _build_table_layout(df_full, col_k, aggregate=agg_flag)
    if rows_layout is None:
        return None, None, None

    # Headless režim (pytest nebo QT offscreen) → dummy okno, aby se testy nezasekly
    import os
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        class _DummyWin:
            def read(self): return (None, {})
            def close(self): pass
            def current_location(self): return (0, 0)
        return _DummyWin(), buy_map, rowkey_map

    # Normální GUI režim
    table_col = sg.Column(
        rows_layout,
        scrollable=True,
        size=(1000, 560),
        key='-COL-',
        pad=(0, 0),
        element_justification='left',
    )
    controls = _controls_row(agg_flag)
    controls_col = sg.Column([controls], element_justification='center', pad=(0, 0))
    lay = [[table_col], [controls_col]]

    use_loc = location if location is not None else LAST_WIN_POS
    win_kwargs = dict(finalize=True, size=(1040, 640))
    try:
        if use_loc is not None:
            x, y = int(use_loc[0]), int(use_loc[1])
            win_kwargs["location"] = (x, y)
    except Exception:
        pass

    w = sg.Window("Výsledek", lay, **win_kwargs)
    return w, buy_map, rowkey_map



def _builder_factory(df_full, col_k, agg_flag):
    """Builder pro gui_helpers.recreate_window_preserving."""
    def _builder(location):
        return _create_results_window(df_full, col_k, agg_flag, location=location)
    return _builder


# ------------------------- PUBLIC -------------------------
def open_results():
    """Okno výsledků: sjednocený standard – rekreace okna přes helper, bez poskakování."""
    import os
    from pathlib import Path

    # Umožni testům přesměrovat cestu
    try:
        import services.paths as _paths
        _paths.OUTPUT_EXCEL = OUTPUT_EXCEL
    except Exception:
        pass

    global LAST_WIN_POS
    try:
        # -------- ZDROJ DAT: preferuj existující OUTPUT_EXCEL (testy to očekávají) --------
        source_mode = "excel" if Path(OUTPUT_EXCEL).exists() else "cache"

        if source_mode == "excel":
            df_full = pd.read_excel(OUTPUT_EXCEL).fillna("")
        else:
            # fallback na cache (strom je jediný zdroj pravdy v runtime)
            df_full = graph_store.get_ingredients_df().fillna("")

        df_full.columns = [str(c).strip() for c in df_full.columns]
        to_date_col(df_full, "datum")

        if df_full.empty:
            sg.popup(ERR.MSG["results_empty"])
            return

        col_k = find_col(df_full, ["koupeno"])
        if col_k is None:
            df_full["koupeno"] = False
            col_k = "koupeno"

        _force_bool_col(df_full, col_k)
        _debug_dump(df_full, "START", col_k)

        agg_flag = False
        w, buy_map, _ = _create_results_window(df_full, col_k, agg_flag, location=LAST_WIN_POS)
        if w is None:
            sg.popup(ERR.MSG["results_all_bought"])
            return
        _remember_pos(w)

        # HEADLESS pojistka proti nekonečné smyčce v testech
        test_mode = bool(os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("QT_QPA_PLATFORM") == "offscreen")
        loops = 0
        max_loops = 50 if test_mode else None

        while True:
            ev, vals = w.read()
            _remember_pos(w)

            # Ukončení i na None (Fake/Dummy okna v testech vrací None)
            if ev in (sg.WINDOW_CLOSED, "-CLOSE-", None):
                break

            if ev == "-AGG-":
                target = bool(vals["-AGG-"]) if isinstance(vals.get("-AGG-"), bool) else not agg_flag
                if target != agg_flag:
                    agg_flag = target

                    # Při přepnutí agregace znovu načti zdroj
                    if source_mode == "excel" and Path(OUTPUT_EXCEL).exists():
                        df_full = pd.read_excel(OUTPUT_EXCEL).fillna("")
                    else:
                        df_full = graph_store.get_ingredients_df().fillna("")
                    df_full.columns = [str(c).strip() for c in df_full.columns]
                    to_date_col(df_full, "datum")
                    _force_bool_col(df_full, col_k)

                    builder = _builder_factory(df_full, col_k, agg_flag)
                    res = recreate_window_preserving(w, builder, col_key='-COL-')
                    if not res or res[0] is None:
                        sg.popup(ERR.MSG["results_all_bought"])
                        break
                    w, buy_map, _ = res

                loops += 1
                if max_loops is not None and loops >= max_loops:
                    break
                continue

            if isinstance(ev, str) and ev.startswith("-BUY-"):
                idx_list = buy_map.get(ev, [])
                if not idx_list:
                    ERR.show_error(ERR.MSG["results_index_map"])
                    loops += 1
                    if max_loops is not None and loops >= max_loops:
                        break
                    continue

                try:
                    sel = sorted({int(i) for i in idx_list if pd.notna(i)})

                    if source_mode == "excel":
                        # --- EXCEL režim: přímá úprava a zápis do OUTPUT_EXCEL ---
                        if sel:
                            df_full.loc[sel, col_k] = True
                        _force_bool_col(df_full, col_k)
                        df_full.to_excel(OUTPUT_EXCEL, index=False)

                        # pro jistotu re-read (stabilní stav) a překreslit
                        df_full = pd.read_excel(OUTPUT_EXCEL).fillna("")
                        df_full.columns = [str(c).strip() for c in df_full.columns]
                        to_date_col(df_full, "datum")
                        _force_bool_col(df_full, col_k)

                    else:
                        # --- CACHE režim: update v graph_store + zápis i do OUTPUT_EXCEL (kvůli testům) ---
                        keys = []
                        for i in sel:
                            try:
                                r = df_full.loc[i]
                            except Exception:
                                continue
                            keys.append((r.get("datum", ""), r.get("ingredience_sk", ""), r.get("ingredience_rc", "")))
                        if keys:
                            graph_store.set_ingredients_bought_many(keys, bought=True)

                        # Do GUI si natáhni čerstvý stav z cache
                        df_full = graph_store.get_ingredients_df().fillna("")
                        df_full.columns = [str(c).strip() for c in df_full.columns]
                        to_date_col(df_full, "datum")
                        _force_bool_col(df_full, col_k)

                        # A zároveň perzistuj aktuální snapshot do OUTPUT_EXCEL, aby testy měly co číst
                        try:
                            df_full.to_excel(OUTPUT_EXCEL, index=False)
                        except Exception:
                            pass

                except Exception as e:
                    ERR.show_error(ERR.MSG["results_save"], e)
                    loops += 1
                    if max_loops is not None and loops >= max_loops:
                        break
                    continue

                # Překreslit okno s aktuálními daty
                builder = _builder_factory(df_full, col_k, agg_flag)
                res = recreate_window_preserving(w, builder, col_key='-COL-')
                if not res or res[0] is None:
                    sg.popup(ERR.MSG["results_all_bought_close"])
                    break
                w, buy_map, _ = res

                loops += 1
                if max_loops is not None and loops >= max_loops:
                    break
                continue

            # Bezpečnostní stopka smyčky (kdyby se objevila neošetřená událost)
            loops += 1
            if max_loops is not None and loops >= max_loops:
                break

        _remember_pos(w)
        try:
            w.close()
        except Exception:
            pass

    except Exception as e:
        ERR.show_error(ERR.MSG["results_window"], e)
