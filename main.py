# main.py
import pandas as pd
from datetime import date
from services.paths import RECEPTY_FILE, PLAN_FILE, OUTPUT_EXCEL
from services.data_utils import to_date_col, find_col
from pathlib import Path

def _to_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.date

def nacti_data():
    # List sheetů, tvůj název má mezery – držíme se originálu
    recepty = pd.read_excel(RECEPTY_FILE, sheet_name="HEO - Kusovníkové vazby platné ")
    plan = pd.read_excel(PLAN_FILE)
    if "datum" in plan.columns:
        plan["datum"] = _to_date(plan["datum"])   # jen datum
    return recepty, plan

def rozloz_vyrobek(vyrobek_id, mnozstvi, recepty, navstiveno=None):
    if navstiveno is None:
        navstiveno = set()
    vysledky = []

    if vyrobek_id in navstiveno:
        return []
    navstiveno.add(vyrobek_id)

    vyrobek_sk, vyrobek_reg_c = vyrobek_id.split("-", 1)
    vyrobek_sk = int(vyrobek_sk)
    vyrobek_reg_c = int(vyrobek_reg_c)

    podrecept = recepty[(recepty["Reg. č."] == vyrobek_reg_c) & (recepty["SK"] == vyrobek_sk)]

    if podrecept.empty:
        vysledky.append({
            "ingredience_rc": vyrobek_reg_c,
            "ingredience_sk": vyrobek_sk,
            "nazev": f"{vyrobek_sk}-{vyrobek_reg_c}",
            "potreba": mnozstvi,
            "jednotka": None
        })
    else:
        for _, r in podrecept.iterrows():
            komponenta_reg_c = r["Reg. č..1"]
            komponenta_nazev = r["Název 1.1"]
            mnozstvi_na_kus = r["Množství"]
            jednotka = r["MJ evidence"]
            komponenta_sk = int(r["SK.1"])
            komponenta_id = f"{komponenta_sk}-{komponenta_reg_c}"
            celkem = mnozstvi * mnozstvi_na_kus

            # Rekurzivně zkus rozložit komponentu
            if ((recepty["Reg. č."] == komponenta_reg_c) & (recepty["SK"] == komponenta_sk)).any():
                vysledky.extend(rozloz_vyrobek(komponenta_id, celkem, recepty, navstiveno))
            elif komponenta_sk not in [400, 300]:
                vysledky.append({
                    "ingredience_rc": komponenta_reg_c,
                    "ingredience_sk": komponenta_sk,
                    "nazev": komponenta_nazev,
                    "potreba": celkem,
                    "jednotka": jednotka
                })

    return vysledky

def spocitej_potrebne_ingredience(recepty, plan):
    vysledky = []
    for _, row in plan.iterrows():
        vyrobek_reg_c = str(row['reg.č'])
        vyrobek_id = f"400-{vyrobek_reg_c}"
        mnozstvi = row["mnozstvi"]
        datum = row["datum"]

        ingredience = rozloz_vyrobek(vyrobek_id, mnozstvi, recepty)
        for ingr in ingredience:
            vysledky.append({
                "datum": datum,
                "vyrobek": vyrobek_id,
                "nazev": ingr["nazev"],
                "ingredience_rc": ingr["ingredience_rc"],
                "ingredience_sk": ingr["ingredience_sk"],
                "potreba": ingr["potreba"],
                "jednotka": ingr["jednotka"]
            })

    df = pd.DataFrame(vysledky)
    to_date_col(df, "datum")

    df = df.groupby(["datum","ingredience_sk","ingredience_rc","nazev","jednotka"], as_index=False)["potreba"].sum()
    df = df[["datum","ingredience_sk","ingredience_rc","nazev","potreba","jednotka"]]
    return df

def _recalculate_koupeno_against_previous(df_new: pd.DataFrame) -> pd.DataFrame:
    """
    Logika: pokud se součet 'potreba' pro (datum, sk, rc) oproti minulému výstupu ZVÝŠIL,
    nastavíme koupeno=False. Jinak zachováme předchozí koupeno. Novou hodnotu True
    automaticky NEpřidělujeme.
    """
    df_new = df_new.copy()
    df_new["__sk"] = df_new["ingredience_sk"].astype(str).str.strip()
    df_new["__rc"] = df_new["ingredience_rc"].astype(str).str.strip()
    df_new["__qty"] = pd.to_numeric(df_new["potreba"], errors="coerce").fillna(0.0)
    to_date_col(df_new, "datum")

    if not OUTPUT_EXCEL.exists():
        df_new["koupeno"] = False
        return df_new.drop(columns=["__sk","__rc","__qty"])

    try:
        old = pd.read_excel(OUTPUT_EXCEL)
    except Exception:
        df_new["koupeno"] = False
        return df_new.drop(columns=["__sk","__rc","__qty"])

    old = old.copy()
    old.columns = old.columns.str.strip()
    to_date_col(old, "datum")
    old["__sk"] = old["ingredience_sk"].astype(str).str.strip()
    old["__rc"] = old["ingredience_rc"].astype(str).str.strip()
    old_qty_col = find_col(old, ["mnozstvi", "potreba"])
    old["__qty"] = pd.to_numeric(old[old_qty_col], errors="coerce").fillna(0.0) if old_qty_col else 0.0

    old_k = find_col(old, ["koupeno"])
    if old_k is None:
        old["koupeno"] = False
        old_k = "koupeno"
    old["__koupeno_bool"] = old[old_k].astype(bool)

    old_grp = (
        old.groupby(["datum","__sk","__rc"], as_index=False)
           .agg(prev_qty=("__qty","sum"), prev_koupeno=("__koupeno_bool","max"))
    )

    new_grp = (
        df_new.groupby(["datum","__sk","__rc"], as_index=False)
              .agg(new_qty=("__qty","sum"))
    )

    merged = new_grp.merge(old_grp, on=["datum","__sk","__rc"], how="left")
    merged["prev_qty"] = merged["prev_qty"].fillna(0.0)
    merged["prev_koupeno"] = merged["prev_koupeno"].fillna(False).astype(bool)
    increased = merged["new_qty"] > merged["prev_qty"]

    # cílový stav 'koupeno' na úrovni klíče
    merged["koupeno_key"] = (~increased) & merged["prev_koupeno"]

    # Přenes hodnotu na řádky df_new
    df_new = df_new.merge(
        merged[["datum","__sk","__rc","koupeno_key"]],
        on=["datum","__sk","__rc"],
        how="left"
    )
    df_new["koupeno"] = df_new["koupeno_key"].fillna(False).astype(bool)

    return df_new.drop(columns=["__sk","__rc","__qty","koupeno_key"])

def compute_plan() -> pd.DataFrame:
    """
    Hlavní funkce: načte data, spočítá potřeby a zohlední historii
    kvůli koloně 'koupeno' (pokud se množství zvýšilo, resetuje na False).
    Nic nezapisuje – zápis/merge řeší excel_service.ensure_output_excel().
    """
    recepty, plan = nacti_data()
    vysledek = spocitej_potrebne_ingredience(recepty, plan)
    vysledek = _recalculate_koupeno_against_previous(vysledek)
    return vysledek
