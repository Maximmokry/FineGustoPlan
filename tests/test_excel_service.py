# tests/test_excel_service.py
import pandas as pd
from datetime import date
from services.excel_service import ensure_output_excel

def _base_rows(koupeno_vals):
    """Pomůcka: vytvoří dvě řádky se stejnými klíči a danými hodnotami 'koupeno'."""
    return pd.DataFrame([
        {
            "datum": date(2025, 1, 1),
            "ingredience_sk": 10,
            "ingredience_rc": 100,
            "nazev": "A",
            "potreba": 5,
            "jednotka": "kg",
            "koupeno": koupeno_vals[0],
        },
        {
            "datum": date(2025, 1, 1),
            "ingredience_sk": 11,
            "ingredience_rc": 101,
            "nazev": "B",
            "potreba": 2,
            "jednotka": "ks",
            "koupeno": koupeno_vals[1],
        },
    ])

def test_first_write_creates_file_and_bools(tmp_output):
    df_new = _base_rows([True, False])
    ensure_output_excel(df_new)
    assert tmp_output.exists()

    back = pd.read_excel(tmp_output)
    # Ověříme, že hodnoty se dají číst jako bool a sedí
    got = back["koupeno"].astype(bool).tolist()
    assert got == [True, False]

def test_merge_prefers_new_values_over_old(tmp_output):
    # 1) Starý soubor říká True/True
    old_df = _base_rows([True, True])
    ensure_output_excel(old_df)

    # 2) Nová data říkají False/True -> nová hodnota má mít přednost
    new_df = _base_rows([False, True])
    ensure_output_excel(new_df)

    back = pd.read_excel(tmp_output)
    got = back.sort_values(["ingredience_sk","ingredience_rc"])["koupeno"].astype(bool).tolist()
    assert got == [False, True]

def test_merge_removes_helper_columns(tmp_output):
    # Zápis starého
    old_df = _base_rows([True, False])
    ensure_output_excel(old_df)
    # Nový zápis se stejnými klíči (způsobí merge s *_old interně)
    new_df = _base_rows([True, True])
    ensure_output_excel(new_df)

    back = pd.read_excel(tmp_output)
    # nesmí zůstat žádné *_old ani duplicitní koupeno sloupce
    assert not any(col.endswith("_old") for col in back.columns)
    assert "koupeno" in back.columns
    assert back.columns.tolist().count("koupeno") == 1

def test_old_file_with_various_koupeno_values_is_normalized(tmp_output):
    # Vytvoříme "starý" soubor s mixem hodnot; ensure_output_excel ho normalizuje
    old = pd.DataFrame([
        {
            "datum": date(2025, 1, 1),
            "ingredience_sk": 10,
            "ingredience_rc": 100,
            "nazev": "A",
            "potreba": 5,
            "jednotka": "kg",
            "koupeno": "1",  # textová jednička
        },
        {
            "datum": date(2025, 1, 1),
            "ingredience_sk": 11,
            "ingredience_rc": 101,
            "nazev": "B",
            "potreba": 2,
            "jednotka": "ks",
            "koupeno": 0,    # nula
        },
    ])
    ensure_output_excel(old)

    # Nová data BEZ změny koupeno (ale ensure_output_excel ho stejně vytvoří),
    # hodnoty by neměly zůstat ve starých "stringových" formách – čteme jako bool
    new = old.drop(columns=["koupeno"])
    ensure_output_excel(new)

    back = pd.read_excel(tmp_output)
    got = back.sort_values(["ingredience_sk","ingredience_rc"])["koupeno"].astype(bool).tolist()
    assert got == [True, False]  # (A -> True), (B -> False)
