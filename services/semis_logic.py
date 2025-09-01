# services/semis_logic.py
from __future__ import annotations
import pandas as pd

from services.paths import RECEPTY_FILE, PLAN_FILE, OUTPUT_SEMI_EXCEL
from services.data_utils import to_date_col, to_bool_cell_excel
from services.semi_excel_service import ensure_output_semis_excel
from services.compute_common import find_col, _safe_int, _key_txt, _series_or_blank

# ---------- výpočet polotovarů (přímé SK300 z plánů SK400) --------------------

def spocitej_polotovary(recepty: pd.DataFrame, plan: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    COL_P_REG = find_col(recepty, ["Reg. č.", "Reg c", "Reg. c", "Reg.č."]) or "Reg. č."
    COL_P_SK  = find_col(recepty, ["SK"]) or "SK"
    COL_C_REG = find_col(recepty, ["Reg. č..1", "Reg. č. 1", "Reg c 1", "Reg. c.1", "Reg.č..1"]) or "Reg. č..1"
    COL_C_SK  = find_col(recepty, ["SK.1", "SK 1", "sk1", "sk.1"]) or "SK.1"
    COL_C_NAM = find_col(recepty, ["Název 1.1", "Název komponenty", "Nazev 1.1", "Nazev"]) or "Název 1.1"
    COL_QTY   = find_col(recepty, ["Množství", "Mnozstvi", "qty"]) or "Množství"
    COL_MJ    = find_col(recepty, ["MJ evidence", "MJ", "jednotka"]) or "MJ evidence"
    COL_P_NAME = find_col(recepty, ["Název 1", "Název", "nazev"])

    COL_PLAN_REG = find_col(plan, ["reg.č", "reg_c", "reg", "reg. c", "reg c", "reg.c"]) or "reg.č"
    COL_PLAN_QTY = find_col(plan, ["mnozstvi", "množství", "qty"]) or "mnozstvi"

    to_date_col(plan, "datum")
    plan = plan.copy()

    rows_main, rows_detail = [], []

    for _, prow in plan.iterrows():
        final_reg_c = _safe_int(prow.get(COL_PLAN_REG))
        if final_reg_c is None:
            continue
        final_sk = 400
        final_qty = float(prow.get(COL_PLAN_QTY, 0) or 0)
        datum = prow.get("datum", None)

        mask_parent = (recepty[COL_P_SK].map(_safe_int) == final_sk) & \
                      (recepty[COL_P_REG].map(_safe_int) == final_reg_c)
        sub = recepty.loc[mask_parent]
        if sub.empty:
            continue

        final_name = ""
        if COL_P_NAME and COL_P_NAME in sub.columns:
            try:
                fn = sub[COL_P_NAME].dropna().astype(str).str.strip()
                final_name = next((x for x in fn if x), "")
            except Exception:
                final_name = ""

        for _, r in sub.iterrows():
            child_sk  = _safe_int(r.get(COL_C_SK))
            child_reg = _safe_int(r.get(COL_C_REG))
            if child_sk != 300 or child_reg is None:
                continue

            mnozstvi_na_kus = float(r.get(COL_QTY, 0) or 0)
            jednotka        = str(r.get(COL_MJ, "") or "").strip()
            child_name      = str(r.get(COL_C_NAM, "") or "").strip()

            req = final_qty * mnozstvi_na_kus

            rows_main.append({
                "datum": datum,
                "polotovar_sk": child_sk,
                "polotovar_rc": child_reg,
                "nazev": child_name,
                "potreba": req,
                "jednotka": jednotka,
            })
            rows_detail.append({
                "datum": datum,
                "polotovar_sk": child_sk,
                "polotovar_rc": child_reg,
                "final_rc": final_reg_c,
                "final_nazev": final_name,
                "mnozstvi": req,
                "jednotka": jednotka,
            })

    df_main = pd.DataFrame(rows_main)
    if df_main.empty:
        df_main = pd.DataFrame(columns=["datum", "polotovar_sk", "polotovar_rc", "nazev", "potreba", "jednotka"])
    to_date_col(df_main, "datum")
    if not df_main.empty:
        df_main["_num"] = pd.to_numeric(df_main["potreba"], errors="coerce").fillna(0.0)
        df_main = (
            df_main
            .groupby(["datum", "polotovar_sk", "polotovar_rc", "nazev", "jednotka"], as_index=False)
            .agg(potreba=("_num", "sum"))
        )

    df_details = pd.DataFrame(rows_detail)
    if df_details.empty:
        df_details = pd.DataFrame(columns=["datum", "polotovar_sk", "polotovar_rc", "final_rc", "final_nazev", "mnozstvi", "jednotka"])
    to_date_col(df_details, "datum")

    return df_main, df_details

# ---------- pipeline vč. zachování 'vyrobeno' -------------------------

def compute_plan_semifinished() -> tuple[pd.DataFrame, pd.DataFrame]:
    recepty = pd.read_excel(RECEPTY_FILE, sheet_name="HEO - Kusovníkové vazby platné ")
    plan    = pd.read_excel(PLAN_FILE)
    to_date_col(plan, "datum")

    df_main, df_details = spocitej_polotovary(recepty, plan)

    df_main = df_main.copy()
    df_main["vyrobeno"] = False

    try:
        old = pd.read_excel(OUTPUT_SEMI_EXCEL, sheet_name="Prehled").fillna("")
    except Exception:
        try:
            old = pd.read_excel(OUTPUT_SEMI_EXCEL).fillna("")
        except Exception:
            old = pd.DataFrame()

    if not old.empty:
        old.columns = [str(c).strip() for c in old.columns]
        to_date_col(old, "datum")
        if "vyrobeno" not in old.columns:
            old["vyrobeno"] = False
        old["vyrobeno"] = old["vyrobeno"].map(to_bool_cell_excel).astype(bool)

        old["__sk"]  = _series_or_blank(old, "polotovar_sk").map(_key_txt)
        old["__rc"]  = _series_or_blank(old, "polotovar_rc").map(_key_txt)
        old_qty_col  = "potreba" if "potreba" in old.columns else None
        old["__qty"] = pd.to_numeric(old[old_qty_col], errors="coerce").fillna(0.0) if old_qty_col else 0.0
        old["__k"]   = old["vyrobeno"].astype(bool)

        has_old_date = "datum" in old.columns
        key_old = (["datum"] if has_old_date else []) + ["__sk", "__rc"]

        old_grp = old.groupby(key_old, as_index=False).agg(prev_qty=("__qty","sum"), prev_vyrobeno=("__k","max"))

        df_main["__sk"]  = df_main["polotovar_sk"].map(_key_txt)
        df_main["__rc"]  = df_main["polotovar_rc"].map(_key_txt)
        df_main["__qty"] = pd.to_numeric(df_main["potreba"], errors="coerce").fillna(0.0)

        key_new = (["datum"] if ("datum" in df_main.columns and has_old_date) else []) + ["__sk", "__rc"]

        new_grp = df_main.groupby(key_new, as_index=False).agg(new_qty=("__qty","sum"))

        on_cols = key_old if key_old == key_new else ["__sk","__rc"]
        merged = new_grp.merge(old_grp, on=on_cols, how="left")
        merged["prev_qty"]      = merged["prev_qty"].fillna(0.0)
        merged["prev_vyrobeno"] = merged["prev_vyrobeno"].fillna(False).astype(bool)

        increased = merged["new_qty"] > merged["prev_qty"]
        merged["keep_true"] = (~increased) & merged["prev_vyrobeno"]

        df_main = df_main.merge(
            merged[(key_new if key_new else ["__sk", "__rc"]) + ["keep_true"]],
            on=(key_new if key_new else ["__sk", "__rc"]),
            how="left"
        )
        df_main["vyrobeno"] = df_main["vyrobeno"] | df_main["keep_true"].fillna(False)
        df_main.drop(columns=["__sk","__rc","__qty","keep_true"], inplace=True, errors="ignore")

    ensure_output_semis_excel(df_main, df_details)
    return df_main, df_details
