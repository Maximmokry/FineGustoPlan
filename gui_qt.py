# gui_qt_safe.py
import traceback
from pathlib import Path
import pandas as pd
import PySimpleGUIQt as sg
import main
from datetime import date
import math

OUTPUT_EXCEL = Path("vysledek.xlsx")
AGG_DATE_PLACEHOLDER = "XX-XX-XXXX"  # datum v agregovaném režimu
# --- vizuální zarovnání buněk v řádku tabulky ---
CELL_PAD = (0, 5)                 # pro všechny Text buňky
BTN_PAD  = ((0, 0), (-5,5))       # pro Button – zvedne ho cca o 6 px (případně uprav na -4 / -8)

# ===================== Normalizace na čistý bool (bez jazyků) =====================

def _to_bool_cell_excel(x):
    """
    Převod libovolné hodnoty na bool bez jazykových slov:
    - True/False z Excelu zůstává
    - 1/0 (i číslem) -> True/False
    - prázdno/None/NaN -> False
    - jakýkoli jiný text -> False (nepřekládáme 'PRAVDA' apod.)
    """
    if x is None:
        return False
    if isinstance(x, bool):
        return x
    if isinstance(x, float):
        if math.isnan(x):
            return False
        return x != 0.0
    if isinstance(x, int):
        return x != 0
    # stringy: zkusíme numeriku; jinak False
    s = str(x).strip()
    if s == "":
        return False
    try:
        # povolíme i "1", "0" v textu
        return float(s.replace(",", ".")) != 0.0
    except Exception:
        return False

def _normalize_koupeno_column(df, prefer_name="koupeno"):
    """
    Zajistí existenci a bool obsah sloupce 'koupeno' (jméno ignoruje case/mezery).
    Vrací skutečné jméno sloupce (case-preserved) po sjednocení.
    """
    real = None
    cols = {c.strip().lower(): c for c in df.columns}
    if prefer_name in ["koupeno"]:
        real = cols.get("koupeno")
    if real is None:
        # sloupec chybí -> založíme
        df["koupeno"] = False
        real = "koupeno"

    # převeď na čisté booly
    df[real] = df[real].apply(_to_bool_cell_excel).astype(bool)
    return real

# ===================== Pomocné funkce =====================

def _find_col(df, candidates):
    cols = {c.strip().lower(): c for c in df.columns}
    for cand in candidates:
        key = cand.strip().lower()
        if key in cols:
            return cols[key]
    return None

def _to_date_col(df, col_name="datum"):
    if col_name in df.columns:
        df[col_name] = pd.to_datetime(df[col_name], errors="coerce").dt.date

def _safe_loc(win):
    """Bezpečně vrátí (x, y) pozici okna, nebo None."""
    try:
        x, y = win.current_location()
        return int(x), int(y)
    except Exception:
        return None

def _fmt_cz_date(v):
    try:
        if isinstance(v, date):
            return f"{v:%d.%m.%Y}"
    except Exception:
        pass
    try:
        dt = pd.to_datetime(v, errors="coerce")
        if pd.isna(dt):
            return ""
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return str(v) if v is not None else ""

def _refresh_table_inplace(w, df_full, col_k, agg_flag):
    """
    Překreslí obsah sloupce '-COL-' BEZ zavření okna.
    Vrací (w, buy_map): w = stejný (nebo výjimečně nové okno při fallbacku), buy_map = nová mapa tlačítek.
    Když už není co zobrazit, vrátí (None, None).
    """
    new_rows_layout, buy_map = _build_table_layout(df_full, col_k, aggregate=agg_flag)
    if new_rows_layout is None:
        return None, None

    # zachovej přesně stejnou pozici okna i po update layoutu
    pos = _safe_loc(w)
    try:
        w['-COL-'].update(layout=new_rows_layout)
        if pos:
            try:
                w.move(pos[0], pos[1])   # ← klíčový trik proti „poskoku“
            except Exception:
                pass
        try:
            w['-AGG-'].update(value=bool(agg_flag))
        except Exception:
            pass
        return w, buy_map
    except Exception:
        # fallback – znovu vytvořit okno přesně na stejné pozici
        try:
            loc = pos or w.current_location()
        except Exception:
            loc = None
        w.close()
        w, buy_map = _create_results_window(df_full, col_k, agg_flag, location=loc)
        return w, buy_map

# ===================== Excel I/O + sjednocení =====================

def ensure_output_excel(data):
    """Zachová 'koupeno'; sjednotí datum a 'koupeno' na správné typy a zapíše jako bool."""
    # ---- příjem nových dat ----
    if isinstance(data, pd.DataFrame):
        df_new = data.copy()
    else:
        try:
            df_new = pd.DataFrame(data)
        except Exception:
            return

    df_new = df_new.fillna("")
    df_new.columns = df_new.columns.str.strip()
    _to_date_col(df_new, "datum")

    # normalizovat 'koupeno' v nových datech
    new_k = _find_col(df_new, ["koupeno"])
    if new_k is None:
        df_new["koupeno"] = False
        new_k = "koupeno"
    df_new[new_k] = df_new[new_k].apply(_to_bool_cell_excel).astype(bool)

    # ---- pokud neexistuje starý soubor ----
    if not OUTPUT_EXCEL.exists():
        try:
            if new_k != "koupeno":
                df_new.rename(columns={new_k: "koupeno"}, inplace=True)
            df_new["koupeno"] = df_new["koupeno"].apply(_to_bool_cell_excel).astype(bool)
            df_new.to_excel(OUTPUT_EXCEL, index=False)
        except Exception:
            pass
        return

    # ---- načtení starého souboru ----
    try:
        df_old = pd.read_excel(OUTPUT_EXCEL)
    except Exception:
        # fallback: zapiš nové
        try:
            if new_k != "koupeno":
                df_new.rename(columns={new_k: "koupeno"}, inplace=True)
            df_new["koupeno"] = df_new["koupeno"].apply(_to_bool_cell_excel).astype(bool)
            df_new.to_excel(OUTPUT_EXCEL, index=False)
        except Exception:
            pass
        return

    df_old = df_old.fillna("")
    df_old.columns = df_old.columns.str.strip()
    _to_date_col(df_old, "datum")

    old_k = _find_col(df_old, ["koupeno"])
    if old_k is None:
        df_old["koupeno"] = False
        old_k = "koupeno"
    df_old[old_k] = df_old[old_k].apply(_to_bool_cell_excel).astype(bool)

    # ---- sjednocení sloupců (kromě 'koupeno') ----
    key_cols = [c for c in df_new.columns if c.strip().lower() != "koupeno"]
    for c in key_cols:
        if c not in df_old.columns:
            df_old[c] = ""

    df_old_subset = df_old[key_cols + [old_k]].copy()

    # ---- merge ----
    try:
        merged = pd.merge(df_new, df_old_subset, on=key_cols, how="left", suffixes=("", "_old"))
    except Exception:
        try:
            if new_k != "koupeno":
                df_new.rename(columns={new_k: "koupeno"}, inplace=True)
            df_new["koupeno"] = df_new["koupeno"].apply(_to_bool_cell_excel).astype(bool)
            df_new.to_excel(OUTPUT_EXCEL, index=False)
        except Exception:
            pass
        return

    # ---- složení výsledného 'koupeno' ----
    old_suff = f"{old_k}_old"  # typicky "koupeno_old"
    if old_suff in merged.columns:
        merged["koupeno"] = merged[old_suff]
    elif old_k in merged.columns:
        merged["koupeno"] = merged[old_k]
    else:
        merged["koupeno"] = False

    if new_k in merged.columns:
        # nová hodnota jen tam, kde ve staré nic nebylo (ale máme už pouze bool -> použijeme OR)
        merged["koupeno"] = merged["koupeno"] | merged[new_k]

    # ---- normalizace a úklid ----
    merged["koupeno"] = merged["koupeno"].apply(_to_bool_cell_excel).astype(bool)
    for c in [old_suff, old_k, new_k]:
        if c and c in merged.columns and c != "koupeno":
            try:
                merged.drop(columns=[c], inplace=True)
            except Exception:
                pass

    # ---- zápis ----
    try:
        merged.to_excel(OUTPUT_EXCEL, index=False)
    except Exception:
        try:
            if new_k != "koupeno":
                df_new.rename(columns={new_k: "koupeno"}, inplace=True)
            df_new["koupeno"] = df_new["koupeno"].apply(_to_bool_cell_excel).astype(bool)
            df_new.to_excel(OUTPUT_EXCEL, index=False)
        except Exception:
            pass

# ===================== Hlavní okno (větší, zarovnaná tlačítka) =====================

header_col = sg.Column(
    [[sg.Text("FineGusto plánovač", font=('Any', 16, 'bold'))]],
    element_justification='center', pad=(0, 10)
)
btn_row_col = sg.Column(
    [[sg.Button("Spočítat", key="-RUN-", size=(18,2)),
      sg.Button("Konec", size=(18,2))]],
    element_justification='center', pad=(0, 0)
)
layout = [[header_col], [btn_row_col]]
window = sg.Window("FineGusto", layout, finalize=True, size=(720, 280))

# ===================== Okno výsledků =====================

def _filter_unbought(d, col_k):
    # Sloupec je bool -> vyber jen NEkoupené
    return d.loc[~d[col_k]].copy()

def _build_table_layout(df_full, col_k, aggregate=False):
    """
    Vrací (rows_layout, buy_map).
    - aggregate=False: po dnech (seřazeno vzestupně dle data, datum dd.mm.yyyy)
    - aggregate=True : součet napříč daty; datum = AGG_DATE_PLACEHOLDER;
                       klik na Koupeno označí všechny výskyty napříč daty
    """
    buy_map = {}

    if not aggregate:
        d = _filter_unbought(df_full, col_k)
        if d.empty:
            return None, buy_map

        # řazení dle data
        if "datum" in d.columns:
            sort_vals = pd.to_datetime(d["datum"], errors="coerce")
            d["_sort_datum"] = sort_vals
            d = d.sort_values("_sort_datum", na_position="last", kind="mergesort").drop(columns=["_sort_datum"], errors="ignore")

        # hlavička
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
                sg.Text(_fmt_cz_date(r.get("datum","")), size=(12,1), pad=CELL_PAD),
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
    grp_cols = ["ingredience_sk", "ingredience_rc", "nazev", "jednotka"]
    g = d.groupby(grp_cols, as_index=False).agg(potreba=("_num_pot", "sum"))
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
    """Řádka ovládacích prvků – vytváří se vždy nově po přestavbě okna."""
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

    # ✅ jen když máme platnou dvojici (x, y), tak ji předáme
    win_kwargs = dict(finalize=True, size=(1040, 640))
    try:
        if location is not None:
            x, y = int(location[0]), int(location[1])
            win_kwargs["location"] = (x, y)
    except Exception:
        pass

    w = sg.Window("Výsledek", lay, **win_kwargs)
    return w, buy_map

def open_results():
    """Okno výsledků s přepínáním agregace (oběma směry) a unifikovanými tlačítky."""
    try:
        df_full = pd.read_excel(OUTPUT_EXCEL).fillna("")
        df_full.columns = df_full.columns.str.strip()
        _to_date_col(df_full, "datum")

        col_k = _find_col(df_full, ["koupeno"])
        if col_k is None:
            df_full["koupeno"] = False
            col_k = "koupeno"

        # sjednotit na bool (žádná jazyková slova se neřeší)
        df_full[col_k] = df_full[col_k].apply(_to_bool_cell_excel).astype(bool)

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
                    # uložit jako čisté booly -> v Excelu logické (zobrazí se PRAVDA/NEPRAVDA dle jazyka)
                    df_full[col_k] = df_full[col_k].apply(_to_bool_cell_excel).astype(bool)
                    df_full.to_excel(OUTPUT_EXCEL, index=False)
                except Exception as e:
                    tb = traceback.format_exc()
                    sg.popup_error(f"Chyba při ukládání do Excelu: {e}\n\n{tb}")
                    continue

                # 👉 bez zavírání okna:
                w, buy_map = _refresh_table_inplace(w, df_full, col_k, agg_flag)
                if w is None:
                    sg.popup("Všechny položky jsou koupené. Okno bude zavřeno.")
                    break
            continue

        w.close()
    except Exception as e:
        tb = traceback.format_exc()
        sg.popup_error(f"Chyba v results window:\n{e}\n\n{tb}")

# ===================== Hlavní smyčka =====================

header_col = sg.Column(
    [[sg.Text("FineGusto plánovač", font=('Any', 16, 'bold'))]],
    element_justification='center', pad=(0, 10)
)
btn_row_col = sg.Column(
    [[sg.Button("Spočítat", key="-RUN-", size=(18,2)),
      sg.Button("Konec", size=(18,2))]],
    element_justification='center', pad=(0, 0)
)
layout = [[header_col], [btn_row_col]]
window = sg.Window("FineGusto", layout, finalize=True, size=(720, 280))

while True:
    try:
        ev, vals = window.read()
        if ev in (sg.WINDOW_CLOSED, "Konec"):
            break
        if ev == "-RUN-":
            try:
                data = main.main()
            except Exception as e:
                tb = traceback.format_exc()
                sg.popup_error(f"Chyba při spuštění main.main(): {e}\n\n{tb}")
                continue
            ensure_output_excel(data)
            open_results()
    except Exception as e:
        tb = traceback.format_exc()
        sg.popup_error(f"Chyba v hlavním okně:\n{e}\n\n{tb}")

window.close()
