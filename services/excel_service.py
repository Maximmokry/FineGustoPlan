# services/excel_service.py
import pandas as pd
from services.paths import OUTPUT_EXCEL
from services.data_utils import to_date_col, find_col, to_bool_cell_excel

def ensure_output_excel(data):
    """
    Zapíše/aktualizuje OUTPUT_EXCEL tak, aby:
      - existoval a měl sjednocený sloupec 'koupeno' jako bool,
      - pokud NOVÁ data skutečně obsahují 'koupeno', tato hodnota má PŘEDNOST,
      - pokud nová data 'koupeno' NEobsahují, zachová se stará hodnota,
      - odstraní pomocné sloupce (koupeno_old apod.).
    """
    # --- příjem nových dat ---
    if isinstance(data, pd.DataFrame):
        df_new = data.copy()
    else:
        df_new = pd.DataFrame(data)

    df_new = df_new.fillna("")
    df_new.columns = df_new.columns.str.strip()
    to_date_col(df_new, "datum")

    # ZJISTIT, zda NOVÁ data opravdu 'koupeno' měla
    new_k_found = find_col(df_new, ["koupeno"])
    new_has_koupeno = new_k_found is not None

    # Zajistit kolonu 'koupeno' i když chybí (default False),
    # ale později při mergi ji neupřednostnit, pokud původně nebyla.
    if not new_has_koupeno:
        df_new["koupeno"] = False
        new_k = "koupeno"
    else:
        new_k = new_k_found

    df_new[new_k] = df_new[new_k].apply(to_bool_cell_excel).astype(bool)

    # --- první zápis ---
    if not OUTPUT_EXCEL.exists():
        if new_k != "koupeno":
            df_new.rename(columns={new_k: "koupeno"}, inplace=True)
        df_new["koupeno"] = df_new["koupeno"].apply(to_bool_cell_excel).astype(bool)
        df_new.to_excel(OUTPUT_EXCEL, index=False)
        return

    # --- načtení starého ---
    try:
        df_old = pd.read_excel(OUTPUT_EXCEL)
    except Exception:
        if new_k != "koupeno":
            df_new.rename(columns={new_k: "koupeno"}, inplace=True)
        df_new["koupeno"] = df_new["koupeno"].apply(to_bool_cell_excel).astype(bool)
        df_new.to_excel(OUTPUT_EXCEL, index=False)
        return

    df_old = df_old.fillna("")
    df_old.columns = df_old.columns.str.strip()
    to_date_col(df_old, "datum")

    old_k = find_col(df_old, ["koupeno"])
    if old_k is None:
        df_old["koupeno"] = False
        old_k = "koupeno"
    df_old[old_k] = df_old[old_k].apply(to_bool_cell_excel).astype(bool)

    # --- sjednocení sloupců (kromě 'koupeno') ---
    key_cols = [c for c in df_new.columns if c.strip().lower() != "koupeno"]
    for c in key_cols:
        if c not in df_old.columns:
            df_old[c] = ""

    df_old_subset = df_old[key_cols + [old_k]].copy()

    # --- merge ---
    merged = pd.merge(df_new, df_old_subset, on=key_cols, how="left", suffixes=("", "_old"))
    old_suff = f"{old_k}_old"

    # --- volba výsledného 'koupeno' ---
    if new_has_koupeno and (new_k in merged.columns):
        # nová data měla 'koupeno' -> mají přednost
        merged["koupeno"] = merged[new_k].astype(bool)
    else:
        # nová data 'koupeno' neměla -> drž se staré hodnoty
        if old_suff in merged.columns:
            merged["koupeno"] = merged[old_suff].astype(bool)
        elif old_k in merged.columns:
            merged["koupeno"] = merged[old_k].astype(bool)
        else:
            merged["koupeno"] = False

    merged["koupeno"] = merged["koupeno"].apply(to_bool_cell_excel).astype(bool)

    # --- úklid ---
    for c in [old_suff, old_k, new_k]:
        if c and c in merged.columns and c != "koupeno":
            try:
                merged.drop(columns=[c], inplace=True)
            except Exception:
                pass

    merged.to_excel(OUTPUT_EXCEL, index=False)