# gui/results_window.py
import traceback
import PySimpleGUIQt as sg
import pandas as pd
from datetime import date

from services.paths import OUTPUT_EXCEL
from services.data_utils import (
    to_date_col,
    find_col,
    fmt_cz_date,
    to_bool_cell_excel,
)

AGG_DATE_PLACEHOLDER = "XX-XX-XXXX"
# Těsnější rozestupy:
CELL_PAD = (0, 2)              # textové buňky
BTN_PAD  = ((0, 0), (-3, 3))   # tlačítko lehce výš, menší výška

# Perzistence pozice okna
LAST_WIN_POS = None  # tuple[int,int] | None

# --------------------------------------------------------------------
# DEBUG – JASNÉ OVLÁDÁNÍ
#   Zap/vyp:  DEBUG_CFG["enabled"] = True/False
#   Filtry:   DEBUG_CFG["pairs"] = [("150","88"), ("200","33")]  # SK, RC jako text
#             (když je prázdné, loguje všechny řádky – pozor na limit)
#   Limit:    DEBUG_CFG["limit"] = 50  # max počet vypsaných řádků v jednom dumpu
# --------------------------------------------------------------------
DEBUG_CFG = {
    "enabled": False,
    "pairs": [],     # např. [("150","88")]j
    "limit": 50,
}


# ----------------------------- pomocné převody --------------------------------

def _force_bool_col(df: pd.DataFrame, col_k: str):
    df[col_k] = df[col_k].map(to_bool_cell_excel).astype(bool)

def _safe_int(v):
    try:
        return int(float(str(v).replace(",", ".")))
    except Exception:
        return None

def _key_txt(v) -> str:
    if v is None:
        return ""
    i = _safe_int(v)
    return str(i) if i is not None else str(v).strip()

def _first_nonempty(s: pd.Series):
    for x in s:
        if str(x).strip() != "":
            return x
    return ""


# ----------------------------- utility ---------------------------------------

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

def _filter_unbought(d: pd.DataFrame, col_k: str) -> pd.DataFrame:
    _force_bool_col(d, col_k)
    return d.loc[~d[col_k]].copy()

def _debug_print(msg: str):
    """Bezpečný debug print – respektuje DEBUG_CFG['enabled']."""
    if DEBUG_CFG.get("enabled"):
        print(msg, flush=True)

def _debug_dump(df: pd.DataFrame, label: str, col_k: str):
    """
    Univerzální dump:
      - Pokud je DEBUG_CFG['pairs'] neprázdné, vypíše pro všechny zadané (SK,RC).
      - Pokud je prázdné, vypíše všechny řádky (omezené 'limit').
    """
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
                mask = (base["ingredience_sk"].map(_key_txt) == str(sk_txt)) & \
                       (base["ingredience_rc"].map(_key_txt) == str(rc_txt))
                sub = base.loc[mask, cols]
                if sub.empty:
                    _debug_print(f"[DEBUG] {label}: (SK,RC)=({sk_txt},{rc_txt}) -> žádné řádky")
                else:
                    _debug_print(f"[DEBUG] {label}: (SK,RC)=({sk_txt},{rc_txt}), řádků: {len(sub)}")
                    _debug_print(sub.head(limit).to_string(index=True))
        else:
            # bez filtrů – loguj vše (omezeno limitem)
            _debug_print(f"[DEBUG] {label}: bez filtru, celkem řádků: {len(base)} (zkráceno na {limit})")
            _debug_print(base[cols].head(limit).to_string(index=True))
    except Exception as e:
        _debug_print(f"[DEBUG] {label}: dump selhal: {e}")


# --------------------------- layout builder ----------------------------------
# Vrací (rows_layout, buy_map, rowkey_map)
# - buy_map:  klíč tlačítka -> seznam indexů df_full k označení True
# - rowkey_map:
#     NEAGREG: index df_full -> vizuální klíč řádku (aby šel schovat)
#     AGREG:   klíč tlačítka -> vizuální klíč agregovaného řádku

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
            d = (
                d.sort_values("_sort_datum", na_position="last", kind="mergesort")
                 .drop(columns=["_sort_datum"], errors="ignore")
            )

        # Těsný header
        header = [
            sg.Text("Datum", size=(12,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
            sg.Text("SK",    size=(6,1),  font=('Any', 10, 'bold'), pad=CELL_PAD),
            sg.Text("Reg.č.",size=(10,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
            sg.Text("Název", size=(36,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
            sg.Text("Množství", size=(12,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
            sg.Text("", size=(8,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
            sg.Text("Akce", size=(10,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
        ]
        rows = [[*header]]

        for i, r in d.iterrows():
            row_key = f"-BUY-{i}-"
            vis_key = f"-ROW-{i}-"
            buy_map[row_key] = [i]
            rowkey_map[i] = vis_key

            row_widgets = [
                sg.Text(fmt_cz_date(r.get("datum","")), size=(12,1), pad=CELL_PAD),
                sg.Text(str(r.get("ingredience_sk","")),  size=(6,1),  pad=CELL_PAD),
                sg.Text(str(r.get("ingredience_rc","")),  size=(10,1), pad=CELL_PAD),
                sg.Text(str(r.get("nazev","")),           size=(36,1), pad=CELL_PAD),
                sg.Text(str(r.get("potreba","")),         size=(12,1), pad=CELL_PAD),
                sg.Text(str(r.get("jednotka","")),        size=(8,1),  pad=CELL_PAD),
                sg.Button("Koupeno", key=row_key, size=(10,1), pad=BTN_PAD),
            ]
            # Každý řádek do vlastního Column → půjde schovat bez rebuildů
            rows.append([sg.Column([row_widgets], key=vis_key, pad=(0,0), element_justification="left")])

        return rows, buy_map, rowkey_map

    # -------- aggregate=True --------
    d = _filter_unbought(df_full, col_k)
    if d.empty:
        return None, buy_map, rowkey_map

    d["_num_pot"] = pd.to_numeric(d["potreba"], errors="coerce").fillna(0.0)
    d["_sk_key"] = d["ingredience_sk"].map(_key_txt)
    d["_rc_key"] = d["ingredience_rc"].map(_key_txt)

    g = (
        d.groupby(["_sk_key", "_rc_key"], as_index=False)
         .agg(
             potreba=("_num_pot", "sum"),
             nazev=("nazev", _first_nonempty),
             jednotka=("jednotka", _first_nonempty),
         )
         .sort_values(["_sk_key","_rc_key"], kind="mergesort")
    )

    # (SK,RC) -> indexy všech řádků v df_full
    group_to_indices = {}
    for idx, row in df_full.iterrows():
        key = (_key_txt(row.get("ingredience_sk","")), _key_txt(row.get("ingredience_rc","")))
        group_to_indices.setdefault(key, []).append(idx)

    header = [
        sg.Text("Datum", size=(12,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
        sg.Text("SK",    size=(6,1),  font=('Any', 10, 'bold'), pad=CELL_PAD),
        sg.Text("Reg.č.",size=(10,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
        sg.Text("Název", size=(36,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
        sg.Text("Množství", size=(12,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
        sg.Text("", size=(8,1), font=('Any', 10, 'bold'), pad=CELL_PAD),   # prázdný titulek pro jednotku
        sg.Text("Akce", size=(10,1), font=('Any', 10, 'bold'), pad=CELL_PAD),
    ]
    rows = [[*header]]

    btn_id = 0
    for _, r in g.iterrows():
        sk_k = _key_txt(r.get("_sk_key",""))
        rc_k = _key_txt(r.get("_rc_key",""))
        nazev = str(r.get("nazev","")).strip()
        jednotka = str(r.get("jednotka","")).strip()

        row_key = f"-BUY-G-{btn_id}-"
        vis_key = f"-GROW-{btn_id}-"
        btn_id += 1

        buy_map[row_key] = group_to_indices.get((sk_k, rc_k), [])
        rowkey_map[row_key] = vis_key

        row_widgets = [
            sg.Text(AGG_DATE_PLACEHOLDER, size=(12,1), pad=CELL_PAD),
            sg.Text(sk_k,                  size=(6,1),  pad=CELL_PAD),
            sg.Text(rc_k,                  size=(10,1), pad=CELL_PAD),
            sg.Text(nazev,                 size=(36,1), pad=CELL_PAD),
            sg.Text(str(r.get("potreba","")), size=(12,1), pad=CELL_PAD),
            sg.Text(jednotka,              size=(8,1),  pad=CELL_PAD),
            sg.Button("Koupeno", key=row_key, size=(10,1), pad=BTN_PAD),
        ]
        rows.append([sg.Column([row_widgets], key=vis_key, pad=(0,0), element_justification="left")])

    return rows, buy_map, rowkey_map


def _controls_row(agg_flag):
    # malý svislý pad → menší výška kontrol
    return [
        sg.Checkbox("Sčítat napříč daty", key="-AGG-", enable_events=True, default=bool(agg_flag), size=(22,1), pad=(0, 2)),
        sg.Button("Zavřít", key="-CLOSE-", size=(16,1), pad=(0, 2)),
    ]


def _create_results_window(df_full, col_k, agg_flag, location=None):
    rows_layout, buy_map, rowkey_map = _build_table_layout(df_full, col_k, aggregate=agg_flag)
    if rows_layout is None:
        return None, None, None

    # Column s minimálními pady (Qt verze nepodporuje element_padding / expand_x)
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
    lay = [[table_col],[controls_col]]

    # Použij poslední známou pozici (bez poskoku)
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


def _refresh_table_inplace(w, df_full, col_k, agg_flag):
    """
    In-place přestavba obsahu tabulky (při přepnutí agregace).
    Zachová pozici okna (žádný poskok).
    """
    new_rows_layout, buy_map, rowkey_map = _build_table_layout(df_full, col_k, aggregate=agg_flag)
    if new_rows_layout is None:
        return None, None, None

    pos = _safe_loc(w)
    try:
        w['-COL-'].update(layout=new_rows_layout)
        # udrž pozici okna beze změny
        if pos:
            try:
                w.move(pos[0], pos[1])
            except Exception:
                pass
        try:
            w['-AGG-'].update(value=bool(agg_flag))
        except Exception:
            pass
        _remember_pos(w)
        return w, buy_map, rowkey_map
    except Exception:
        # fallback – re-create na stejné pozici
        try:
            loc = pos or w.current_location()
        except Exception:
            loc = None
        _remember_pos(w)
        w.close()
        w, buy_map, rowkey_map = _create_results_window(df_full, col_k, agg_flag, location=loc or LAST_WIN_POS)
        return w, buy_map, rowkey_map


def open_results():
    """Okno výsledků: menší rozestupy, bez poskoku při klikání i při přepnutí agregace."""
    global LAST_WIN_POS
    try:
        df_full = pd.read_excel(OUTPUT_EXCEL).fillna("")
        df_full.columns = [str(c).strip() for c in df_full.columns]
        to_date_col(df_full, "datum")

        if df_full.empty:
            sg.popup("Výsledný Excel je prázdný – není co zobrazit.")
            print("[INFO] Výsledný Excel je prázdný – není co zobrazit.")
            return

        col_k = find_col(df_full, ["koupeno"])
        if col_k is None:
            df_full["koupeno"] = False
            col_k = "koupeno"

        _force_bool_col(df_full, col_k)
        _debug_dump(df_full, "START", col_k)

        agg_flag = False
        w, buy_map, rowkey_map = _create_results_window(df_full, col_k, agg_flag, location=LAST_WIN_POS)
        if w is None:
            sg.popup("Všechny položky jsou již koupené.")
            print("[INFO] Všechny položky jsou již koupené.")
            return
        _remember_pos(w)

        while True:
            ev, vals = w.read()
            _remember_pos(w)

            if ev in (sg.WINDOW_CLOSED, "-CLOSE-"):
                break

            if ev == "-AGG-":
                agg_flag = bool(vals.get("-AGG-", False))
                # In-place přestavba bez zavírání okna → bez poskoku
                w, buy_map, rowkey_map = _refresh_table_inplace(w, df_full, col_k, agg_flag)
                if w is None:
                    sg.popup("Všechny položky jsou již koupené.")
                    print("[INFO] Všechny položky jsou již koupené.")
                    break
                continue

            if isinstance(ev, str) and ev.startswith("-BUY-"):
                idx_list = buy_map.get(ev, [])
                if not idx_list and ev not in rowkey_map:
                    sg.popup_error(
                        "Chybné mapování indexů pro tlačítko. "
                        "Zkuste vypnout/zapnout agregaci. Pokud potíže přetrvají, "
                        "dejte vědět – zkusíme data znormalizovat."
                    )
                    print(f"[WARN] prázdný idx_list pro {ev}", flush=True)
                    continue

                # Označ vybrané řádky v DF (neagreg.) / všechny ve skupině (agreg.)
                if idx_list:
                    idx_list = sorted({int(i) for i in idx_list if pd.notna(i)})
                    try:
                        sks = df_full.loc[idx_list, "ingredience_sk"].map(_key_txt).tolist()
                        rcs = df_full.loc[idx_list, "ingredience_rc"].map(_key_txt).tolist()
                        print(f"[DEBUG] Klik '{ev}': zasahuje {len(idx_list)} řádků; "
                              f"unikátní páry: {sorted(set(zip(sks, rcs)))}", flush=True)
                    except Exception:
                        pass
                    df_full.loc[idx_list, col_k] = True
                else:
                    # agregovaný režim – logika koupení už přes buy_map
                    pass

                try:
                    _force_bool_col(df_full, col_k)
                    df_full.to_excel(OUTPUT_EXCEL, index=False)
                    _debug_dump(df_full, "AFTER_SAVE", col_k)
                except Exception as e:
                    tb = traceback.format_exc()
                    sg.popup_error(f"Chyba při ukládání do Excelu: {e}\n\n{tb}")
                    print(f"[ERROR] Chyba při ukládání do Excelu: {e}\n{tb}", flush=True)
                    continue

                # Pouze skryj dotčené vizuální řádky (žádný rebuild → žádný poskok)
                if not agg_flag:
                    for i in (idx_list or []):
                        vis_key = rowkey_map.get(i)
                        if vis_key and vis_key in w.AllKeysDict:
                            try:
                                w[vis_key].update(visible=False)
                            except Exception:
                                pass
                else:
                    vis_key = rowkey_map.get(ev)
                    if vis_key and vis_key in w.AllKeysDict:
                        try:
                            w[vis_key].update(visible=False)
                        except Exception:
                            pass

                # Pokud už nic nezbývá viditelné, zavři s hláškou
                any_visible = any(
                    isinstance(k, str) and (k.startswith("-ROW-") or k.startswith("-GROW-")) and
                    hasattr(w[k].Widget, "isVisible") and w[k].Widget.isVisible()
                    for k in w.AllKeysDict
                )
                if not any_visible:
                    sg.popup("Všechny položky jsou koupené. Okno bude zavřeno.")
                    print("[INFO] Všechny položky jsou koupené – zavírám okno.", flush=True)
                    break

            continue

        _remember_pos(w)
        w.close()
    except Exception as e:
        tb = traceback.format_exc()
        sg.popup_error(f"Chyba v okně výsledků:\n{e}\n\n{tb}")
        print(f"[ERROR] Chyba v okně výsledků: {e}\n{tb}", flush=True)
