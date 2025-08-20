import pandas as pd
from datetime import date
from pathlib import Path

# Cesty k souborům 
DATA_DIR = Path("data")
RECEPTY_FILE = DATA_DIR / "recepty.xlsx" 
PLAN_FILE = Path("plan.xlsx")
OUTPUT_FILE = Path("vysledek.xlsx")

# --- pomocné funkce ---
def _to_date(s):
    return pd.to_datetime(s, errors="coerce").dt.date

def _find_col(df, candidates):
    """Najde skutečný název sloupce case-insensitive (stejné jako v GUI)."""
    cols = {c.strip().lower(): c for c in df.columns}
    for cand in candidates:
        key = cand.strip().lower()
        if key in cols:
            return cols[key]
    return None

def _truthy(v):
    """Robustně zkontroluje, jestli hodnota reprezentuje True."""
    if pd.isna(v):
        return False
    if isinstance(v, bool):
        return v
    try:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return bool(int(v))
    except Exception:
        pass
    s = str(v).strip().lower()
    return s in ("true", "1", "yes", "y", "t", "pravda")

def _as_date(val):
    """Převod hodnoty na date (pokud možno). Pokud ne, vrátí původní hodnotu jako string)."""
    try:
        return pd.to_datetime(val).date()
    except Exception:
        try:
            if isinstance(val, date):
                return val
        except Exception:
            pass
        return str(val)

# --- načtení dat ---
def nacti_data():
    recepty = pd.read_excel(RECEPTY_FILE, sheet_name="HEO - Kusovníkové vazby platné ")
    plan = pd.read_excel(PLAN_FILE)
    if "datum" in plan.columns:
        plan["datum"] = _to_date(plan["datum"])   # ← jen den
    return recepty, plan

def rozloz_vyrobek(vyrobek_id, mnozstvi, recepty, navstiveno=None):
    if navstiveno is None:
        navstiveno = set()
    vysledky = []

    if vyrobek_id in navstiveno:
        return []
    
    # vyrobek_sk_c = "SK-Reg.c" -> rozdělíme
    vyrobek_sk, vyrobek_reg_c = vyrobek_id.split("-", 1)
    vyrobek_sk = int(vyrobek_sk)
    vyrobek_reg_c = int(vyrobek_reg_c)

    # najdi všechny řádky, kde rodič = vyrobek
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
        id = f"400-{vyrobek_reg_c}"

        mnozstvi = row["mnozstvi"] 
        datum = row["datum"] 
        ingredience = rozloz_vyrobek(id, mnozstvi, recepty) 
        for ingr in ingredience:
            vysledky.append({ 
                "datum": datum, 
                "vyrobek": id, 
                "nazev": ingr["nazev"], 
                "ingredience_rc": ingr["ingredience_rc"], 
                "ingredience_sk": ingr["ingredience_sk"], 
                "potreba": ingr["potreba"], 
                "jednotka": ingr["jednotka"] 
            }) 
            
    df = pd.DataFrame(vysledky)
    df["datum"] = _to_date(df["datum"])               # ← jen den

    df = df.groupby(["datum", "ingredience_sk","ingredience_rc","nazev", "jednotka"], as_index=False)["potreba"].sum() 
    cols = ["datum", "ingredience_sk","ingredience_rc", "nazev", "potreba", "jednotka"] 
    df = df[cols] 
    return df 

def uloz_vysledek(df): 
    df.to_excel(OUTPUT_FILE, index=False) 
    print(f"✅ Výsledek uložen do: {OUTPUT_FILE}") 
    
def main():
    recepty, plan = nacti_data() 
    vysledek = spocitej_potrebne_ingredience(recepty, plan) 

    # ---- NOVÁ LOGIKA OBNOVY KOLONKY 'koupeno' PODLE MNOŽSTVÍ ----
    # vytvoříme dočasný numerický sloupec 'mnozstvi' pro porovnání
    vysledek["mnozstvi"] = pd.to_numeric(vysledek["potreba"], errors="coerce").fillna(0)

    vysledek["datum"] = _to_date(vysledek["datum"])   # ← jen den

    vysledek["__sk"] = vysledek["ingredience_sk"].astype(str).str.strip()
    vysledek["__rc"] = vysledek["ingredience_rc"].astype(str).str.strip()

    if OUTPUT_FILE.exists():
        try:
            old = pd.read_excel(OUTPUT_FILE)
            old.columns = old.columns.str.strip()

            # klíče v old
            old["datum"] = _to_date(old["datum"])             # ← jen den

            old["__sk"] = old["ingredience_sk"].astype(str).str.strip()
            old["__rc"] = old["ingredience_rc"].astype(str).str.strip()

            # zjištění názvu sloupce s množstvím v old (může být 'mnozstvi' nebo 'potreba')
            old_qty_col = _find_col(old, ["mnozstvi", "potreba"])
            if old_qty_col is None:
                old["__qty"] = 0.0
            else:
                old["__qty"] = pd.to_numeric(old[old_qty_col], errors="coerce").fillna(0)

            # koupeno v old → bool
            old_k = _find_col(old, ["koupeno"])
            if old_k is None:
                old["koupeno"] = False
                old_k = "koupeno"
            old["__koupeno_bool"] = old[old_k].apply(_truthy)

            # agregace starých dat na úroveň klíče (součet množství + stav koupeno = any)
            old_grp = (
                old.groupby(["datum", "__sk", "__rc"], as_index=False)
                .agg(
                    prev_qty=("__qty", "sum"),             # součet předchozího množství
                    prev_koupeno=("__koupeno_bool", "max") # True, pokud kdykoli dřív bylo koupeno
                )
            )
            # Pozn.: triviální způsob jak mít čitelný kód bez hvězdiček v editoru

            # merge nového výsledku s historii
            merged = vysledek.merge(old_grp, on=["datum", "__sk", "__rc"], how="left")

            # NaN → defaulty
            merged["prev_qty"] = merged["prev_qty"].fillna(0.0)
            merged["prev_koupeno"] = merged["prev_koupeno"].fillna(False).astype(bool)

            # Pokud se nové množství ZVÝŠILO oproti minule → koupeno=False
            # Jinak nech původní hodnotu koupeno (NEpřiřazuj True automaticky)
            increased = merged["mnozstvi"] > merged["prev_qty"]
            merged["koupeno"] = (~increased) & merged["prev_koupeno"]

            # uklid: zahoď pomocné sloupce a vrať do 'vysledek'
            vysledek = merged.drop(columns=["prev_qty", "prev_koupeno"])
        except Exception as e:
            print("⚠️ Nelze načíst/porovnat starý výsledek, nastavím koupeno=False:", e)
            vysledek["koupeno"] = False
    else:
        # žádný starý soubor → všechno nekoupené
        vysledek["koupeno"] = False

    # už nepotřebujeme dočasné klíče a 'mnozstvi'
    vysledek = vysledek.drop(columns=["__sk", "__rc", "mnozstvi"])

    uloz_vysledek(vysledek) 
    return vysledek
    
if __name__ == "__main__": 
    main()
