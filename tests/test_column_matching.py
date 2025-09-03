import sys
import pandas as pd
import pytest
from datetime import date as _date

from services.compute_common import find_col

# Nová pipeline (graf)
from services.data_loader import nacti_data as _nacti_data
from services.graph_model import Graph
from services.graph_builder import (
    build_nodes_from_recipes,
    expand_plan_to_demands,
    attach_status_from_excels,
)
from services.projections.ingredients_projection import to_ingredients_df


# --- Lokální aliasy a wrappry, aby šel snadno monkeypatch ---
def nacti_data():
    """Alias na loader; v testech se dá monkeypatchnout přímo v tomto modulu."""
    return _nacti_data()


def compute_plan() -> pd.DataFrame:
    """
    Testovací wrapper nad novou grafovou pipeline:
      recepty + plán -> graf -> projekce ingrediencí (vysledek.xlsx formát)
    """
    recepty, plan = nacti_data()
    nodes = build_nodes_from_recipes(recepty)
    g = Graph(nodes=nodes, demands=expand_plan_to_demands(plan, nodes))
    attach_status_from_excels(g)  # přenese koupeno/vyrobeno ze stávajících Excelů (pokud jsou)
    return to_ingredients_df(g)


# ---------------------------- původní testy ----------------------------

def test_find_col_loose_variants():
    df = pd.DataFrame(columns=[
        "Reg. č.", "Množství", "SK", "SK.1"
    ])

    # Reg. č. varianty
    for variant in ["reg. č.", "REG C", "regc", "Reg_c", "reg-c", "reg.č."]:
        assert find_col(df, [variant]) == "Reg. č."

    # Množství varianty
    for variant in ["mnozstvi", "MNOZSTVI", "množství"]:
        assert find_col(df, [variant]) == "Množství"

    # SK varianty
    for variant in ["sk", "Sk ", " SK"]:
        assert find_col(df, [variant]) == "SK"

    # SK.1 varianty
    for variant in ["sk1", "Sk 1", "SK.1"]:
        assert find_col(df, [variant]) == "SK.1"


def test_find_col_returns_none_if_not_found():
    df = pd.DataFrame(columns=["A", "B"])
    assert find_col(df, ["xyz"]) is None


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

    # monkeypatch na nacti_data() v TOMTO modulu
    def fake_nacti_data():
        return recepty, plan

    monkeypatch.setattr(sys.modules[__name__], "nacti_data", fake_nacti_data)

    df = compute_plan()
    # očekáváme výsledek
    assert not df.empty
    assert set(["datum", "ingredience_sk", "ingredience_rc", "nazev", "potreba", "jednotka"]).issubset(df.columns)
    # 5 ks * 2 na kus
    assert float(df["potreba"].iloc[0]) == 10.0


@pytest.mark.parametrize("date_col_name", ["DATUM", "Date", "datum"])
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

    # monkeypatch opět do tohoto modulu
    monkeypatch.setattr(sys.modules[__name__], "nacti_data", fake_nacti_data)

    df = compute_plan()
    assert not df.empty
    # 3 ks * 2 na kus = 6
    assert float(df["potreba"].iloc[0]) == 6.0

    # datum je převeden na datetime.date
    assert isinstance(df["datum"].iloc[0], _date)
