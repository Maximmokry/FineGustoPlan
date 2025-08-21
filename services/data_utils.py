# services/data_utils.py
import pandas as pd
from datetime import date
import math

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

def to_bool_cell_excel(x):
    """
    Převod na čisté bool bez jazykových slov:
    - True/False zůstává
    - 1/0 (i jako text) -> True/False
    - prázdno/None/NaN/text -> False
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
    s = str(x).strip()
    if s == "":
        return False
    try:
        return float(s.replace(",", ".")) != 0.0
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
        f = float(v)
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
