import pandas as pd
from datetime import date

from gui.results_window import (
    _filter_unbought,
    _build_table_layout,
    _force_bool_col,
    DEBUG_CFG,
)

def _make_df():
    return pd.DataFrame([
        {"datum": date(2025,8,20), "ingredience_sk": 150,    "ingredience_rc": 88, "nazev": "Koření Piri Piri 1kg", "potreba": 3.6568, "jednotka":"kg", "koupeno": False},
        {"datum": date(2025,8,21), "ingredience_sk": "150.0","ingredience_rc": "88","nazev": "Koření Piri Piri 1kg", "potreba": 7.3136, "jednotka":"kg", "koupeno": False},
        {"datum": date(2025,8,21), "ingredience_sk": 200,    "ingredience_rc": 33, "nazev": "Jiná ingredience",      "potreba": 1,      "jednotka":"ks", "koupeno": True},
    ])

def test_filter_unbought_respects_bool():
    df = _make_df()
    _force_bool_col(df, "koupeno")
    out = _filter_unbought(df, "koupeno")
    assert len(out) == 2
    assert set(out["nazev"]) == {"Koření Piri Piri 1kg"}

def test_build_table_layout_non_aggregate_headers_and_mapping():
    df = _make_df()
    rows, buy_map, rowkey_map = _build_table_layout(df, "koupeno", aggregate=False)
    assert rows is not None
    header = rows[0]
    assert len(header) == 7
    assert len(buy_map) == 2
    assert len(rowkey_map) == 2
    for _, idxs in buy_map.items():
        assert isinstance(idxs, list) and len(idxs) == 1
        assert idxs[0] in rowkey_map

def test_build_table_layout_aggregate_headers_and_grouping_with_unit():
    df = _make_df()
    rows, buy_map, rowkey_map = _build_table_layout(df, "koupeno", aggregate=True)
    assert rows is not None
    header = rows[0]
    assert len(header) == 7
    assert getattr(header[5], "DisplayText", "") == ""  # prázdný titulek pro jednotku
    # 2 piri-piri řádky musí spadnout do jedné skupiny
    assert len(buy_map) == 1
    idxs = list(buy_map.values())[0]
    assert sorted(idxs) == [0, 1]

def test_piri_piri_non_aggregate_marks_only_one_row_simulation():
    df = _make_df()
    rows, buy_map, _ = _build_table_layout(df, "koupeno", aggregate=False)
    first_btn, first_idxs = next(iter(buy_map.items()))
    idx = first_idxs[0]
    df.loc[idx, "koupeno"] = True
    rows2, buy_map2, _ = _build_table_layout(df, "koupeno", aggregate=False)
    assert len(buy_map2) == 1
    new_idx = list(buy_map2.values())[0][0]
    assert new_idx != idx

def test_aggregation_normalizes_keys_implicitly():
    """Nepřímo ověříme normalizaci (150, '150.0', '150,0' apod.) přes agregaci."""
    df = _make_df()
    # přidáme variantu s čárkou, která by měla spadnout do stejné skupiny
    df = pd.concat([df, pd.DataFrame([{
        "datum": date(2025,8,22), "ingredience_sk": "150,0", "ingredience_rc": "88",
        "nazev": "Koření Piri Piri 1kg", "potreba": 1.0, "jednotka":"kg", "koupeno": False
    }])], ignore_index=True)
    rows, buy_map, _ = _build_table_layout(df, "koupeno", aggregate=True)
    # stále jen 1 skupina pro piri-piri
    assert len(buy_map) == 1
    assert sorted(list(buy_map.values())[0]) == [0, 1, 3]
