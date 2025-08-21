import pandas as pd
from datetime import date
import pytest

import main  # používáme implementaci v main.py

def test_float_quantity_equality_keeps_true(tmp_path, monkeypatch):
    """
    Starý soubor má koupeno=True a množství 1,10 (text), nové množství 1.1 (float).
    Nemá se resetovat na False, protože množství je numericky stejné.
    """
    out_file = tmp_path/"vysledek.xlsx"
    monkeypatch.setattr("main.OUTPUT_EXCEL", out_file, raising=False)

    old = pd.DataFrame([{
        "datum": date(2025,8,20),
        "ingredience_sk": 150,
        "ingredience_rc": 88,
        "nazev": "Koření Piri Piri 1kg",
        "potreba": "1,10",  # text s čárkou
        "jednotka": "kg",
        "koupeno": True,
    }])
    old.to_excel(out_file, index=False)

    new = pd.DataFrame([{
        "datum": date(2025,8,20),
        "ingredience_sk": 150.0,      # float/objekt
        "ingredience_rc": "88",
        "nazev": "Koření Piri Piri 1kg",
        "potreba": 1.1,               # float
        "jednotka": "kg",
    }])

    df = main._recalculate_koupeno_against_previous(new)
    assert df["koupeno"].tolist() == [True]

def test_float_quantity_increase_resets_false(tmp_path, monkeypatch):
    """
    Staré množství 1.1, nové množství 1.2 → koupeno se musí resetovat na False.
    """
    out_file = tmp_path/"vysledek.xlsx"
    monkeypatch.setattr("main.OUTPUT_EXCEL", out_file, raising=False)

    old = pd.DataFrame([{
        "datum": date(2025,8,20),
        "ingredience_sk": 150,
        "ingredience_rc": 88,
        "nazev": "Koření Piri Piri 1kg",
        "potreba": 1.1,
        "jednotka": "kg",
        "koupeno": True,
    }])
    old.to_excel(out_file, index=False)

    new = pd.DataFrame([{
        "datum": date(2025,8,20),
        "ingredience_sk": "150",
        "ingredience_rc": "88",
        "nazev": "Koření Piri Piri 1kg",
        "potreba": "1,2",  # větší (1.2)
        "jednotka": "kg",
    }])

    df = main._recalculate_koupeno_against_previous(new)
    assert df["koupeno"].tolist() == [False]
