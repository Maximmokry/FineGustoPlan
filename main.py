# main.py
from __future__ import annotations
import pandas as pd
import math
from datetime import date
from pathlib import Path

from services.excel_service import ensure_output_excel_generic
from services.paths import RECEPTY_FILE, PLAN_FILE, OUTPUT_EXCEL, OUTPUT_SEMI_EXCEL
from services.data_utils import (
    to_date_col,
    clean_columns,
    to_bool_cell_excel,
)
from services.semi_excel_service import ensure_output_semis_excel


# ---------------------------- Tolerantní hledání sloupců ----------------------------

def _normalize_col_key(s: str) -> str:
    """Normalizace klíče: lower + odstranění mezer/teček/podtržítek/pomlček + odstraň CZ diakritiku."""
    x = str(s or "").strip().lower()
    repl = {
        "á": "a", "č": "c", "ď": "d", "é": "e", "ě": "e", "í": "i", "ň": "n",
        "ó": "o", "ř": "r", "š": "s", "ť": "t", "ú": "u", "ů": "u", "ý": "y", "ž": "z",
    }
    x = "".join(repl.get(ch, ch) for ch in x)
    for ch in (" ", ".", "_", "-", "\u00A0"):  # vč. pevné mezery
        x = x.replace(ch, "")
    return x


def find_col_loose(df: pd.DataFrame, candidates) -> str | None:
    """
    Tolerantní hledání názvu sloupce:
    - ignoruje velikost písmen, mezery, tečky, podtržítka, pomlčky
    - odstraňuje CZ diakritiku (č->c, ř->r, …)
    - funguje i když kandidát má tečku na konci nebo ne (reg.c vs reg.c.)
    Vrací PŮVODNÍ název sloupce z df.columns, nebo None.
    """
    norm_map = {}
    for c in df.columns:
        norm_map[_normalize_col_key(c)] = c

    def _variants(cand: str):
        base = str(cand or "")
        yield base
        if base.endswith("."):
            yield base[:-1]      # bez poslední tečky
        else:
            yield base + "."     # s tečkou navíc
        yield base.replace(".", "")  # bez všech teček

    for cand in candidates or []:
        for v in _variants(cand):
            k = _normalize_col_key(v)
            if k in norm_map:
                return norm_map[k]
    return None


# Překryjeme lokálně find_col tak, aby veškerý kód níže automaticky používal tolerantní vyhledávání.
def find_col(df: pd.DataFrame, candidates):
    return find_col_loose(df, candidates)


# ---------------------------- Pomocné safe převody ----------------------------

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


def _as_key_txt(v):
    """Stabilní textová reprezentace čísla/klíče (pro SK/RC apod.)."""
    if v is None:
        return ""
    i = _safe_int(v)
    return str(i) if i is not None else str(v).strip()


def _key_txt(v) -> str:
    """Stabilní textový klíč: 150 i 150.0 -> '150'; None -> ''."""
    if v is None:
        return ""
    i = _safe_int(v)
    return str(i) if i is not None else str(v).strip()


def _series_or_blank(df: pd.DataFrame, col: str) -> pd.Series:
    """Vrať df[col], pokud existuje; jinak prázdnou Series se stejným indexem."""
    return df[col] if col in df.columns else pd.Series([""] * len(df), index=df.index)


# ---------------------------- Načtení a normalizace ----------------------------

def _prepare_recepty(df: pd.DataFrame) -> pd.DataFrame:
    """
    Přidá do DataFrame jednotné pomocné sloupce:
      - _P_REG, _P_SK         (rodič – výrobek)
      - _C_REG, _C_SK         (komponenta)
      - _C_NAME, _QTY, _UNIT  (název, množství/ks, jednotka)
    Umí to pracovat s názvy sloupců, které používají testy (Reg. č., Reg. č..1, SK, SK.1, Množství, MJ evidence, Název 1.1).
    """
    df = df.copy()
    clean_columns(df)

    # Najdi sloupce (tolerantně)
    p_reg = find_col(df, ["Reg. č.", "Reg. č", "Reg.č.", "reg. č.", "reg. č", "reg c", "reg.c"])
    p_sk  = find_col(df, ["SK", "sk"])

    c_reg = find_col(df, ["Reg. č..1", "Reg. č.1", "Reg.č..1", "reg. č..1", "reg. č.1", "Reg c 1", "Reg. c.1"])
    c_sk  = find_col(df, ["SK.1", "SK1", "sk.1", "sk1", "SK 1"])
    c_nm  = find_col(df, ["Název 1.1", "Nazev 1.1", "název 1.1", "nazev 1.1", "Název", "Nazev"])
    qty   = find_col(df, ["Množství", "Mnozstvi", "množství", "mnozstvi", "qty"])
    unit  = find_col(df, ["MJ evidence", "MJ", "Jednotka", "jednotka"])

    # Minimální sada musí existovat
    for need, nm in [
        ("rodič Reg. č.", p_reg),
        ("rodič SK", p_sk),
        ("komponenta Reg. č..1", c_reg),
        ("komponenta SK.1", c_sk),
        ("množství", qty),
    ]:
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

    # Bezpečné vyhledání sloupců v receptuře (tolerantně)
    col_p_sk  = find_col(recepty, ["SK"])
    col_p_reg = find_col(recepty, ["Reg. č.", "Reg. č", "Reg c", "Reg. c", "Reg.č."])

    col_c_sk  = find_col(recepty, ["SK.1", "SK 1", "sk1", "sk.1"])
    col_c_reg = find_col(recepty, ["Reg. č..1", "Reg. č. 1", "Reg c 1", "Reg. c.1", "Reg.č..1"])
    col_c_qty = find_col(recepty, ["Množství", "Mnozstvi", "qty"])

    # Normalizace klíčových čísel v receptu (rodič/komponenta) – jen pokud sloupce existují
    recepty["_P_SK"]  = recepty[col_p_sk].map(_safe_int) if col_p_sk else None
    recepty["_P_REG"] = recepty[col_p_reg].map(_safe_int) if col_p_reg else None
    recepty["_C_SK"]  = recepty[col_c_sk].map(_safe_int) if col_c_sk else None
    recepty["_C_REG"] = recepty[col_c_reg].map(_safe_int) if col_c_reg else None

    # Množství na kus – numeric (pokud máme sloupec)
    if col_c_qty:
        recepty["_C_QTY"] = pd.to_numeric(recepty[col_c_qty], errors="coerce").fillna(0.0)
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
    navstiveno.add(vyrobek_id)

    # rozdělení "400-12345" na sk a reg
    vyrobek_sk, vyrobek_reg_c = vyrobek_id.split("-", 1)
    vyrobek_sk = _as_key_txt(vyrobek_sk)
    vyrobek_reg_c = _as_key_txt(vyrobek_reg_c)

    # musí existovat sloupce z _prepare_recepty
    if "_P_REG" not in recepty.columns or "_P_SK" not in recepty.columns:
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

def spocitej_potrebne_ingredience(recepty: pd.DataFrame, plan: pd.DataFrame) -> pd.DataFrame:
    # připrav receptury (už tolerantní)
    recepty = _prepare_recepty(recepty)

    # očisti a toleruj názvy sloupců i v PLÁNU
    clean_columns(plan)

    COL_PLAN_REG  = find_col(plan, ["reg.č", "reg c", "reg.c", "regc", "reg č", "reg"])
    COL_PLAN_QTY  = find_col(plan, ["mnozstvi", "množství", "qty", "mnozství"])
    COL_PLAN_DATE = find_col(plan, ["datum", "date", "dat", "DATUM"])

    vysledky = []
    for _, row in plan.iterrows():
        vyrobek_reg_c = row.get(COL_PLAN_REG)
        if vyrobek_reg_c is None:
            # řádek plánu bez identifikace výrobku přeskoč
            continue

        vyrobek_id = f"400-{_safe_int(vyrobek_reg_c)}"

        mnozstvi = _safe_float(row.get(COL_PLAN_QTY)) or 0.0
        datum = row.get(COL_PLAN_DATE, None)

        ingredience = rozloz_vyrobek(vyrobek_id, mnozstvi, recepty)
        for ingr in ingredience:
            if ingr["ingredience_sk"] is None or ingr["ingredience_rc"] is None:
                continue
            vysledky.append({
                "datum": datum,
                "vyrobek": vyrobek_id,
                "nazev": ingr["nazev"],
                "ingredience_rc": ingr["ingredience_rc"],
                "ingredience_sk": ingr["ingredience_sk"],
                "potreba": ingr["potreba"],
                "jednotka": ingr["jednotka"],
            })

    df = pd.DataFrame(vysledky)
    if df.empty:
        return pd.DataFrame(columns=["datum","ingredience_sk","ingredience_rc","nazev","potreba","jednotka","koupeno"])

    to_date_col(df, "datum")
    df = df.groupby(["datum","ingredience_sk","ingredience_rc","nazev","jednotka"], as_index=False)["potreba"].sum()
    return df[["datum","ingredience_sk","ingredience_rc","nazev","potreba","jednotka"]]


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
        q = d.quantize(Decimal(10) ** (-SCALE), rounding=ROUND_HALF_UP)
        return int((q * (Decimal(10) ** SCALE)).to_integral_value(rounding=ROUND_HALF_UP))

    # --- NOVÁ DATA ---
    df_new = df_new.copy()
    clean_columns_local(df_new)
    to_date_col(df_new, "datum")

    # začínáme vždy s False (nová výpočetní tabulka koupeno neposuzuje)
    df_new["koupeno"] = False

    # klíče a množství (int mikro)
    df_new["__sk"]    = df_new.get("ingredience_sk", "").map(_key_txt)
    df_new["__rc"]    = df_new.get("ingredience_rc", "").map(_key_txt)
    df_new["__qty_i"] = df_new.get("potreba", 0).map(_qty_to_int_micro)

    # --- STARÝ VÝSTUP ---
    try:
        old = pd.read_excel(OUTPUT_EXCEL)
    except Exception:
        # žádná historie → všude koupeno=False (už nastaveno)
        return df_new.drop(columns=["__sk", "__rc", "__qty_i"], errors="ignore")

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

    old_qty_col = find_col(old, ["mnozstvi", "množství", "potreba", "quantity", "qty"])
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
           .agg(prev_qty_i=("__qty_i", "sum"), prev_koupeno=("__k", "max"))
    )
    new_grp = (
        df_new.groupby(key_cols, as_index=False)
              .agg(new_qty_i=("__qty_i", "sum"))
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

    return df_new.drop(columns=["__sk", "__rc", "__qty_i", "keep_true"], errors="ignore")


def compute_plan() -> pd.DataFrame:
    recepty, plan = nacti_data()
    vysledek = spocitej_potrebne_ingredience(recepty, plan)
    # může být prázdný – v takovém případě rovnou vrať
    if vysledek.empty:
        vysledek["koupeno"] = []
        return vysledek
    vysledek = _recalculate_koupeno_against_previous(vysledek)
    return vysledek


# ---------- výpočet polotovarů (přímé SK300 z plánů SK400) --------------------

def spocitej_polotovary(recepty: pd.DataFrame, plan: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Vrátí (df_main, df_details)

    df_main (Prehled):
      ['datum','polotovar_sk','polotovar_rc','nazev','potreba','jednotka']  (bez 'vyrobeno'; doplní se až v pipeline)

    df_details (Detaily):
      ['datum','polotovar_sk','polotovar_rc','final_rc','final_nazev','mnozstvi','jednotka']
    """
    # -- pojmenuj důležité sloupce v receptuře --
    # parent (finální výrobek):
    COL_P_REG = find_col(recepty, ["Reg. č.", "Reg c", "Reg. c", "Reg.č."]) or "Reg. č."
    COL_P_SK  = find_col(recepty, ["SK"]) or "SK"
    # child (komponenta):
    COL_C_REG = find_col(recepty, ["Reg. č..1", "Reg. č. 1", "Reg c 1", "Reg. c.1", "Reg.č..1"]) or "Reg. č..1"
    COL_C_SK  = find_col(recepty, ["SK.1", "SK 1", "sk1", "sk.1"]) or "SK.1"
    COL_C_NAM = find_col(recepty, ["Název 1.1", "Název komponenty", "Nazev 1.1", "Nazev"]) or "Název 1.1"
    COL_QTY   = find_col(recepty, ["Množství", "Mnozstvi", "qty"]) or "Množství"
    COL_MJ    = find_col(recepty, ["MJ evidence", "MJ", "jednotka"]) or "MJ evidence"

    # název finálního výrobku (pokud existuje)
    COL_P_NAME = find_col(recepty, ["Název 1", "Název", "nazev"])

    # -- pojmenuj sloupce v plánu --
    COL_PLAN_REG = find_col(plan, ["reg.č", "reg_c", "reg", "reg. c", "reg c", "reg.c"]) or "reg.č"
    COL_PLAN_QTY = find_col(plan, ["mnozstvi", "množství", "qty"]) or "mnozstvi"

    to_date_col(plan, "datum")
    plan = plan.copy()

    # -- akumulace výsledků --
    rows_main: list[dict] = []
    rows_detail: list[dict] = []

    for _, prow in plan.iterrows():
        final_reg_c = _safe_int(prow.get(COL_PLAN_REG))
        if final_reg_c is None:
            continue
        final_sk = 400  # finální výrobky
        final_qty = float(prow.get(COL_PLAN_QTY, 0) or 0)
        datum = prow.get("datum", None)

        # vyber řádky receptury pro daného rodiče (SK400, Reg. č. = final_reg_c)
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

        # projdi komponenty a vem jen SK300 (přímé polotovary)
        for _, r in sub.iterrows():
            child_sk  = _safe_int(r.get(COL_C_SK))
            child_reg = _safe_int(r.get(COL_C_REG))
            if child_sk != 300 or child_reg is None:
                continue

            mnozstvi_na_kus = float(r.get(COL_QTY, 0) or 0)
            jednotka        = str(r.get(COL_MJ, "") or "").strip()
            child_name      = str(r.get(COL_C_NAM, "") or "").strip()

            req = final_qty * mnozstvi_na_kus  # kolik polotovaru je třeba

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

    # -- do DataFrame + agregace --
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


# ---------- finální pipeline vč. zachování 'vyrobeno' -------------------------

def compute_plan_semifinished() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Plán polotovarů:
      - načte receptury a plán,
      - spočítá přímé SK300 pro SK400,
      - zachová/aktualizuje sloupec 'vyrobeno' (bool, viz logika níže),
      - vytvoří OUTPUT_SEMI_EXCEL se 3 listy: Prehled, Detaily, Polotovary,
      - vrátí (df_main_merged, df_details).
    """
    # 1) načti zdroje
    recepty = pd.read_excel(RECEPTY_FILE, sheet_name="HEO - Kusovníkové vazby platné ")
    plan    = pd.read_excel(PLAN_FILE)
    to_date_col(plan, "datum")

    # 2) spočítej nové tabulky
    df_main, df_details = spocitej_polotovary(recepty, plan)

    # 3) výchozí stav 'vyrobeno' = False
    df_main = df_main.copy()
    df_main["vyrobeno"] = False

    # 4) načti starý přehled (pokud existuje) a zachovej True, pokud se množství nezvýšilo
    try:
        old = pd.read_excel(OUTPUT_SEMI_EXCEL, sheet_name="Prehled").fillna("")
    except Exception:
        try:
            old = pd.read_excel(OUTPUT_SEMI_EXCEL).fillna("")
        except Exception:
            old = pd.DataFrame()

    if not old.empty:
        # normalizace
        old.columns = [str(c).strip() for c in old.columns]
        to_date_col(old, "datum")
        if "vyrobeno" not in old.columns:
            old["vyrobeno"] = False
        old["vyrobeno"] = old["vyrobeno"].map(to_bool_cell_excel).astype(bool)

        # stabilní klíče – použij bezpečné Series, i když sloupce chybí
        old["__sk"]  = _series_or_blank(old, "polotovar_sk").map(_key_txt)
        old["__rc"]  = _series_or_blank(old, "polotovar_rc").map(_key_txt)

        # množství ve starém souboru
        old_qty_col  = "potreba" if "potreba" in old.columns else None
        old["__qty"] = pd.to_numeric(old[old_qty_col], errors="coerce").fillna(0.0) if old_qty_col else 0.0
        old["__k"]   = old["vyrobeno"].astype(bool)

        has_old_date = "datum" in old.columns
        key_old = (["datum"] if has_old_date else []) + ["__sk", "__rc"]

        old_grp = (
            old.groupby(key_old, as_index=False)
               .agg(prev_qty=("__qty", "sum"), prev_vyrobeno=("__k", "max"))
        )

        # připrav nové klíče
        df_main["__sk"]  = df_main["polotovar_sk"].map(_key_txt)
        df_main["__rc"]  = df_main["polotovar_rc"].map(_key_txt)
        df_main["__qty"] = pd.to_numeric(df_main["potreba"], errors="coerce").fillna(0.0)

        key_new = (["datum"] if ("datum" in df_main.columns and has_old_date) else []) + ["__sk", "__rc"]

        new_grp = (
            df_main.groupby(key_new, as_index=False)
                   .agg(new_qty=("__qty", "sum"))
        )

        # merge a logika zachování
        on_cols = key_old if key_old == key_new else ["__sk", "__rc"]
        merged = new_grp.merge(old_grp, on=on_cols, how="left")
        merged["prev_qty"]      = merged["prev_qty"].fillna(0.0)
        merged["prev_vyrobeno"] = merged["prev_vyrobeno"].fillna(False).astype(bool)

        increased = merged["new_qty"] > merged["prev_qty"]
        merged["keep_true"] = (~increased) & merged["prev_vyrobeno"]

        # promítnout zpět na řádky df_main
        df_main = df_main.merge(
            merged[(key_new if key_new else ["__sk", "__rc"]) + ["keep_true"]],
            on=(key_new if key_new else ["__sk", "__rc"]),
            how="left"
        )
        df_main["vyrobeno"] = df_main["vyrobeno"] | df_main["keep_true"].fillna(False)
        df_main.drop(columns=["__sk", "__rc", "__qty", "keep_true"], inplace=True, errors="ignore")

    # 5) zapiš Excel s bloky/listy (Prehled, Detaily, Polotovary)
    ensure_output_semis_excel(df_main, df_details)

    return df_main, df_details
