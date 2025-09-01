# services/ingredients_logic.py
from __future__ import annotations
import pandas as pd
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional, Tuple

from services.paths import RECEPTY_FILE, PLAN_FILE, OUTPUT_EXCEL
from services.data_utils import to_date_col, clean_columns, to_bool_cell_excel
from services.excel_service import ensure_output_excel_generic

from services.compute_common import (
    find_col, _prepare_recepty, _safe_int, _safe_float,
    _as_key_txt, _key_txt
)

# ---------------------------- Načtení ----------------------------

def nacti_data():
    recepty = pd.read_excel(RECEPTY_FILE, sheet_name="HEO - Kusovníkové vazby platné ")
    plan = pd.read_excel(PLAN_FILE)
    clean_columns(recepty)
    clean_columns(plan)
    if "datum" in plan.columns:
        to_date_col(plan, "datum")
    return recepty, plan

# ---------------------------- Rozklad s kontextem polotovaru ----------------------------

def _rozloz_vyrobek_ctx(
    vyrobek_id: str,
    mnozstvi: float,
    recepty: pd.DataFrame,
    datum,
    ctx_semis: Optional[Tuple[str, str, str]] = None,  # (SK, RC, NAME) polotovaru
    navstiveno=None
):
    """
    Vrací list ingrediencí (raw) s VAZBOU na polotovar (for_*),
    pokud rozklad probíhá „pod“ nějakým SK300.
    """
    if navstiveno is None:
        navstiveno = set()
    out = []

    if vyrobek_id in navstiveno:
        return out
    navstiveno.add(vyrobek_id)

    vyrobek_sk, vyrobek_reg_c = vyrobek_id.split("-", 1)
    vyrobek_sk = _as_key_txt(vyrobek_sk)
    vyrobek_reg_c = _as_key_txt(vyrobek_reg_c)

    if "_P_REG" not in recepty.columns or "_P_SK" not in recepty.columns:
        recepty = _prepare_recepty(recepty)

    podrecept = recepty[(recepty["_P_REG"] == vyrobek_reg_c) & (recepty["_P_SK"] == vyrobek_sk)]

    if podrecept.empty:
        # list položka (raw) – přiřaď ke kontextovému polotovaru, pokud nějaký je
        out.append({
            "datum": datum,
            "vyrobek": f"{vyrobek_sk}-{vyrobek_reg_c}",
            "nazev": f"{vyrobek_sk}-{vyrobek_reg_c}",
            "ingredience_rc": vyrobek_reg_c,
            "ingredience_sk": vyrobek_sk,
            "potreba": mnozstvi,
            "jednotka": None,
            "for_datum": datum if ctx_semis else None,
            "for_polotovar_sk": ctx_semis[0] if ctx_semis else None,
            "for_polotovar_rc": ctx_semis[1] if ctx_semis else None,
            "for_polotovar_nazev": ctx_semis[2] if ctx_semis else None,
        })
        return out

    for _, r in podrecept.iterrows():
        komponenta_reg_c = r["_C_REG"]
        komponenta_nazev = str(r["_C_NAME"] or "").strip()
        mnozstvi_na_kus  = float(r["_QTY"] or 0)
        jednotka         = r["_UNIT"]
        komponenta_sk    = r["_C_SK"]
        komponenta_id    = f"{komponenta_sk}-{komponenta_reg_c}"
        celkem           = mnozstvi * mnozstvi_na_kus

        # pokud je to polotovar (SK300), nastav nový kontext a rozlož dál
        if _safe_int(komponenta_sk) == 300 and _safe_int(komponenta_reg_c) is not None:
            new_ctx = (str(komponenta_sk), str(_safe_int(komponenta_reg_c)), komponenta_nazev)
            out.extend(_rozloz_vyrobek_ctx(komponenta_id, celkem, recepty, datum, new_ctx, navstiveno))
        # pokud je to finál (400) – pokračuj bez kontextu polotovaru
        elif _safe_int(komponenta_sk) == 400:
            out.extend(_rozloz_vyrobek_ctx(komponenta_id, celkem, recepty, datum, None, navstiveno))
        else:
            # raw ingredience -> přiřaď ke stávajícímu polotovaru (pokud nějaký je)
            out.append({
                "datum": datum,
                "vyrobek": f"{vyrobek_sk}-{vyrobek_reg_c}",
                "nazev": komponenta_nazev,
                "ingredience_rc": komponenta_reg_c,
                "ingredience_sk": komponenta_sk,
                "potreba": celkem,
                "jednotka": jednotka,
                "for_datum": datum if ctx_semis else None,
                "for_polotovar_sk": ctx_semis[0] if ctx_semis else None,
                "for_polotovar_rc": ctx_semis[1] if ctx_semis else None,
                "for_polotovar_nazev": ctx_semis[2] if ctx_semis else None,
            })
    return out

# ---------------------------- Výpočet ingrediencí ----------------------------

def spocitej_potrebne_ingredience(recepty: pd.DataFrame, plan: pd.DataFrame) -> pd.DataFrame:
    recepty = _prepare_recepty(recepty)
    clean_columns(plan)

    COL_PLAN_REG  = find_col(plan, ["reg.č", "reg c", "reg.c", "regc", "reg č", "reg"])
    COL_PLAN_QTY  = find_col(plan, ["mnozstvi", "množství", "qty", "mnozství"])
    COL_PLAN_DATE = find_col(plan, ["datum", "date", "dat", "DATUM"])

    vysledky = []
    for _, row in plan.iterrows():
        final_reg = row.get(COL_PLAN_REG)
        if final_reg is None:
            continue

        vyrobek_id = f"400-{_safe_int(final_reg)}"
        mnozstvi = _safe_float(row.get(COL_PLAN_QTY)) or 0.0
        datum = row.get(COL_PLAN_DATE, None)

        vysledky.extend(_rozloz_vyrobek_ctx(vyrobek_id, mnozstvi, recepty, datum))

    df = pd.DataFrame(vysledky)
    if df.empty:
        return pd.DataFrame(columns=[
            "datum","ingredience_sk","ingredience_rc","nazev","potreba","jednotka","koupeno",
            "for_datum","for_polotovar_sk","for_polotovar_rc","for_polotovar_nazev"
        ])

    to_date_col(df, "datum")
    if "for_datum" in df.columns:
        to_date_col(df, "for_datum")

    # agregace po ingredienci + zachování for_* (pokud existují, agregujeme nezávisle)
    grp_cols = ["datum","ingredience_sk","ingredience_rc","nazev","jednotka","for_datum","for_polotovar_sk","for_polotovar_rc","for_polotovar_nazev"]
    present_grp_cols = [c for c in grp_cols if c in df.columns]
    df["_pot"] = pd.to_numeric(df["potreba"], errors="coerce").fillna(0.0)
    df = df.groupby(present_grp_cols, as_index=False, dropna=False)["_pot"].sum().rename(columns={"_pot":"potreba"})

    # pořadí sloupců
    cols = ["datum","ingredience_sk","ingredience_rc","nazev","potreba","jednotka",
            "for_datum","for_polotovar_sk","for_polotovar_rc","for_polotovar_nazev"]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]

# ---------------------------- Zachování 'koupeno' ----------------------------

def _recalculate_koupeno_against_previous(df_new: pd.DataFrame) -> pd.DataFrame:
    SCALE = 6
    def _qty_to_int_micro(v) -> int:
        try:
            s = str(v).strip().replace(",", ".")
            if s == "" or s.lower() in {"nan", "none"}:
                return 0
            d = Decimal(s)
        except (InvalidOperation, Exception):
            return 0
        q = d.quantize(Decimal(10) ** (-SCALE), rounding=ROUND_HALF_UP)
        return int((q * (Decimal(10) ** SCALE)).to_integral_value(rounding=ROUND_HALF_UP))

    df_new = df_new.copy()
    df_new.columns = [str(c).strip() for c in df_new.columns]
    to_date_col(df_new, "datum")
    if "for_datum" in df_new.columns:
        to_date_col(df_new, "for_datum")
    df_new["koupeno"] = False

    df_new["__sk"]    = df_new.get("ingredience_sk", "").map(_key_txt)
    df_new["__rc"]    = df_new.get("ingredience_rc", "").map(_key_txt)
    df_new["__qty_i"] = df_new.get("potreba", 0).map(_qty_to_int_micro)

    try:
        old = pd.read_excel(OUTPUT_EXCEL)
    except Exception:
        return df_new.drop(columns=["__sk", "__rc", "__qty_i"], errors="ignore")

    old = old.fillna("")
    old.columns = [str(c).strip() for c in old.columns]
    to_date_col(old, "datum")
    if "for_datum" in old.columns:
        to_date_col(old, "for_datum")

    for col in ("ingredience_sk","ingredience_rc","koupeno"):
        if col not in old.columns:
            old[col] = "" if col != "koupeno" else False

    old["koupeno"] = old["koupeno"].apply(to_bool_cell_excel).astype(bool)
    old["__sk"] = old["ingredience_sk"].map(_key_txt)
    old["__rc"] = old["ingredience_rc"].map(_key_txt)

    old_qty_col = None
    for c in ("mnozstvi","množství","potreba","quantity","qty"):
        if c in old.columns:
            old_qty_col = c; break
    old["__qty_i"] = old[old_qty_col].map(_qty_to_int_micro) if old_qty_col else 0
    old["__k"] = old["koupeno"].astype(bool)

    new_has_date = "datum" in df_new.columns
    old_has_date = "datum" in old.columns
    key_cols = (["datum"] if (new_has_date and old_has_date) else []) + ["__sk","__rc"]

    old_grp = old.groupby(key_cols, as_index=False).agg(prev_qty_i=("__qty_i","sum"), prev_koupeno=("__k","max"))
    new_grp = df_new.groupby(key_cols, as_index=False).agg(new_qty_i=("__qty_i","sum"))

    merged = new_grp.merge(old_grp, on=key_cols, how="left")
    merged["prev_qty_i"] = merged["prev_qty_i"].fillna(0).astype(int)
    merged["prev_koupeno"] = merged["prev_koupeno"].fillna(False).astype(bool)
    increased = merged["new_qty_i"].astype(int) > merged["prev_qty_i"].astype(int)
    merged["keep_true"] = (~increased) & merged["prev_koupeno"]

    df_new = df_new.merge(merged[key_cols + ["keep_true"]], on=key_cols, how="left")
    df_new["keep_true"] = df_new["keep_true"].fillna(False).astype(bool)
    df_new["koupeno"] = (df_new["koupeno"].astype(bool)) | df_new["keep_true"]
    return df_new.drop(columns=["__sk","__rc","__qty_i","keep_true"], errors="ignore")

# ---------------------------- Veřejné API ----------------------------

def compute_plan() -> pd.DataFrame:
    recepty, plan = nacti_data()
    vysledek = spocitej_potrebne_ingredience(recepty, plan)
    if vysledek.empty:
        vysledek["koupeno"] = []
        return vysledek
    vysledek = _recalculate_koupeno_against_previous(vysledek)
    return vysledek

def compute_and_write_ingredients_excel() -> pd.DataFrame:
    df = compute_plan()
    # zachová sloupce včetně for_* + koupeno
    ensure_output_excel_generic(df, OUTPUT_EXCEL)
    return df
