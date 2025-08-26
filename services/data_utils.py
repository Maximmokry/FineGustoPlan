# services/data_utils.py
import pandas as pd
from datetime import date
import math
import unicodedata

def _norm_str(x: str) -> str:
    # odstraň diakritiku a sjednoť case/trim
    s = unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode("ascii")
    return s.strip().lower()

def find_col(df: pd.DataFrame, candidates):
    cols = {str(c).strip().lower(): c for c in df.columns}
    for cand in candidates:
        key = cand.strip().lower()
        if key in cols:
            return cols[key]
    return None

def to_date_col(df: pd.DataFrame, col_name="datum"):
    if col_name in df.columns:
        df[col_name] = pd.to_datetime(df[col_name], errors="coerce").dt.date

def fmt_cz_date(v):
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

def to_bool_cell_excel(v) -> bool:
    """
    Normalizace různých vstupů na bool pro Excel zápis/čtení.
    Akceptuje True/False, 1/0, "1"/"0", "true"/"false", "yes"/"no",
    české "ano"/"ne", i zaškrtnutí typu "x", "✓", "✔".
    Prázdné / NaN -> False.
    """
    # Přímé bool
    if isinstance(v, bool):
        return v

    # None / NaN -> False
    if v is None:
        return False
    if isinstance(v, float) and math.isnan(v):
        return False
    try:
        # pandas NaT / NaN-like
        if pd.isna(v):
            return False
    except Exception:
        pass

    # Čísla
    if isinstance(v, (int, float)):
        return v != 0

    # Řetězce
    s = _norm_str(v)
    if s in {"true", "t", "yes", "pravda","y", "ano", "a", "1", "x", "✓", "✔"}:
        return True
    if s in {"false", "f", "no","nepravda" "n", "ne", "0", "", "-"}:
        return False

    # Zkusíme číselný string ("0", "0.0", "1,0", ...)
    try:
        sval = s.replace(",", ".")
        return float(sval) != 0.0
    except Exception:
        return False
# ---- NOVÉ: bezpečné čištění názvů sloupců a normalizace čísel na string ----

def clean_columns(df: pd.DataFrame):
    """Ujisti se, že názvy sloupců jsou stringy bez mezer kolem."""
    df.columns = [str(c).strip() for c in df.columns]

def norm_num_to_str(v) -> str:
    """
    150 -> "150", 150.0 -> "150", "150.0" -> "150"
    NaN/None -> ""
    ostatní -> ořezaný string
    """
    try:
        # akceptuj i českou čárku
        s = str(v).replace(",", ".")
        f = float(s)
        if math.isnan(f):
            return ""
        if f.is_integer():
            return str(int(f))
        return str(f).strip()
    except Exception:
        if v is None:
            return ""
        return str(v).strip()

def normalize_key_series(s: pd.Series) -> pd.Series:
    """Vektorová normalizace pro klíčové sloupce (SK/RC apod.)."""
    return s.map(norm_num_to_str)
