# tests/test_compute_plan.py
import pandas as pd
from datetime import date
from services.ingredients_logic import nacti_data, compute_plan
from services.ingredients_logic import _recalculate_koupeno_against_previous

# Pomocná továrna na jednoduchý kusovník a plán
def _fake_recepty(sk_parent=400, reg_parent=111, sk_child=150, reg_child=555, qty_per_unit=2.0, mj="kg", nazev="Koření Piri Piri 1kg"):
    """
    Vytvoří DataFrame se stejným schématem, jaké očekává main.rozloz_vyrobek:
    - Rodič: sloupce "Reg. č.", "SK"
    - Potomek: "Reg. č..1", "Název 1.1", "Množství", "MJ evidence", "SK.1"
    """
    return pd.DataFrame([{
        "Reg. č.": reg_parent,
        "SK": sk_parent,
        "Reg. č..1": reg_child,
        "Název 1.1": nazev,
        "Množství": qty_per_unit,
        "MJ evidence": mj,
        "SK.1": sk_child,
    }])

def _fake_plan(reg_parent=111, mnozstvi=1.0, d=date(2025, 1, 1)):
    return pd.DataFrame([{
        "reg.č": reg_parent,
        "mnozstvi": mnozstvi,
        "datum": d,
    }])


def test_compute_plan_first_run_sets_koupeno_false(tmp_output, monkeypatch):
    """
    První běh: neexistuje žádný starý výsledek → 'koupeno' musí být False.
    """
    # Přesměruj OUTPUT_EXCEL i v modulu main (konstanta importovaná by-value)
    monkeypatch.setattr("services.ingredients_logic.OUTPUT_EXCEL", tmp_output, raising=False)

    # Stub nacti_data() → žádné čtení z disku
    recepty_df = _fake_recepty(qty_per_unit=2.0)
    plan_df = _fake_plan(mnozstvi=1.0)
    monkeypatch.setattr("services.ingredients_logic.nacti_data", lambda: (recepty_df, plan_df))

    out = compute_plan()

    # Očekáváme jeden řádek s child SK/RC a potřeba = 2.0, koupeno=False
    assert len(out) == 1
    row = out.iloc[0]
    assert int(row["ingredience_sk"]) == 150
    assert int(row["ingredience_rc"]) == 555
    assert float(row["potreba"]) == 2.0
    assert bool(row["koupeno"]) is False


def test_compute_plan_resets_koupeno_when_quantity_increases(tmp_output, monkeypatch):
    """
    Když se nové množství zvýší oproti starému souboru, koupeno se resetuje na False.
    """
    # Přesměruj OUTPUT_EXCEL v modulu main
    monkeypatch.setattr("services.ingredients_logic.nacti_data", lambda: (recepty_df, plan_df))

    # 1) Připrav "starý" výsledek s menším množstvím a koupeno=True
    old = pd.DataFrame([{
        "datum": date(2025, 1, 1),
        "ingredience_sk": 150,
        "ingredience_rc": 555,
        "nazev": "Koření Piri Piri 1kg",
        "potreba": 1.0,
        "jednotka": "kg",
        "koupeno": True,
    }])
    old.to_excel(tmp_output, index=False)

    # 2) Nová data budou mít větší potřebu (2.0) → musí resetovat koupeno=False
    recepty_df = _fake_recepty(qty_per_unit=2.0)   # 1 kus → 2.0 kg
    plan_df = _fake_plan(mnozstvi=1.0)             # plán na 1 kus (=> 2.0 kg)
    monkeypatch.setattr("services.ingredients_logic.nacti_data", lambda: (recepty_df, plan_df))

    out = compute_plan()
    assert len(out) == 1
    row = out.iloc[0]
    assert float(row["potreba"]) == 2.0
    assert bool(row["koupeno"]) is False
