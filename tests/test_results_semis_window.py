# tests/test_results_semis_window.py
import pandas as pd
from gui import results_semis_window as smw

def _df_main():
    return pd.DataFrame([
        # stejný polotovar v jednom týdnu – má se sečíst
        {"datum":"2025-03-03","polotovar_sk":"10","polotovar_rc":"A1","polotovar_nazev":"Těsto","jednotka":"kg","potreba":"2","vyrobeno":False},
        {"datum":"2025-03-05","polotovar_sk":"10","polotovar_rc":"A1","polotovar_nazev":"Těsto","jednotka":"kg","potreba":"3","vyrobeno":False},
        # jiný polotovar – samostatný řádek v agregaci
        {"datum":"2025-03-06","polotovar_sk":"20","polotovar_rc":"B2","polotovar_nazev":"Omáčka","jednotka":"l","potreba":"1.5","vyrobeno":False},
        # jiný týden – další skupina
        {"datum":"2025-03-12","polotovar_sk":"10","polotovar_rc":"A1","polotovar_nazev":"Těsto","jednotka":"kg","potreba":"1","vyrobeno":False},
    ])

def test_weekly_aggregate_sums_and_labels():
    df = _df_main()
    g = smw._aggregate_weekly(df, "vyrobeno")
    # Očekáváme 3 skupiny: (10,A1) v týdnu 3.–9.3. (2+3), (20,B2) v týdnu 3.–9.3., a (10,A1) v týdnu 10.–16.3.
    # Zkontroluj počty a labely
    assert set(g.columns) >= {"_week_start","datum","polotovar_sk","polotovar_rc","polotovar_nazev","jednotka","potreba"}
    # první týden Po–Ne: 2025-03-03 až 2025-03-09
    assert any("03.03.2025" in str(lbl) and "09.03.2025" in str(lbl) for lbl in g["datum"])
    # součet 2+3 pro Těsto
    row = g[(g["polotovar_sk"]=="10") & (g["polotovar_rc"]=="A1") & (g["potreba"]==5.0)]
    assert len(row) == 1
