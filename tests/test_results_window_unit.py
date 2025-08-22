# tests/test_results_window_unit.py
import pandas as pd
from gui import results_window as rw

def test_group_buy_map_collects_all_indices():
    df = pd.DataFrame([
        {"datum":"2025-03-01","ingredience_sk":"11","ingredience_rc":"X1","nazev":"Rajčata","jednotka":"kg","potreba":"2","koupeno":False},
        {"datum":"2025-03-02","ingredience_sk":"11","ingredience_rc":"X1","nazev":"Rajčata","jednotka":"kg","potreba":"1.5","koupeno":False},
        {"datum":"2025-03-03","ingredience_sk":"12","ingredience_rc":"Y9","nazev":"Sýr","jednotka":"kg","potreba":"0.5","koupeno":False},
    ])
    rows, buy_map, rowkey_map = rw._build_table_layout(df, "koupeno", aggregate=True)
    # Měl by existovat alespoň jeden -BUY-G- klíč pro (11,X1) a obsahovat indexy {0,1}
    group_btns = [k for k in buy_map if k.startswith("-BUY-G-")]
    assert group_btns, "Agregace nevytvořila skupinová tlačítka"
    found = False
    for k in group_btns:
        idxs = set(buy_map[k])
        if idxs == {0,1}:
            found = True
            break
    assert found, "Skupina (11,X1) nemá všechny zdrojové indexy {0,1}"
