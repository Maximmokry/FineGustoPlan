import builtins
import io
import sys
import pandas as pd
from datetime import date
import pytest

# Importujeme interní pomocné funkce z GUI (jsou s podtržítkem, ale to nevadí pro test)
from gui.results_window import (
    _key_txt,
    _filter_unbought,
    _build_table_layout,
    _force_bool_col,
    DEBUG_CFG,
)

# Pomocný DataFrame pro testy
def _make_df():
    df = pd.DataFrame([
        # stejné SK/RC (piri piri) na různé dny
        {"datum": date(2025,8,20), "ingredience_sk": 150, "ingredience_rc": 88, "nazev": "Koření Piri Piri 1kg", "potreba": 3.6568, "jednotka":"kg", "koupeno": False},
        {"datum": date(2025,8,21), "ingredience_sk": "150.0", "ingredience_rc": "88", "nazev": "Koření Piri Piri 1kg", "potreba": 7.3136, "jednotka":"kg", "koupeno": False},
        # jiná položka
        {"datum": date(2025,8,21), "ingredience_sk": 200, "ingredience_rc": 33, "nazev": "Jiná ingredience", "potreba": 1, "jednotka":"ks", "koupeno": True},
    ])
    return df

def test_key_txt_normalizes_numbers_and_commas():
    assert _key_txt(150) == "150"
    assert _key_txt("150.0") == "150"
    assert _key_txt("150,0") == "150"
    assert _key_txt("00150") == "150"  # přes int(float(...))
    assert _key_txt(None) == ""

def test_filter_unbought_respects_bool():
    df = _make_df()
    # force bool (může být string/float)
    _force_bool_col(df, "koupeno")
    out = _filter_unbought(df, "koupeno")
    # měl by vyřadit koupeno=True (poslední řádek)
    assert len(out) == 2
    assert set(out["nazev"]) == {"Koření Piri Piri 1kg"}

def test_build_table_layout_non_aggregate_headers_and_mapping():
    df = _make_df()
    rows, buy_map, rowkey_map = _build_table_layout(df, "koupeno", aggregate=False)
    assert rows is not None
    # první řádek je hlavička se 7 buňkami
    header = rows[0]
    assert len(header) == 7
    # musí existovat buy_map pro nekoupené dva řádky
    assert len(buy_map) == 2
    # rowkey_map by měl obsahovat indexy původního df pro nekoupené řádky
    assert len(rowkey_map) == 2
    # Každé tlačítko mapuje právě na jeden index
    for k, idxs in buy_map.items():
        assert isinstance(idxs, list) and len(idxs) == 1
        assert idxs[0] in rowkey_map

def test_build_table_layout_aggregate_headers_and_grouping_with_unit():
    df = _make_df()
    rows, buy_map, rowkey_map = _build_table_layout(df, "koupeno", aggregate=True)
    assert rows is not None
    header = rows[0]
    # hlavička: Datum, SK, Reg.č., Název, Množství, "", Akce
    assert len(header) == 7
    # druhá hlavičková buňka (počet 6) je prázdný titulek pro jednotku
    assert header[5].DisplayText == ""  # PySimpleGUIQt Text

    # v agregaci se dva piri-piri řádky musí sloučit do jednoho tlačítka
    # buy_map má mít právě 1 položku pro piri piri + 0 pro tu True položku
    # => tedy 1 celkem (protože True položka je odfiltrována)
    assert len(buy_map) == 1

    # a tato 1 položka musí mapovat na 2 indexy (obě data piri-piri)
    idxs = list(buy_map.values())[0]
    assert sorted(idxs) == [0, 1]  # první dva řádky v _make_df()

def test_piri_piri_non_aggregate_marks_only_one_row_simulation():
    """Simulace kliknutí v neagregovaném layoutu: tlačítko mapuje na 1 index."""
    df = _make_df()
    rows, buy_map, rowkey_map = _build_table_layout(df, "koupeno", aggregate=False)
    # vezmeme první tlačítko a jeho index a "označíme" ho True
    first_btn, first_idxs = next(iter(buy_map.items()))
    idx = first_idxs[0]
    df.loc[idx, "koupeno"] = True
    # po přestavbě by měl zbývat už jen druhý nekoupený piri-piri
    rows2, buy_map2, _ = _build_table_layout(df, "koupeno", aggregate=False)
    assert len(buy_map2) == 1  # už jen jeden řádek piri-piri
    # a index v mapě není ten původně označený
    new_idx = list(buy_map2.values())[0][0]
    assert new_idx != idx
