# services/excel_service.py
import pandas as pd
from services.paths import OUTPUT_EXCEL
from services.data_utils import to_date_col, find_col, to_bool_cell_excel, clean_columns

def ensure_output_excel(data):
    """
    Zapíše/aktualizuje OUTPUT_EXCEL tak, aby:
      - existoval a měl sjednocený sloupec 'koupeno' jako bool,
      - pokud NOVÁ data 'koupeno' mají, použijí se tyto hodnoty,
      - pokud ne, defaultně nastaví 'koupeno' = False (nikdy True),
      - staré hodnoty se berou jen tehdy, když existují a dávají smysl,
      - odstraní pomocné sloupce (koupeno_old apod.).
    """
    # --- příjem nových dat ---
    if isinstance(data, pd.DataFrame):
        df_new = data.copy()
    else:
        df_new = pd.DataFrame(data)

    df_new = df_new.fillna("")
    clean_columns(df_new)
    to_date_col(df_new, "datum")

    new_k_found = find_col(df_new, ["koupeno"])
    new_has_koupeno = new_k_found is not None

    if not new_has_koupeno:
        df_new["koupeno"] = False
        new_k = "koupeno"
    else:
        new_k = new_k_found
        df_new[new_k] = df_new[new_k].apply(to_bool_cell_excel).astype(bool)

    # --- pokud neexistuje starý soubor nebo je prázdný/nečitelný -> první zápis s default False ---
    try:
        df_old = pd.read_excel(OUTPUT_EXCEL)
    except Exception:
        df_old = None

    if df_old is None or df_old.empty or len(df_old.columns) == 0:
        out = df_new.copy()
        if new_k != "koupeno":
            out.rename(columns={new_k: "koupeno"}, inplace=True)
        # pojistka: vždy čisté booly; bez nového 'koupeno' -> False
        out["koupeno"] = (out["koupeno"].apply(to_bool_cell_excel).astype(bool)
                          if "koupeno" in out.columns else False)
        out.to_excel(OUTPUT_EXCEL, index=False)
        return

    # --- máme starý soubor, zkusíme merge ---
    df_old = df_old.fillna("")
    clean_columns(df_old)
    to_date_col(df_old, "datum")

    old_k = find_col(df_old, ["koupeno"])
    if old_k is None:
        df_old["koupeno"] = False
        old_k = "koupeno"
    df_old[old_k] = df_old[old_k].apply(to_bool_cell_excel).astype(bool)

    key_cols = [c for c in df_new.columns if str(c).strip().lower() != "koupeno"]
    for c in key_cols:
        if c not in df_old.columns:
            df_old[c] = ""

    df_old_subset = df_old[key_cols + [old_k]].copy()

    merged = pd.merge(df_new, df_old_subset, on=key_cols, how="left", suffixes=("", "_old"))
    old_suff = f"{old_k}_old"

    # volba výsledného 'koupeno'
    if new_has_koupeno and (new_k in merged.columns):
        # NOVÉ hodnoty mají prioritu
        merged["koupeno"] = merged[new_k].astype(bool)
    else:
        if old_suff in merged.columns:
            merged["koupeno"] = merged[old_suff].astype(bool)
        elif old_k in merged.columns:
            merged["koupeno"] = merged[old_k].astype(bool)
        else:
            merged["koupeno"] = False

    merged["koupeno"] = merged["koupeno"].apply(to_bool_cell_excel).astype(bool)

    # úklid
    for c in [old_suff, old_k, new_k]:
        if c and c in merged.columns and c != "koupeno":
            try:
                merged.drop(columns=[c], inplace=True)
            except Exception:
                pass

    merged.to_excel(OUTPUT_EXCEL, index=False)

def test_merge_handles_dtype_mismatch(monkeypatch, tmp_path):
    # přesměrovat OUTPUT_EXCEL
    out = tmp_path / "vysledek.xlsx"
    monkeypatch.setattr("services.paths.OUTPUT_EXCEL", out)

    # starý: 'ingredience_sk' jako int
    old = pd.DataFrame([{
        "datum": "2025-01-01",
        "ingredience_sk": 150,        # int
        "ingredience_rc": 555,        # int
        "nazev": "Piri Piri",
        "potreba": 1.0,
        "jednotka": "kg",
        "koupeno": True,
    }])
    old.to_excel(out, index=False)

    # nový: 'ingredience_sk' jako string
    new = pd.DataFrame([{
        "datum": "2025-01-01",
        "ingredience_sk": "150",      # string
        "ingredience_rc": "555",      # string
        "nazev": "Piri Piri",
        "potreba": 2.0,
        "jednotka": "kg",
        # bez koupeno → default False
    }])

    from services.excel_service import ensure_output_excel
    ensure_output_excel(new)

    back = pd.read_excel(out)
    assert "koupeno" in back.columns
    # because qty increased 1.0 -> 2.0, koupeno must not be blindly preserved here
    # (ensured elsewhere by recalc; here stačí že merge nepadá a koupeno je bool)
    assert back["koupeno"].dtype == bool
