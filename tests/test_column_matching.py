import pandas as pd
import pytest
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

def test_compute_plan_with_renamed_columns(tmp_path, monkeypatch):
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
        "reg c": [123],         # schválně bez tečky a lowercase
        "mnozstvi": [5],        # bez diakritiky
        "DATUM": ["2025-01-01"] # capslock
    })

    # monkeypatch na nacti_data()
    def fake_nacti_data():
        return recepty, plan
    monkeypatch.setattr(core, "nacti_data", fake_nacti_data)

    df = core.compute_plan()
    # očekáváme, že se správně dopočítá ingredience
    assert not df.empty
    assert "ingredience_sk" in df.columns
    assert "ingredience_rc" in df.columns
    assert df["potreba"].iloc[0] == 10  # 5 ks * množství 2
