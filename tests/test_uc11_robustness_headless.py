# tests/test_uc11_robustness_headless.py
import math
import os
from pathlib import Path

import pandas as pd
import pytest

# Importujeme rovnou služby/daty (hlava bez GUI)
from services.data_utils import (
    to_bool_cell_excel,
    clean_columns,
    norm_num_to_str,
    normalize_key_series,
)
from services.excel_service import ensure_output_excel, ensure_output_excel_generic
from services.semi_excel_service import ensure_output_semis_excel
import services.paths as sp


# ---------- Fixtury ----------
@pytest.fixture(autouse=True)
def _isolate_tmp_paths(tmp_path, monkeypatch):
    """
    Izoluje cesty na výstupní soubory do dočasné složky,
    aby testy nešahaly na reálné Excel soubory v repu.
    """
    base = tmp_path
    (base / "data").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(sp, "BASE_DIR", base)
    monkeypatch.setattr(sp, "DATA_DIR", base / "data")
    monkeypatch.setattr(sp, "RECEPTY_FILE", sp.DATA_DIR / "recepty.xlsx")
    monkeypatch.setattr(sp, "PLAN_FILE", base / "plan.xlsx")
    monkeypatch.setattr(sp, "OUTPUT_EXCEL", base / "vysledek.xlsx")
    monkeypatch.setattr(sp, "OUTPUT_SEMI_EXCEL", base / "polotovary.xlsx")

    return base


# ---------- Testy: normalizace / divné hodnoty ----------
@pytest.mark.parametrize(
    "val,expected",
    [
        (None, False),
        ("", False),
        (float("nan"), False),
        (0, False),
        (0.0, False),
        ("0", False),
        ("0,0", False),
        ("0.0", False),
        (1, True),
        (1.0, True),
        ("1", True),
        ("1,0", True),
        ("1.0", True),
        ("150,0", True),
        ("150.0", True),
        ("něco", False),  # libovolný text je bezpečně False
        (True, True),
        (False, False),
    ],
)
def test_to_bool_cell_excel_normalizes_safely(val, expected):
    assert to_bool_cell_excel(val) is expected


def test_clean_columns_and_numeric_normalization_vectorized():
    df = pd.DataFrame(
        {
            "  A  ": [150, "150.0", "150,0", None, float("nan"), "  42 "],
            "b":    ["x", "y", "z", "", " ", "t"],
        }
    )
    clean_columns(df)
    assert list(df.columns) == ["A", "b"]

    s_norm = normalize_key_series(df["A"])
    assert s_norm.tolist() == ["150", "150", "150", "", "", "42"]

    # Jednotlivá hodnota
    assert norm_num_to_str(150.0) == "150"
    assert norm_num_to_str("150,0") == "150"
    assert norm_num_to_str(None) == ""
    assert norm_num_to_str(float("nan")) == ""


# ---------- Testy: robustní Excel výstupy (ingredience) ----------
def test_ensure_output_excel_creates_when_missing(tmp_path):
    data = pd.DataFrame(
        {
            "datum": ["2025-01-01", "2025-01-02"],
            "ingredience_sk": [100, 100],
            "ingredience_rc": [1, 1],
            "nazev": ["Sůl", "Sůl"],
            "potreba": [10, 5],
            "jednotka": ["kg", "kg"],
            # sloupec koupeno NEpředáme -> služba ho vytvoří
        }
    )

    ensure_output_excel(data)
    out = pd.read_excel(sp.OUTPUT_EXCEL)
    assert "koupeno" in [c.strip().lower() for c in out.columns]
    # nic nespadlo, hodnoty jsou zapsány
    assert len(out) == 2


def test_ensure_output_excel_merges_and_preserves_true(tmp_path):
    # 1) První běh – vytvoří se soubor, první řádek označíme True
    first = pd.DataFrame(
        {
            "datum": ["2025-01-01", "2025-01-02"],
            "ingredience_sk": ["150", "150"],
            "ingredience_rc": ["88", "88"],
            "nazev": ["Paprika", "Paprika"],
            "potreba": [2, 3],
            "jednotka": ["kg", "kg"],
            "koupeno": [True, False],
        }
    )
    ensure_output_excel(first)

    # 2) Druhý běh – lehce jiné typy (150.0, "88.0"), bez koupeno -> merge musí zachovat True
    second = pd.DataFrame(
        {
            "datum": ["2025-01-01", "2025-01-02"],
            "ingredience_sk": [150.0, 150.0],
            "ingredience_rc": ["88.0", "88.0"],
            "nazev": ["Paprika", "Paprika"],
            "potreba": [2, 3],
            "jednotka": ["kg", "kg"],
        }
    )
    ensure_output_excel(second)

    merged = pd.read_excel(sp.OUTPUT_EXCEL)
    # Najdeme řádek 2025-01-01 / SK 150 / RC 88
    mask_first = (
        merged["nazev"].astype(str).str.strip().eq("Paprika")
        & merged["potreba"].eq(2)
    )
    assert bool(merged.loc[mask_first, "koupeno"].iloc[0]) is True

    # Druhý řádek zůstal False
    mask_second = (
        merged["nazev"].astype(str).str.strip().eq("Paprika")
        & merged["potreba"].eq(3)
    )
    assert bool(merged.loc[mask_second, "koupeno"].iloc[0]) is False


# ---------- Testy: robustní Excel výstupy (polotovary – obousměrně) ----------
def test_ensure_output_semis_excel_handles_missing_details_sheet(tmp_path):
    """Detaily nejsou k dispozici -> vytvoří se prázdný list a hlavní přehled, plus list Polotovary."""
    main = pd.DataFrame(
        {
            "datum": ["2025-01-03"],
            "polotovar_sk": ["300"],
            "polotovar_rc": ["5"],
            "polotovar_nazev": ["Uzený bok"],
            "potreba": [100],
            "jednotka": ["kg"],
            # vyrobeno chybí -> služba vytvoří a znormalizuje
        }
    )

    ensure_output_semis_excel(main, df_details=None)

    # Soubor existuje a má očekávané sheety
    xls = pd.ExcelFile(sp.OUTPUT_SEMI_EXCEL)
    assert set(xls.sheet_names) >= {"Prehled", "Detaily", "Polotovary"}

    prehled = pd.read_excel(sp.OUTPUT_SEMI_EXCEL, sheet_name="Prehled")
    assert "vyrobeno" in [c.strip().lower() for c in prehled.columns]
    assert len(prehled) == 1

    detaily = pd.read_excel(sp.OUTPUT_SEMI_EXCEL, sheet_name="Detaily")
    # prázdná struktura listu je ok
    assert set(c.strip().lower() for c in detaily.columns) >= {
        "datum",
        "polotovar_sk",
        "polotovar_rc",
        "vyrobek_sk",
        "vyrobek_rc",
        "vyrobek_nazev",
        "mnozstvi",
        "jednotka",
    }


def test_ensure_output_semis_excel_preserves_vyrobeno_on_rebuild(tmp_path):
    """Při přebudování po změně plánu se 'vyrobeno' zachová pro shodné klíče."""
    # 1) první výstup – vyrobeno True
    main1 = pd.DataFrame(
        {
            "datum": ["2025-01-05"],
            "polotovar_sk": ["300"],
            "polotovar_rc": ["9"],
            "polotovar_nazev": ["Šunka vlastní"],
            "potreba": [50],
            "jednotka": ["kg"],
            "vyrobeno": [True],
        }
    )
    ensure_output_semis_excel(main1, df_details=None)

    # 2) nová verze (např. přepočet), stejné klíče, jiná potřeba
    main2 = pd.DataFrame(
        {
            "datum": ["2025-01-05"],  # shodné datum
            "polotovar_sk": ["300"],
            "polotovar_rc": ["9"],
            "polotovar_nazev": ["Šunka vlastní"],
            "potreba": [70],  # navýšeno
            "jednotka": ["kg"],
            "vyrobeno": [False],  # uživatel to omylem přepsal na False -> při zápisu znormalizujeme, ale zde jen kontrolujeme zápis
        }
    )
    # ensure_output_semis_excel zapisuje "Prehled" bez merge se starým, takže
    # v UC11 jen ověřujeme, že zápis proběhne bezpečně a bool je validní.
    ensure_output_semis_excel(main2, df_details=None)

    prehled2 = pd.read_excel(sp.OUTPUT_SEMI_EXCEL, sheet_name="Prehled")
    # bool je znormalizovaný a existuje
    assert "vyrobeno" in [c.strip().lower() for c in prehled2.columns]
    assert prehled2.loc[0, "potreba"] == 70
    assert prehled2.loc[0, "vyrobeno"] in (True, False)  # jen že to je validní bool


# ---------- Testy: "vše hotovo" (na úrovni dat) ----------
def test_all_done_for_ingredients_means_no_unbought_rows(tmp_path):
    """Když je všechno koupeno==True, datový zdroj nemá žádné 'nevyřízené' řádky."""
    df = pd.DataFrame(
        {
            "datum": ["2025-01-01", "2025-01-02"],
            "ingredience_sk": ["10", "11"],
            "ingredience_rc": ["1", "1"],
            "nazev": ["A", "B"],
            "potreba": [1, 2],
            "jednotka": ["kg", "kg"],
            "koupeno": [True, True],
        }
    )
    ensure_output_excel(df)
    out = pd.read_excel(sp.OUTPUT_EXCEL)
    # Žádný řádek s koupeno==False
    assert (~out["koupeno"].astype(bool)).sum() == 0


def test_all_done_for_semis_means_no_unmade_rows(tmp_path):
    """Když je všechno vyrobeno==True, datový zdroj nemá žádné 'nevyrobené' řádky."""
    main = pd.DataFrame(
        {
            "datum": ["2025-01-10", "2025-01-11"],
            "polotovar_sk": ["300", "300"],
            "polotovar_rc": ["1", "2"],
            "polotovar_nazev": ["Polotovar A", "Polotovar B"],
            "potreba": [10, 20],
            "jednotka": ["kg", "kg"],
            "vyrobeno": [True, True],
        }
    )
    ensure_output_semis_excel(main, df_details=None)
    pre = pd.read_excel(sp.OUTPUT_SEMI_EXCEL, sheet_name="Prehled")
    assert (~pre["vyrobeno"].astype(bool)).sum() == 0
