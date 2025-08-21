# main.py
import pandas as pd
import math
from datetime import date
from pathlib import Path
from services.paths import RECEPTY_FILE, PLAN_FILE, OUTPUT_EXCEL
from services.data_utils import (
    to_date_col,
    find_col,
    clean_columns,
    to_bool_cell_excel
)


# ---------------------------- Pomocné safe převody ----------------------------

def _as_key_txt(v):
    if v is None:
        return ""
    i = _safe_int(v)
    return str(i) if i is not None else str(v).strip()

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
    """Bezpečný převod na int: 150 -> 150, 150.0 -> 150, '150' -> 150, NaN/''/None -> None."""
    f = _safe_float(v)
    if f is None:
        return None
    return int(f)

# ---------------------------- Načtení a normalizace ----------------------------

from services.data_utils import find_col, clean_columns  # už u tebe je

def _prepare_recepty(df: pd.DataFrame) -> pd.DataFrame:
    """
    Přidá do DataFrame jednotné pomocné sloupce:
      - _P_REG, _P_SK         (rodič – výrobek)
      - _C_REG, _C_SK         (komponenta)
      - _C_NAME, _QTY, _UNIT  (název, množství/ks, jednotka)
    Umí to pracovat s názvy sloupců, které používají testy (Reg. č., Reg. č..1, SK, SK.1, Množství, MJ evidence, Název 1.1).
    """
    df = df.copy()
    clean_columns(df)  # ořízne záhlaví, převede na stringy

    # Najdi sloupce rodiče (výrobku)
    p_reg = find_col(df, ["Reg. č.", "Reg. č", "Reg.č.", "reg. č.", "reg. č"])
    p_sk  = find_col(df, ["SK", "sk"])

    # Najdi sloupce komponenty
    c_reg = find_col(df, ["Reg. č..1", "Reg. č.1", "Reg.č..1", "reg. č..1", "reg. č.1"])
    c_sk  = find_col(df, ["SK.1", "SK1", "sk.1", "sk1"])
    c_nm  = find_col(df, ["Název 1.1", "Nazev 1.1", "název 1.1", "nazev 1.1", "Název", "Nazev"])
    qty   = find_col(df, ["Množství", "Mnozstvi", "množství", "mnozstvi"])
    unit  = find_col(df, ["MJ evidence", "MJ", "Jednotka", "jednotka"])

    # Ošetři, že minimální sada existuje (pro testy stačí níže uvedené)
    for need, nm in [("rodič Reg. č.", p_reg), ("rodič SK", p_sk), ("komponenta Reg. č..1", c_reg), ("komponenta SK.1", c_sk), ("množství", qty)]:
        if nm is None:
            raise KeyError(f"Nebyl nalezen sloupec pro {need}")

    # Vytvoř pomocné sloupce
    df["_P_REG"]  = df[p_reg].map(_as_key_txt)
    df["_P_SK"]   = df[p_sk].map(_as_key_txt)
    df["_C_REG"]  = df[c_reg].map(_as_key_txt)
    df["_C_SK"]   = df[c_sk].map(_as_key_txt)
    df["_C_NAME"] = df[c_nm] if c_nm is not None else ""
    df["_QTY"]    = pd.to_numeric(df[qty], errors="coerce").fillna(0.0)
    df["_UNIT"]   = df[unit] if unit is not None else ""
    return df


def nacti_data():
    # Recepty + plán
    recepty = pd.read_excel(RECEPTY_FILE, sheet_name="HEO - Kusovníkové vazby platné ")
    plan = pd.read_excel(PLAN_FILE)

    clean_columns(recepty)
    clean_columns(plan)

    if "datum" in plan.columns:
        to_date_col(plan, "datum")

    # Normalizace klíčových čísel v receptu (rodič/komponenta)
    # Rodič (parent)
    recepty["_P_SK"]  = recepty.get("SK").map(_safe_int) if "SK" in recepty.columns else None
    recepty["_P_REG"] = recepty.get("Reg. č.").map(_safe_int) if "Reg. č." in recepty.columns else None
    # Komponenta (child)
    recepty["_C_SK"]  = recepty.get("SK.1").map(_safe_int) if "SK.1" in recepty.columns else None
    recepty["_C_REG"] = recepty.get("Reg. č..1").map(_safe_int) if "Reg. č..1" in recepty.columns else None

    # Množství na kus – numeric
    if "Množství" in recepty.columns:
        recepty["_C_QTY"] = pd.to_numeric(recepty["Množství"], errors="coerce").fillna(0.0)
    else:
        recepty["_C_QTY"] = 0.0

    return recepty, plan

# ---------------------------- Rozklad výrobku ----------------------------

def rozloz_vyrobek(vyrobek_id, mnozstvi, recepty, navstiveno=None):
    if navstiveno is None:
        navstiveno = set()
    vysledky = []

    if vyrobek_id in navstiveno:
        return []

    # rozdělení "400-12345" na sk a reg
    vyrobek_sk, vyrobek_reg_c = vyrobek_id.split("-", 1)
    vyrobek_sk = _as_key_txt(vyrobek_sk)
    vyrobek_reg_c = _as_key_txt(vyrobek_reg_c)

    # musí existovat sloupce z _prepare_recepty
    if "_P_REG" not in recepty.columns or "_P_SK" not in recepty.columns:
        # pro jistotu připravit, kdyby někdo volal bez přípravy
        recepty = _prepare_recepty(recepty)

    # najdi komponenty pro daný výrobek
    podrecept = recepty[(recepty["_P_REG"] == vyrobek_reg_c) & (recepty["_P_SK"] == vyrobek_sk)]

    if podrecept.empty:
        # žádný záznam – ber to jako list položku
        vysledky.append({
            "ingredience_rc": vyrobek_reg_c,
            "ingredience_sk": vyrobek_sk,
            "nazev": f"{vyrobek_sk}-{vyrobek_reg_c}",
            "potreba": mnozstvi,
            "jednotka": None
        })
    else:
        for _, r in podrecept.iterrows():
            komponenta_reg_c = r["_C_REG"]
            komponenta_nazev = r["_C_NAME"]
            mnozstvi_na_kus  = r["_QTY"]
            jednotka         = r["_UNIT"]
            komponenta_sk    = r["_C_SK"]
            komponenta_id    = f"{komponenta_sk}-{komponenta_reg_c}"
            celkem           = mnozstvi * mnozstvi_na_kus

            # Pokud existuje další receptura pro komponentu (tj. je sama rodič)
            if ((recepty["_P_REG"] == komponenta_reg_c) & (recepty["_P_SK"] == komponenta_sk)).any():
                vysledky.extend(rozloz_vyrobek(komponenta_id, celkem, recepty, navstiveno))
            elif _safe_int(komponenta_sk) not in [400, 300]:
                vysledky.append({
                    "ingredience_rc": komponenta_reg_c,
                    "ingredience_sk": komponenta_sk,
                    "nazev": komponenta_nazev,
                    "potreba": celkem,
                    "jednotka": jednotka
                })

    return vysledky


# ---------------------------- Výpočet a historie 'koupeno' ----------------------------

def spocitej_potrebne_ingredience(recepty, plan):
    
    recepty = _prepare_recepty(recepty)
    vysledky = []
    for _, row in plan.iterrows():
        # z plánu: reg.č je rodičovský REG, výrobek je 400-<reg.č>
        vyrobek_reg_c = row.get('reg.č')
        vyrobek_id = f"400-{_safe_int(vyrobek_reg_c)}"

        mnozstvi = _safe_float(row.get("mnozstvi")) or 0.0
        datum = row.get("datum")

        ingredience = rozloz_vyrobek(vyrobek_id, mnozstvi, recepty)
        for ingr in ingredience:
            # přeskoč, pokud se někde nepodařilo určit SK/RC
            if ingr["ingredience_sk"] is None or ingr["ingredience_rc"] is None:
                continue
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
    if df.empty:
        # nic k výrobě -> vrať prázdný DF se správnými sloupci
        return pd.DataFrame(columns=["datum","ingredience_sk","ingredience_rc","nazev","potreba","jednotka","koupeno"])

    to_date_col(df, "datum")

    df = df.groupby(["datum","ingredience_sk","ingredience_rc","nazev","jednotka"], as_index=False)["potreba"].sum()
    df = df[["datum","ingredience_sk","ingredience_rc","nazev","potreba","jednotka"]]
    return df

def _recalculate_koupeno_against_previous(df_new: pd.DataFrame) -> pd.DataFrame:
    """
    Porovná 'nové' množství s 'předchozím' bez chyb způsobených float aritmetikou:
    - množství převádí na "mikro-jednotky" (int) přes Decimal s 6 desetinnými místy
    - pokud se nová suma > stará suma (po klíči), resetuje koupeno na False
    - jinak zachová True z minulosti
    """
    import pandas as pd
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

    SCALE = 6  # počet desetinných míst pro převod na celé číslo

    def clean_columns_local(df: pd.DataFrame) -> None:
        df.columns = [str(c).strip() for c in df.columns]

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

    def _qty_to_int_micro(v) -> int:
        """
        Převod na celé číslo v mikro-jednotkách přes Decimal:
        - čte i stringy s čárkou
        - NaN/None -> 0
        - zaokrouhlení HALF_UP
        """
        try:
            s = str(v).strip().replace(",", ".")
            if s == "" or s.lower() in {"nan", "none"}:
                return 0
            d = Decimal(s)
        except (InvalidOperation, Exception):
            return 0
        # kvantizace na SCALE míst + přenásobení
        q = d.quantize(Decimal(10) ** (-SCALE), rounding=ROUND_HALF_UP)
        return int((q * (Decimal(10) ** SCALE)).to_integral_value(rounding=ROUND_HALF_UP))

    # --- NOVÁ DATA ---
    df_new = df_new.copy()
    clean_columns_local(df_new)
    to_date_col(df_new, "datum")

    # začínáme vždy s False (nová výpočetní tabulka koupeno neposuzuje)
    df_new["koupeno"] = False

    # klíče a množství (int mikro)
    df_new["__sk"]  = df_new.get("ingredience_sk", "").map(_key_txt)
    df_new["__rc"]  = df_new.get("ingredience_rc", "").map(_key_txt)
    df_new["__qty_i"] = df_new.get("potreba", 0).map(_qty_to_int_micro)

    # --- STARÝ VÝSTUP ---
    try:
        old = pd.read_excel(OUTPUT_EXCEL)
    except Exception:
        # žádná historie → všude koupeno=False (už nastaveno)
        return df_new.drop(columns=["__sk","__rc","__qty_i"], errors="ignore")

    old = old.fillna("")
    clean_columns_local(old)
    to_date_col(old, "datum")

    # jistota sloupců
    if "ingredience_sk" not in old.columns:
        old["ingredience_sk"] = ""
    if "ingredience_rc" not in old.columns:
        old["ingredience_rc"] = ""
    if "koupeno" not in old.columns:
        old["koupeno"] = False

    # normalizace
    old["koupeno"] = old["koupeno"].apply(to_bool_cell_excel).astype(bool)
    old["__sk"] = old["ingredience_sk"].map(_key_txt)
    old["__rc"] = old["ingredience_rc"].map(_key_txt)

    old_qty_col = find_col(old, ["mnozstvi", "potreba"])
    if old_qty_col is None:
        old["__qty_i"] = 0
    else:
        old["__qty_i"] = old[old_qty_col].map(_qty_to_int_micro)

    old["__k"] = old["koupeno"].astype(bool)

    # klíče pro merge (s datem jen když ho mají obě tabulky)
    new_has_date = "datum" in df_new.columns
    old_has_date = "datum" in old.columns
    key_cols = (["datum"] if (new_has_date and old_has_date) else []) + ["__sk", "__rc"]

    # součty po klíčích
    old_grp = (
        old.groupby(key_cols, as_index=False)
           .agg(prev_qty_i=("__qty_i","sum"), prev_koupeno=("__k","max"))
    )
    new_grp = (
        df_new.groupby(key_cols, as_index=False)
              .agg(new_qty_i=("__qty_i","sum"))
    )

    merged = new_grp.merge(old_grp, on=key_cols, how="left")
    merged["prev_qty_i"] = merged["prev_qty_i"].fillna(0).astype(int)
    merged["prev_koupeno"] = merged["prev_koupeno"].fillna(False).astype(bool)

    # přesné porovnání na celých číslech (žádné floaty)
    increased = merged["new_qty_i"].astype(int) > merged["prev_qty_i"].astype(int)
    merged["keep_true"] = (~increased) & merged["prev_koupeno"]

    # promítnout zpět do df_new
    df_new = df_new.merge(
        merged[key_cols + ["keep_true"]],
        on=key_cols,
        how="left"
    )
    df_new["keep_true"] = df_new["keep_true"].fillna(False).astype(bool)
    df_new["koupeno"] = (df_new["koupeno"].astype(bool)) | df_new["keep_true"]

    return df_new.drop(columns=["__sk","__rc","__qty_i","keep_true"], errors="ignore")


def compute_plan() -> pd.DataFrame:
    recepty, plan = nacti_data()
    vysledek = spocitej_potrebne_ingredience(recepty, plan)
    # může být prázdný – v takovém případě rovnou vrať
    if vysledek.empty:
        vysledek["koupeno"] = []
        return vysledek
    vysledek = _recalculate_koupeno_against_previous(vysledek)
    return vysledek
