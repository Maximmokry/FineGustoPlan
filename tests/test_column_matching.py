import pandas as pd
import pytest
from datetime import date as _date
import main as core


def test_find_col_loose_variants():
    df = pd.DataFrame(columns=[
        "Reg. č.", "Množství", "SK", "SK.1"
    ])

    # Reg. č. varianty
    for variant in ["reg. č.", "REG C", "regc", "Reg_c", "reg-c", "reg.č."]:
        assert core.find_col(df, [variant]) == "Reg. č."

    # Množství varianty
    for variant in ["mnozstvi", "MNOZSTVI", "množství"]:
        assert core.find_col(df, [variant]) == "Množství"

    # SK varianty
    for variant in ["sk", "Sk ", " SK"]:
        assert core.find_col(df, [variant]) == "SK"

    # SK.1 varianty
    for variant in ["sk1", "Sk 1", "SK.1"]:
        assert core.find_col(df, [variant]) == "SK.1"


def test_find_col_returns_none_if_not_found():
    df = pd.DataFrame(columns=["A", "B"])
    assert core.find_col(df, ["xyz"]) is None


def test_compute_plan_with_renamed_columns(monkeypatch):
    # Fake recepty + plán s divnými názvy sloupců
    recepty = pd.DataFrame({
        "SK": [400],
        "Reg. č.": [123],
        "SK.1": [200],
        "Reg. č..1": [999],
        "Název 1.1": ["Sůl"],
        "Množství": [2],
        "MJ evidence": ["kg"],
    })
    plan = pd.DataFrame({
        "reg c": [123],          # bez tečky, lowercase
        "mnozstvi": [5],         # bez diakritiky
        "DATUM": ["2025-01-01"]  # capslock
    })

    # monkeypatch na nacti_data()
    def fake_nacti_data():
        return recepty, plan
    monkeypatch.setattr(core, "nacti_data", fake_nacti_data)

    df = core.compute_plan()
    # očekáváme výsledek
    assert not df.empty
    assert set(["datum","ingredience_sk","ingredience_rc","nazev","potreba","jednotka"]).issubset(df.columns)
    # 5 ks * 2 na kus
    assert float(df["potreba"].iloc[0]) == 10.0


@pytest.mark.parametrize("date_col_name", ["DATUM", "Date", "dat", "datum"])
def test_compute_plan_with_various_date_column_names(monkeypatch, date_col_name):
    # Receptura: 400-123 -> obsahuje komponentu 200-999, množství 2 (kg)
    recepty = pd.DataFrame({
        "SK": [400],
        "Reg. č.": [123],
        "SK.1": [200],
        "Reg. č..1": [999],
        "Název 1.1": ["Sůl"],
        "Množství": [2],
        "MJ evidence": ["kg"],
    })
    plan = pd.DataFrame({
        "reg.c": [123],
        "množství": [3],                 # tentokrát s diakritikou
        date_col_name: ["2025-02-03"],   # různé názvy sloupce pro datum
    })

    def fake_nacti_data():
        return recepty, plan
    monkeypatch.setattr(core, "nacti_data", fake_nacti_data)

    df = core.compute_plan()
    assert not df.empty
    # 3 ks * 2 na kus = 6
    assert float(df["potreba"].iloc[0]) == 6.0

    # datum je převeden na datetime.date
    assert isinstance(df["datum"].iloc[0], _date)
