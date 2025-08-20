import pandas as pd
from datetime import date
from pathlib import Path

# Cesty k souborům 
DATA_DIR = Path("data")
RECEPTY_FILE = DATA_DIR / "recepty.xlsx" 
PLAN_FILE = Path("plan.xlsx")
OUTPUT_FILE = Path("vysledek.xlsx")

# --- pomocné funkce ---
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
        # čísla
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return bool(int(v))
    except Exception:
        pass
    s = str(v).strip().lower()
    return s in ("true", "1", "yes", "y", "t", "pravda")

def _as_date(val):
    """Převod hodnoty na date (pokud možno). Pokud ne, vrátí původní hodnotu jako string)."""
    try:
        # pd.to_datetime zvládne i date/datetime/str
        return pd.to_datetime(val).date()
    except Exception:
        try:
            # pokud už je to date
            if isinstance(val, date):
                return val
        except Exception:
            pass
        return str(val)

# --- načtení dat ---
def nacti_data(): 
    recepty = pd.read_excel(RECEPTY_FILE, sheet_name="HEO - Kusovníkové vazby platné ") 
    plan = pd.read_excel(PLAN_FILE) 
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
        # žádný další kusovník = konečná ingredience
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
        # id = f"{400}-{row['reg.č']}"

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
    df["datum"] = pd.to_datetime(df["datum"]).dt.date
    # agregace stejných ingrediencí podle data 
    df = df.groupby(["datum", "ingredience_sk","ingredience_rc","nazev", "jednotka"], as_index=False)["potreba"].sum() 
    
    # preusporadani sloupcu 
    cols = ["datum", "ingredience_sk","ingredience_rc", "nazev", "potreba", "jednotka"] 
    df = df[cols] 
    return df 


def uloz_vysledek(df): 
    df.to_excel(OUTPUT_FILE, index=False) 
    print(f"✅ Výsledek uložen do: {OUTPUT_FILE}") 
    
def main():
    recepty, plan = nacti_data() 
    vysledek = spocitej_potrebne_ingredience(recepty, plan) 

    # --- pokud existuje předchozí výsledek, znovu označíme již koupené položky ---
    if OUTPUT_FILE.exists():
        try:
            old = pd.read_excel(OUTPUT_FILE)
            old.columns = old.columns.str.strip()
            # najdeme sloupec koupeno (pokud existuje)
            old_k = _find_col(old, ["koupeno"])
            if old_k is None:
                old["koupeno"] = False
                old_k = "koupeno"

            # normalizace typů pro porovnání
            # převést datumy na date
            old["datum"] = pd.to_datetime(old["datum"], errors="coerce").dt.date
            # převést SK a RC na int kde to jde (jinak string)
            # pro bezpečné porovnání převedeme na stringy (bez whitespace)
            old["__key_sk"] = old["ingredience_sk"].astype(str).str.strip()
            old["__key_rc"] = old["ingredience_rc"].astype(str).str.strip()
            old["__key_date"] = old["datum"].apply(lambda v: v.isoformat() if isinstance(v, date) else str(v))

            # vytvoříme množinu klíčů, které jsou koupené (truthy)
            bought_keys = set()
            for _, r in old.iterrows():
                if _truthy(r.get(old_k, False)):
                    bought_keys.add((r["__key_date"], r["__key_sk"], r["__key_rc"]))

            # nyní nastavíme v novém výsledku sloupec 'koupeno' na True tam, kde klíč sedí
            # připravíme klíč i pro nový df
            vysledek["__key_date"] = vysledek["datum"].apply(lambda v: v.isoformat() if isinstance(v, date) else str(v))
            vysledek["__key_sk"] = vysledek["ingredience_sk"].astype(str).str.strip()
            vysledek["__key_rc"] = vysledek["ingredience_rc"].astype(str).str.strip()

            vysledek["koupeno"] = vysledek.apply(
                lambda r: True if (r["__key_date"], r["__key_sk"], r["__key_rc"]) in bought_keys else False,
                axis=1
            )

            # odstraníme pomocné klíče
            vysledek = vysledek.drop(columns=["__key_date", "__key_sk", "__key_rc"])
        except Exception as e:
            # pokud cokoli selže při načítání starého souboru, prostě vytvoříme nový bez koupeno
            print("⚠️ Nelze načíst starý výsledek pro restore koupeno:", e)
            vysledek["koupeno"] = False
    else:
        # žádný starý soubor - vytvoříme sloupec koupeno = False
        vysledek["koupeno"] = False

    uloz_vysledek(vysledek) 
    return vysledek
    
if __name__ == "__main__": 
    main()
