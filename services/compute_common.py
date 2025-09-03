# services/compute_common.py
from __future__ import annotations
import math
import pandas as pd
from datetime import date
from typing import Iterable

from services.data_utils import to_date_col, clean_columns, to_bool_cell_excel
from services.paths import OUTPUT_EXCEL

# ---------------------------- Tolerantní hledání sloupců ----------------------------

def _normalize_col_key(s: str) -> str:
    x = str(s or "").strip().lower()
    repl = {
        "á": "a", "č": "c", "ď": "d", "é": "e", "ě": "e", "í": "i", "ň": "n",
        "ó": "o", "ř": "r", "š": "s", "ť": "t", "ú": "u", "ů": "u", "ý": "y", "ž": "z",
    }
    x = "".join(repl.get(ch, ch) for ch in x)
    for ch in (" ", ".", "_", "-", "\u00A0"):
        x = x.replace(ch, "")
    return x

def find_col_loose(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    norm_map = {}
    for c in df.columns:
        norm_map[_normalize_col_key(c)] = c

    def _variants(cand: str):
        base = str(cand or "")
        yield base
        if base.endswith("."):
            yield base[:-1]
        else:
            yield base + "."
        yield base.replace(".", "")

    for cand in candidates or []:
        for v in _variants(cand):
            k = _normalize_col_key(v)
            if k in norm_map:
                return norm_map[k]
    return None

def find_col(df: pd.DataFrame, candidates: Iterable[str]):
    return find_col_loose(df, candidates)

# ---------------------------- Safe převody a klíče ----------------------------

def _safe_float(v):
    try:
        if v is None:
            return None
        f = float(v)
        if math.isnan(f):
            return None
        return f
    except Exception:
        try:
            s = str(v).strip().replace(",", ".")
            if s == "":
                return None
            f = float(s)
            if math.isnan(f):
                return None
            return f
        except Exception:
            return None

def _safe_int(v):
    f = _safe_float(v)
    if f is None:
        return None
    return int(f)

def _as_key_txt(v):
    if v is None:
        return ""
    i = _safe_int(v)
    return str(i) if i is not None else str(v).strip()

def _key_txt(v) -> str:
    if v is None:
        return ""
    i = _safe_int(v)
    return str(i) if i is not None else str(v).strip()

def _series_or_blank(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col] if col in df.columns else pd.Series([""] * len(df), index=df.index)

# ---------------------------- Receptury (normalizace) ----------------------------

def _prepare_recepty(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    clean_columns(df)

    p_reg = find_col(df, ["Reg. č.", "Reg. č", "Reg.č.", "reg. č.", "reg. č", "reg c", "reg.c"])
    p_sk  = find_col(df, ["SK", "sk"])

    c_reg = find_col(df, ["Reg. č..1", "Reg. č.1", "Reg.č..1", "reg. č..1", "reg. č.1", "Reg c 1", "Reg. c.1"])
    c_sk  = find_col(df, ["SK.1", "SK1", "sk.1", "sk1", "SK 1"])

    # ⬇️ NOVÉ – názvy
    p_nm  = find_col(df, ["Název", "Nazev"])                  # rodič (finál)
    c_nm  = find_col(df, ["Název 1.1", "Nazev 1.1", "Název", "Nazev"])

    qty   = find_col(df, ["Množství", "Mnozstvi", "množství", "mnozstvi", "qty"])
    unit  = find_col(df, ["MJ evidence", "MJ", "Jednotka", "jednotka"])

    for need, nm in [
        ("rodič Reg. č.", p_reg),
        ("rodič SK", p_sk),
        ("komponenta Reg. č..1", c_reg),
        ("komponenta SK.1", c_sk),
        ("množství", qty),
    ]:
        if nm is None:
            raise KeyError(f"Nebyl nalezen sloupec pro {need}")

    df["_P_REG"]   = df[p_reg].map(_as_key_txt)
    df["_P_SK"]    = df[p_sk].map(_as_key_txt)
    df["_C_REG"]   = df[c_reg].map(_as_key_txt)
    df["_C_SK"]    = df[c_sk].map(_as_key_txt)

    # ⬇️ NOVÉ – jména (bezpečně, strip, prázdné když není)
    df["_P_NAME"]  = df[p_nm].astype(str).str.strip() if p_nm is not None else ""
    df["_C_NAME"]  = df[c_nm].astype(str).str.strip() if c_nm is not None else ""

    df["_QTY"]     = pd.to_numeric(df[qty], errors="coerce").fillna(0.0)
    df["_UNIT"]    = (df[unit].astype(str).str.strip() if unit is not None else "")
    return df


# ---------------------------- Pomoc pro GUI „ready“ ----------------------------

def ready_semis_keys_from_vysledek(vysledek_df_or_path) -> set[tuple]:
    """
    Vrátí množinu klíčů (for_datum, for_polotovar_sk, for_polotovar_rc),
    pro které jsou všechny ingredience koupené (koupeno==True).
    Parametr může být DataFrame nebo cesta k souboru.
    """
    import pandas as pd
    if isinstance(vysledek_df_or_path, pd.DataFrame):
        ing = vysledek_df_or_path.copy()
    else:
        try:
            ing = pd.read_excel(vysledek_df_or_path)
        except Exception:
            return set()

    if ing.empty:
        return set()

    clean_columns(ing)

    needed = {"for_datum", "for_polotovar_sk", "for_polotovar_rc", "koupeno"}
    if not needed.issubset(set(ing.columns)):
        return set()

    to_date_col(ing, "for_datum")
    ing["koupeno"] = ing["koupeno"].apply(to_bool_cell_excel).astype(bool)

    grouped = ing.groupby(["for_datum", "for_polotovar_sk", "for_polotovar_rc"], dropna=False)["koupeno"]
    ready = set()
    for key, s in grouped:
        if len(s) > 0 and bool(s.fillna(False).all()):
            ready.add(key)
    return ready
