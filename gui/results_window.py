# gui/results_window.py
import traceback
import PySimpleGUIQt as sg
import pandas as pd
from datetime import date
from services.paths import OUTPUT_EXCEL
from services.data_utils import to_date_col, find_col, fmt_cz_date, to_bool_cell_excel

AGG_DATE_PLACEHOLDER = "XX-XX-XXXX"
CELL_PAD = (0, 5)
BTN_PAD  = ((0, 0), (-5,5))

def _safe_loc(win):
    try:
        x, y = win.current_location()
        return int(x), int(y)
    except Exception:
        return None

def _filter_unbought(d: pd.DataFrame, col_k: str) -> pd.DataFrame:
    return d.loc[~d[col_k].astype(bool)].copy()

def _build_table_layout(df_full: pd.DataFrame, col_k: str, aggregate: bool = False):
    buy_map = {}

    if not aggregate:
        d = _filter_unbought(df_full, col_k)
        if d.empty:
            return None, buy_map

        if "datum" in d.columns:
            sort_vals = pd.to_datetime(d["datum"], errors="coerce")
            d["_sort_datum"] = sort_vals
            d = d.sort_values("_sort_datum", na_position="last", kind="mergesort") \
                 .drop(columns=["_sort_datum"], errors="ignore")

        rows = [[
            sg.Text("Datum", size=(12,1), font=('Any', 10, 'bold')),
            sg.Text("SK",    size=(6,1),  font=('Any', 10, 'bold')),
            sg.Text("Reg.č.",size=(10,1), font=('Any', 10, 'bold')),
            sg.Text("Název", size=(36,1), font=('Any', 10, 'bold')),
            sg.Text("Množství", size=(12,1), font=('Any', 10, 'bold')),
            sg.Text("", size=(8,1), font=('Any', 10, 'bold')),
            sg.Text("Akce", size=(10,1), font=('Any', 10, 'bold')),
        ]]

        for i, r in d.iterrows():
            row_key = f"-BUY-{i}-"
            buy_map[row_key] = [i]
            rows.append([
                sg.Text(fmt_cz_date(r.get("datum","")), size=(12,1), pad=CELL_PAD),
                sg.Text(str(r.get("ingredience_sk","")),  size=(6,1),  pad=CELL_PAD),
                sg.Text(str(r.get("ingredience_rc","")),  size=(10,1), pad=CELL_PAD),
                sg.Text(str(r.get("nazev","")),           size=(36,1), pad=CELL_PAD),
                sg.Text(str(r.get("potreba","")),         size=(12,1), pad=CELL_PAD),
                sg.Text(str(r.get("jednotka","")),        size=(8,1),  pad=CELL_PAD),
                sg.Button("Koupeno", key=row_key, size=(10,1), pad=BTN_PAD),
            ])

        return rows, buy_map

    # aggregate=True
    d = _filter_unbought(df_full, col_k)
    if d.empty:
        return None, buy_map

    d["_num_pot"] = pd.to_numeric(d["potreba"], errors="coerce").fillna(0.0)
    grp_cols = ["ingredience_sk","ingredience_rc","nazev","jednotka"]
    g = d.groupby(grp_cols, as_index=False).agg(potreba=("_num_pot","sum"))
    g = g.sort_values(["ingredience_sk","ingredience_rc","nazev","jednotka"], kind="mergesort")

    # skupina -> indexy všech řádků v CELÉM df_full (napříč daty)
    group_to_indices = {}
    for idx, row in df_full.iterrows():
        key = (str(row.get("ingredience_sk","")).strip(),
               str(row.get("ingredience_rc","")).strip(),
               str(row.get("nazev","")).strip(),
               str(row.get("jednotka","")).strip())
        group_to_indices.setdefault(key, []).append(idx)

    rows = [[
        sg.Text("Datum", size=(12,1), font=('Any', 10, 'bold')),
        sg.Text("SK",    size=(6,1),  font=('Any', 10, 'bold')),
        sg.Text("Reg.č.",size=(10,1), font=('Any', 10, 'bold')),
        sg.Text("Název", size=(36,1), font=('Any', 10, 'bold')),
        sg.Text("Množství", size=(12,1), font=('Any', 10, 'bold')),
        sg.Text("", size=(8,1), font=('Any', 10, 'bold')),
        sg.Text("Akce", size=(10,1), font=('Any', 10, 'bold')),
    ]]

    btn_id = 0
    for _, r in g.iterrows():
        sk = str(r.get("ingredience_sk","")).strip()
        rc = str(r.get("ingredience_rc","")).strip()
        nz = str(r.get("nazev","")).strip()
        mj = str(r.get("jednotka","")).strip()
        row_key = f"-BUY-G-{btn_id}-"
        btn_id += 1
        buy_map[row_key] = group_to_indices.get((sk, rc, nz, mj), [])

        rows.append([
            sg.Text(AGG_DATE_PLACEHOLDER,             size=(12,1), pad=CELL_PAD),
            sg.Text(sk,                                size=(6,1),  pad=CELL_PAD),
            sg.Text(rc,                                size=(10,1), pad=CELL_PAD),
            sg.Text(nz,                                size=(36,1), pad=CELL_PAD),
            sg.Text(str(r.get("potreba","")),          size=(12,1), pad=CELL_PAD),
            sg.Text(mj,                                size=(8,1),  pad=CELL_PAD),
            sg.Button("Koupeno", key=row_key, size=(10,1), pad=BTN_PAD),
        ])
    return rows, buy_map

def _controls_row(agg_flag):
    return [
        sg.Checkbox("Sčítat napříč daty", key="-AGG-", enable_events=True, default=bool(agg_flag), size=(22,1)),
        sg.Button("Zavřít", key="-CLOSE-", size=(16,1))
    ]

def _create_results_window(df_full, col_k, agg_flag, location=None):
    rows_layout, buy_map = _build_table_layout(df_full, col_k, aggregate=agg_flag)
    if rows_layout is None:
        return None, None

    table_col = sg.Column(rows_layout, scrollable=True, size=(1000,560), key='-COL-')
    controls = _controls_row(agg_flag)
    controls_col = sg.Column([controls], element_justification='center', pad=(0,0))
    lay = [[table_col],[controls_col]]

    win_kwargs = dict(finalize=True, size=(1040, 640))
    try:
        if location is not None:
            x, y = int(location[0]), int(location[1])
            win_kwargs["location"] = (x, y)
    except Exception:
        pass

    w = sg.Window("Výsledek", lay, **win_kwargs)
    return w, buy_map

def _refresh_table_inplace(w, df_full, col_k, agg_flag):
    new_rows_layout, buy_map = _build_table_layout(df_full, col_k, aggregate=agg_flag)
    if new_rows_layout is None:
        return None, None
    pos = _safe_loc(w)
    try:
        w['-COL-'].update(layout=new_rows_layout)
        if pos:
            try:
                w.move(pos[0], pos[1])
            except Exception:
                pass
        try:
            w['-AGG-'].update(value=bool(agg_flag))
        except Exception:
            pass
        return w, buy_map
    except Exception:
        try:
            loc = pos or w.current_location()
        except Exception:
            loc = None
        w.close()
        w, buy_map = _create_results_window(df_full, col_k, agg_flag, location=loc)
        return w, buy_map

def open_results():
    """Okno výsledků s přepínáním agregace a značkou 'Koupeno'."""
    try:
        df_full = pd.read_excel(OUTPUT_EXCEL).fillna("")
        df_full.columns = df_full.columns.str.strip()
        to_date_col(df_full, "datum")

        col_k = find_col(df_full, ["koupeno"])
        if col_k is None:
            df_full["koupeno"] = False
            col_k = "koupeno"

        df_full[col_k] = df_full[col_k].apply(to_bool_cell_excel).astype(bool)

        agg_flag = False
        w, buy_map = _create_results_window(df_full, col_k, agg_flag)
        if w is None:
            sg.popup("Žádné položky k zobrazení (vše koupeno nebo prázdné).")
            return

        while True:
            ev, vals = w.read()
            if ev in (sg.WINDOW_CLOSED, "-CLOSE-"):
                break

            if ev == "-AGG-":
                agg_flag = bool(vals.get("-AGG-", False))
                w, buy_map = _refresh_table_inplace(w, df_full, col_k, agg_flag)
                if w is None:
                    sg.popup("Žádné položky k zobrazení (vše koupeno nebo prázdné).")
                    break
                continue

            if isinstance(ev, str) and ev.startswith("-BUY-"):
                idx_list = buy_map.get(ev, [])
                if not idx_list:
                    try:
                        idx = int(ev.split("-")[2])
                        idx_list = [idx]
                    except Exception:
                        sg.popup_error("Chybný index položky.")
                        continue

                for idx in idx_list:
                    df_full.at[idx, col_k] = True

                try:
                    df_full[col_k] = df_full[col_k].apply(to_bool_cell_excel).astype(bool)
                    df_full.to_excel(OUTPUT_EXCEL, index=False)
                except Exception as e:
                    tb = traceback.format_exc()
                    sg.popup_error(f"Chyba při ukládání do Excelu: {e}\n\n{tb}")
                    continue

                w, buy_map = _refresh_table_inplace(w, df_full, col_k, agg_flag)
                if w is None:
                    sg.popup("Všechny položky jsou koupené. Okno bude zavřeno.")
                    break
            continue

        w.close()
    except Exception as e:
        tb = traceback.format_exc()
        sg.popup_error(f"Chyba v okně výsledků:\n{e}\n\n{tb}")
