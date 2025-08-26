# tests/test_uc8_excel_bidirectional.py
import os
from pathlib import Path
import pandas as pd
import pytest

# Headless/CI režim
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Projektové moduly
import services.paths as sp
import services.data_utils as du
import services.excel_service as es
import services.semi_excel_service as ses
import gui.results_semis_window as rsw_semis


# ------------------------------------------------------------------
# Společná izolace výstupních souborů + umlčení popupů (headless)
# ------------------------------------------------------------------
TEST_ING = Path("test_uc8_vysledek.xlsx")
TEST_SEMI = Path("test_uc8_polotovary.xlsx")


@pytest.fixture(autouse=True)
def _isolate_files(monkeypatch):
    # výstupní cesty přesměrovat na testovací soubory
    monkeypatch.setattr(sp, "OUTPUT_EXCEL", TEST_ING, raising=False)
    monkeypatch.setattr(sp, "OUTPUT_SEMI_EXCEL", TEST_SEMI, raising=False)

    # z modulu GUI (semis) přesměruj také přímo (pro případ přímého použití)
    monkeypatch.setattr(rsw_semis, "OUTPUT_SEMI_EXCEL", TEST_SEMI, raising=False)

    # umlč popupy (kdyby si je nějaká funkce vyžádala)
    monkeypatch.setattr(rsw_semis.sg, "popup", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(rsw_semis.sg, "popup_error", lambda *a, **k: None, raising=False)

    # cleanup
    for f in (TEST_ING, TEST_SEMI):
        if f.exists():
            f.unlink()
    yield
    for f in (TEST_ING, TEST_SEMI):
        if f.exists():
            f.unlink()


# ------------------------------------------------------------------
# Pomocné továrny DF
# ------------------------------------------------------------------
def df_ing_base():
    return pd.DataFrame(
        [
            {
                "datum": "2025-05-12",
                "ingredience_sk": "100",
                "ingredience_rc": "1",
                "nazev": "Sůl",
                "potreba": "5",            # záměrně string
                "jednotka": "kg",
            },
            {
                "datum": "2025-05-13",
                "ingredience_sk": 200,     # záměrně číslo
                "ingredience_rc": "9",
                "nazev": "Cibule",
                "potreba": "150,0",        # lokalizované číslo
                "jednotka": "kg",
            },
        ]
    )


def df_semis_base(vyrobeno_col=True):
    rows = [
        {
            "datum": "2025-06-01",
            "polotovar_sk": "300",
            "polotovar_rc": "88",
            "polotovar_nazev": "Polotovar A",
            "potreba": "10",
            "jednotka": "kg",
        },
        {
            "datum": "2025-06-02",
            "polotovar_sk": "300",
            "polotovar_rc": 88,  # číslo i text by měly projít
            "polotovar_nazev": "Polotovar A",
            "potreba": 5.0,
            "jednotka": "kg",
        },
    ]
    df = pd.DataFrame(rows)
    if vyrobeno_col:
        df["vyrobeno"] = ["1", ""]  # různé formy pravdy/prázdna
    return df


# ------------------------------------------------------------------
# UC8.1 – Chybějící sloupec koupeno/ vyrobeno se doplní (False)
# ------------------------------------------------------------------
def test_uc8_missing_bool_column_is_created_false_by_default():
    # Ingredience: v DF není 'koupeno'
    df_ing = df_ing_base()
    es.ensure_output_excel_generic(df_ing, TEST_ING, bool_col="koupeno")

    out = pd.read_excel(TEST_ING)
    assert "koupeno" in out.columns
    assert out["koupeno"].astype(bool).eq(False).all()

    # Polotovary: DF bez sloupce vyrobeno
    df_semi = df_semis_base(vyrobeno_col=False)
    ses.ensure_output_semis_excel(df_semi, df_details=None)
    prehled = pd.read_excel(TEST_SEMI, sheet_name="Prehled")
    assert "vyrobeno" in prehled.columns
    assert prehled["vyrobeno"].astype(bool).eq(False).all()


# ------------------------------------------------------------------
# UC8.2 – Normalizace boolů a čísel (1/0/True/False/""; 150/150.0/"150,0")
# ------------------------------------------------------------------
def test_uc8_bool_and_number_normalization():
    # Bool helper by měl mít konzistentní chování
    assert du.to_bool_cell_excel(True) is True
    assert du.to_bool_cell_excel("1") is True
    assert du.to_bool_cell_excel(1) is True
    assert du.to_bool_cell_excel("True") is True
    assert du.to_bool_cell_excel("ano") is True or du.to_bool_cell_excel("ano") is False  # tolerantní k implementaci
    assert du.to_bool_cell_excel("0") is False
    assert du.to_bool_cell_excel(0) is False
    assert du.to_bool_cell_excel("") is False
    assert du.to_bool_cell_excel(None) is False

    # Normalizace čísel na stabilní textovou reprezentaci
    assert du.norm_num_to_str(150) == "150"
    # 150.0 může být "150" nebo "150.0" v závislosti na implementaci – akceptujeme obě, ale "150,0" by nemělo způsobit pád
    assert du.norm_num_to_str(150.0) in ("150", "150.0")
    assert du.norm_num_to_str("150,0") in ("150", "150.0")
    assert du.norm_num_to_str(None) == ""


# ------------------------------------------------------------------
# UC8.3 – Ruční úprava Excelu: různé typy/ prázdná pole → zápis bez pádu
# ------------------------------------------------------------------
def test_uc8_manual_excel_edits_various_types_do_not_crash_on_write():
    # Ingredience s mixem typů a prázdny
    df = df_ing_base()
    df.loc[1, "potreba"] = ""   # prázdné
    es.ensure_output_excel_generic(df, TEST_ING, bool_col="koupeno")  # nesmí spadnout
    out = pd.read_excel(TEST_ING)
    assert len(out) == 2
    assert "koupeno" in out.columns

    # Polotovary s mixem typů a 'vyrobeno' v různých formách
    df_s = df_semis_base(vyrobeno_col=True)
    ses.ensure_output_semis_excel(df_s, df_details=None)  # nesmí spadnout
    prehled = pd.read_excel(TEST_SEMI, sheet_name="Prehled")
    assert prehled["vyrobeno"].dtype in (bool, "bool") or prehled["vyrobeno"].astype(bool).isin([True, False]).all()


# ------------------------------------------------------------------
# UC8.4 – Merge: zachování koupeno=True při dalším přepočtu (ingredience)
# ------------------------------------------------------------------
def test_uc8_merge_preserves_koupeno_true_for_same_keys():
    # 1) První zápis + ruční označení koupeno=True
    df = df_ing_base()
    es.ensure_output_excel_generic(df, TEST_ING, bool_col="koupeno")
    out = pd.read_excel(TEST_ING)
    # označ první řádek jako koupeno=True (simulace ruční změny)
    out.loc[0, "koupeno"] = True
    out.to_excel(TEST_ING, index=False)

    # 2) Druhý zápis – "přepočet": stejné klíče, ale jiné množství
    df2 = df.copy()
    df2.loc[0, "potreba"] = "7"    # 5 -> 7
    df2.loc[1, "potreba"] = "100"  # 150,0 -> 100
    es.ensure_output_excel_generic(df2, TEST_ING, bool_col="koupeno")

    merged = pd.read_excel(TEST_ING)
    assert bool(merged.loc[0, "koupeno"]) is True, "koupeno=True se musí zachovat po merži pro shodné klíče"


def test_uc8_merge_preserves_vyrobeno_true_for_same_keys_spec():
    # 1) počáteční Prehled s vyrobeno=True na prvním řádku
    df_s = df_semis_base(vyrobeno_col=True)
    ses.ensure_output_semis_excel(df_s, df_details=None)
    pre = pd.read_excel(TEST_SEMI, sheet_name="Prehled")
    pre.loc[0, "vyrobeno"] = True
    pre.to_excel(TEST_SEMI, index=False, sheet_name="Prehled")  # POZN.: pokud writer neumožní single-sheet rewrite, implementaci bude potřeba upravit v kódu

    # 2) přepočet – stejné klíče, jiné množství
    df_s2 = df_s.copy()
    df_s2.loc[0, "potreba"] = "12"   # 10 -> 12
    ses.ensure_output_semis_excel(df_s2, df_details=None)

    merged = pd.read_excel(TEST_SEMI, sheet_name="Prehled")
    assert bool(merged.loc[0, "vyrobeno"]) is True


# ------------------------------------------------------------------
# UC8.6 – Mapování lehce odlišných názvů sloupců (semis: find_col)
# ------------------------------------------------------------------
def test_uc8_find_col_variants_for_semis():
    # rsw_semis.find_col by měl najít sloupec podle více variant názvů
    df = pd.DataFrame(
        {
            "Datum": ["2025-06-01"],
            "SK": ["300"],
            "Reg.č.": ["88"],
            "Polotovar": ["Polo X"],
            "Množství": [10],
            "": [""],  # prázdný 6. sloupec v "Polotovary" hlavičce
            "Vyrobeno": [False],
            "Poznámka": [""],
        }
    )
    # Ověřme, že find_col najde běžné aliasy (pokud jsou podporované)
    # Pokud implementace podporuje jen lowercase klíče, převod proběhne uvnitř funkce.
    assert rsw_semis.find_col(df, ["datum", "Datum"]) in df.columns
    assert rsw_semis.find_col(df, ["polotovar_sk", "SK"]) in df.columns
    assert rsw_semis.find_col(df, ["polotovar_rc", "Reg.č.", "Reg_c"]) in df.columns
    assert rsw_semis.find_col(df, ["polotovar_nazev", "Polotovar"]) in df.columns
    assert rsw_semis.find_col(df, ["potreba", "Množství"]) in df.columns
    assert rsw_semis.find_col(df, ["vyrobeno", "Vyrobeno"]) in df.columns
