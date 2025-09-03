# services/excel_service.py
from pathlib import Path
import pandas as pd
import services.paths as sp
from .data_utils import to_date_col, find_col, to_bool_cell_excel


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

def _normalize_keys_inplace(df: pd.DataFrame):
    """Sjednotí klíčové sloupce na stabilní typy/obsah."""
    if "datum" in df.columns:
        to_date_col(df, "datum")
    for c in ("ingredience_sk","ingredience_rc"):
        if c in df.columns:
            df[c] = df[c].map(_key_txt)  # jako text klíč
    for c in ("nazev","jednotka"):
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()

def ensure_output_excel(data):
    """Zpětná kompatibilita pro ingredience (bool sloupec 'koupeno')."""
    ensure_output_excel_generic(
       data=data,
       output_path=sp.OUTPUT_EXCEL,  # DŮLEŽITÉ: čte se vždy runtime hodnota (možná monkeypatchnutá)
       bool_col="koupeno",
   )
def ensure_output_excel_generic(data, output_path, bool_col="koupeno", *, writer_engine="openpyxl"):
    """
    Obecný zápis výsledku:
      - drží (a normalizuje) bool sloupec `bool_col`
      - merge se starým souborem, aby zůstaly zachované stavy
      - unifikuje klíče (datum, ingredience_sk/rc, nazev, jednotka) → bez dtype konfliktů
      - zapisuje POUZE přes xlsxwriter v 'with' bloku (žádné visící file-handles)
    """
    # --- příjem nových dat ---
    if isinstance(data, pd.DataFrame):
        df_new = data.copy()
    else:
        df_new = pd.DataFrame(data)

    df_new = df_new.fillna("")
    df_new.columns = [str(c).strip() for c in df_new.columns]
    _normalize_keys_inplace(df_new)

    # normalizace bool sloupce v nových datech
    new_k = find_col(df_new, [bool_col]) or bool_col
    if new_k not in df_new.columns:
        df_new[new_k] = False
    df_new[new_k] = df_new[new_k].map(to_bool_cell_excel).astype(bool)

    # --- když neexistuje starý soubor → rovnou zapiš (po přejmenování sloupce) ---
    try:
        df_old = pd.read_excel(output_path)
        has_old = True
    except Exception:
        has_old = False

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if not has_old:
        if new_k != bool_col:
            df_new = df_new.rename(columns={new_k: bool_col})
        df_new[bool_col] = df_new[bool_col].map(to_bool_cell_excel).astype(bool)
        _normalize_keys_inplace(df_new)

        # Bezpečný zápis – vždy přes xlsxwriter
        with pd.ExcelWriter(out, engine=writer_engine) as writer:
            df_new.to_excel(writer, index=False)
        return

    # --- máme stará data → merge ---
    df_old = df_old.fillna("")
    df_old.columns = [str(c).strip() for c in df_old.columns]
    _normalize_keys_inplace(df_old)

    old_k = find_col(df_old, [bool_col]) or bool_col
    if old_k not in df_old.columns:
        df_old[old_k] = False
    df_old[old_k] = df_old[old_k].map(to_bool_cell_excel).astype(bool)

    # KLÍČE: jen identifikační sloupce (NE množství apod.)
    preferred_keys = ["datum", "ingredience_sk", "ingredience_rc", "nazev", "jednotka"]
    present = [c for c in preferred_keys if c in df_new.columns]
    if present:
        key_cols = present
    else:
        # Fallback: všechno kromě bool sloupce a zjevně proměnlivých polí
        skip = {bool_col.lower(), "potreba", "mnozstvi", "množství"}
        key_cols = [c for c in df_new.columns if c.strip().lower() not in skip]

    # Doplň do df_old chybějící sloupce (kvůli merži)
    for c in key_cols:
        if c not in df_old.columns:
            df_old[c] = ""

    # stará podmnožina: klíče + starý bool
    df_old_subset = df_old[key_cols + [old_k]].copy()

    # merge bez dtype konfliktů (už jsou všechny klíče string/normalized)
    merged = pd.merge(df_new, df_old_subset, on=key_cols, how="left", suffixes=("", "_old"))

    # složení výsledného bool sloupce
    old_suff = f"{old_k}_old"
    if old_suff in merged.columns:
        merged[bool_col] = merged[old_suff]
    elif old_k in merged.columns:
        merged[bool_col] = merged[old_k]
    else:
        merged[bool_col] = False

    # případný bool z nových dat (jen OR – ponechá True)
    if new_k in merged.columns:
        merged[bool_col] = merged[bool_col] | merged[new_k]

    merged[bool_col] = merged[bool_col].map(to_bool_cell_excel).astype(bool)

    # úklid pomocných sloupců
    for c in [old_suff, old_k, new_k]:
        if c in merged.columns and c != bool_col:
            merged.drop(columns=[c], inplace=True)

    _normalize_keys_inplace(merged)

    # Bezpečný zápis – vždy přes xlsxwriter
    with pd.ExcelWriter(out, engine=writer_engine) as writer:
        merged.to_excel(writer, index=False)
