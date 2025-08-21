# services/excel_service.py
from __future__ import annotations
import pandas as pd
from services.paths import OUTPUT_EXCEL
from services.data_utils import to_date_col, find_col, to_bool_cell_excel, clean_columns

# --- interní normalizace klíčů ------------------------------------------------

def _safe_int(v):
    try:
        # umí i "150.0", "150,0"
        return int(float(str(v).replace(",", ".")))
    except Exception:
        return None

def _as_key_txt(v) -> str:
    """Stabilní textová reprezentace klíčů (SK/RC/název/jednotka)."""
    if v is None:
        return ""
    i = _safe_int(v)
    return str(i) if i is not None else str(v).strip()

KEY_COLS_CANON = ["datum", "ingredience_sk", "ingredience_rc", "nazev", "jednotka"]

def _normalize_key_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Zajistí stabilní typy klíčových sloupců pro merge:
      - datum -> date (bez času)
      - ostatní -> string pomocí _as_key_txt
    Nechává ostatní sloupce na pokoji (např. 'potreba' zůstává číselná).
    """
    if df is None or df.empty:
        return df
    # jistota: názvy sloupců jako stringy bez okrajových mezer
    clean_columns(df)

    # datum na date
    if "datum" in df.columns:
        to_date_col(df, "datum")

    # SK/RC/NÁZEV/JEDNOTKA jako stabilní text
    for c in ["ingredience_sk", "ingredience_rc", "nazev", "jednotka"]:
        if c in df.columns:
            df[c] = df[c].map(_as_key_txt).astype(str)
    return df

# --- hlavní funkce ------------------------------------------------------------

def ensure_output_excel(data):
    """
    Zapíše/aktualizuje OUTPUT_EXCEL tak, aby:
      - existoval a měl sjednocený sloupec 'koupeno' jako bool,
      - merge je robustní vůči typům (klíčové sloupce sjednoceny na text),
      - když starý soubor chybí/prázdný → default 'koupeno' = False,
      - pokud nová data obsahují 'koupeno', použijí se (po normalizaci na bool).
    """
    # ---- NOVÁ DATA -----------------------------------------------------------
    if isinstance(data, pd.DataFrame):
        df_new = data.copy()
    else:
        df_new = pd.DataFrame(data)

    df_new = df_new.fillna("")
    clean_columns(df_new)
    to_date_col(df_new, "datum")

    # normalizace koupeno v nových datech (pokud existuje)
    new_k = find_col(df_new, ["koupeno"])
    new_has_koupeno = new_k is not None
    if not new_has_koupeno:
        df_new["koupeno"] = False
        new_k = "koupeno"
    else:
        df_new[new_k] = df_new[new_k].apply(to_bool_cell_excel).astype(bool)

    # sjednotit KLÍČE na stabilní text
    df_new = _normalize_key_columns(df_new)

    # ---- STARÝ SOUBOR -------------------------------------------------------
    try:
        df_old = pd.read_excel(OUTPUT_EXCEL)
    except Exception:
        df_old = None

    if df_old is None or df_old.empty or len(df_old.columns) == 0:
        # první zápis – vždy 'koupeno' z nových (po normalizaci) nebo default False
        out = df_new.copy()
        if new_k != "koupeno":
            out.rename(columns={new_k: "koupeno"}, inplace=True)
        out["koupeno"] = out["koupeno"].apply(to_bool_cell_excel).astype(bool)
        out.to_excel(OUTPUT_EXCEL, index=False)
        return

    # máme starý soubor: připravíme ho
    df_old = df_old.fillna("")
    clean_columns(df_old)
    to_date_col(df_old, "datum")

    # zajistit koupeno ve starém
    old_k = find_col(df_old, ["koupeno"])
    if old_k is None:
        df_old["koupeno"] = False
        old_k = "koupeno"
    df_old[old_k] = df_old[old_k].apply(to_bool_cell_excel).astype(bool)

    # sjednotit KLÍČE na stabilní text (stejně jako v df_new)
    df_old = _normalize_key_columns(df_old)

    # ---- MERGE ---------------------------------------------------------------
    # klíče = všechny sloupce kromě 'koupeno' a ne-mergeové numeriky typu 'potreba'
    key_cols = [c for c in df_new.columns if c.lower() != "koupeno"]
    # zároveň se pojistíme, aby merge nebral kvantitativní sloupce – zůstávají jen identifikační
    # (držme se pouze kanonických klíčů, které reálně existují v df_new)
    canon = [c for c in KEY_COLS_CANON if c in df_new.columns]
    if canon:  # preferujeme kanon
        key_cols = canon

    # jistota: všechny klíče v df_old musí existovat, případně je doplníme prázdným stringem
    for c in key_cols:
        if c not in df_old.columns:
            df_old[c] = "" if c != "datum" else pd.NaT
    df_old_subset = df_old[key_cols + [old_k]].copy()

    # merge – teď už jsou typy klíčů sjednocené (string/date), nemá to padat
    merged = pd.merge(df_new, df_old_subset, on=key_cols, how="left", suffixes=("", "_old"))

    # zvol 'koupeno'
    old_suff = f"{old_k}_old"
    if new_has_koupeno and (new_k in merged.columns):
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
