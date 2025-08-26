# tests/test_uc9_rebuild_after_plan_change.py
import os
from pathlib import Path
import pandas as pd
import pytest

# Headless/CI režim
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Projektové moduly
import services.paths as sp
import services.excel_service as es
import services.semi_excel_service as ses


ING_OUT = Path("test_uc9_vysledek.xlsx")
SEMI_OUT = Path("test_uc9_polotovary.xlsx")


# ------------------------------- Fixtures -------------------------------

@pytest.fixture(autouse=True)
def _isolate_outputs(monkeypatch):
    monkeypatch.setattr(sp, "OUTPUT_EXCEL", ING_OUT, raising=False)
    monkeypatch.setattr(sp, "OUTPUT_SEMI_EXCEL", SEMI_OUT, raising=False)

    for f in (ING_OUT, SEMI_OUT):
        if f.exists():
            f.unlink()
    yield
    for f in (ING_OUT, SEMI_OUT):
        if f.exists():
            f.unlink()


def df_ing(a=5, b=3):
    """Ingredience: 2 položky (Sůl a Cibule) – klíče musí zůstat stabilní."""
    return pd.DataFrame(
        [
            {"datum": "2025-05-12", "ingredience_sk": "100", "ingredience_rc": "1", "nazev": "Sůl",    "potreba": a, "jednotka": "kg"},
            {"datum": "2025-05-13", "ingredience_sk": "200", "ingredience_rc": "9", "nazev": "Cibule", "potreba": b, "jednotka": "kg"},
        ]
    )


def df_semis(p1=10, p2=20, include_second=True):
    """Polotovary (Prehled): dva dny stejného polotovaru; optionalně druhý řádek vynechám (zmizení)."""
    rows = [
        {"datum": "2025-06-01", "polotovar_sk": "300", "polotovar_rc": "88", "polotovar_nazev": "Polotovar A", "potreba": p1, "jednotka": "kg", "vyrobeno": False}
    ]
    if include_second:
        rows.append({"datum": "2025-06-02", "polotovar_sk": "300", "polotovar_rc": "88", "polotovar_nazev": "Polotovar A", "potreba": p2, "jednotka": "kg", "vyrobeno": False})
    return pd.DataFrame(rows)


# ------------------------------- UC9 – Ingredience -------------------------------

def test_uc9_ing_increase_preserves_koupeno_and_updates_quantity():
    # 1) první výpočet / zápis
    es.ensure_output_excel_generic(df_ing(a=100, b=50), ING_OUT, bool_col="koupeno")
    base = pd.read_excel(ING_OUT)

    # označím Sůl jako koupeno=True (ruční zásah uživatele)
    mask_sul = (base["ingredience_sk"].astype(str).str.strip() == "100") & \
               (base["ingredience_rc"].astype(str).str.strip() == "1") & \
               (base["nazev"].astype(str).str.strip() == "Sůl")
    base.loc[mask_sul, "koupeno"] = True
    base.to_excel(ING_OUT, index=False)

    # 2) re-run s navýšením množství Sůl 100 -> 200 (stav k dnešku)
    es.ensure_output_excel_generic(df_ing(a=200, b=50), ING_OUT, bool_col="koupeno")

    out = pd.read_excel(ING_OUT)
    row = out.loc[mask_sul]
    assert not row.empty, "Řádek Sůl musí existovat i po navýšení."
    assert float(row.iloc[0]["potreba"]) == 200.0, "Množství musí odrážet nové (200)."
    assert bool(row.iloc[0]["koupeno"]) is True, "koupeno=True se musí zachovat po merži."


def test_uc9_ing_decrease_and_disappearance():
    # 1) první výpočet / zápis: dvě položky
    es.ensure_output_excel_generic(df_ing(a=200, b=100), ING_OUT, bool_col="koupeno")

    # 2) snížení Sůl 200 -> 100
    es.ensure_output_excel_generic(df_ing(a=100, b=100), ING_OUT, bool_col="koupeno")
    out1 = pd.read_excel(ING_OUT)
    mask_sul = (out1["ingredience_sk"].astype(str).str.strip() == "100") & \
               (out1["ingredience_rc"].astype(str).str.strip() == "1")
    assert float(out1.loc[mask_sul].iloc[0]["potreba"]) == 100.0, "Po snížení má být 100."

    # 3) Cibule úplně zmizí z plánu
    only_sul = pd.DataFrame(
        [{"datum":"2025-05-12","ingredience_sk":"100","ingredience_rc":"1","nazev":"Sůl","potreba":100,"jednotka":"kg"}]
    )
    es.ensure_output_excel_generic(only_sul, ING_OUT, bool_col="koupeno")
    out2 = pd.read_excel(ING_OUT)
    assert (out2["nazev"] == "Cibule").sum() == 0, "Zmizelá položka musí být z výsledku odstraněna."


# ------------------------------- UC9 – Polotovary -------------------------------

def test_uc9_semis_preserve_vyrobeno_on_recompute_spec():
    # 1) první zápis + ruční vyrobeno=True pro řádek 2025-06-01
    ses.ensure_output_semis_excel(df_semis(p1=100, p2=50), df_details=None)
    pre = pd.read_excel(SEMI_OUT, sheet_name="Prehled")
    mask = (pre["polotovar_sk"].astype(str).str.strip()=="300") & \
           (pre["polotovar_rc"].astype(str).str.strip()=="88") & \
           (pd.to_datetime(pre["datum"], errors="coerce").dt.date.astype(str)=="2025-06-01")
    pre.loc[mask, "vyrobeno"] = True
    # Pozor: přepsat jen jeden sheet potř. writer s openpyxl; pokud implementace nepodporuje, je to součást TODO.
    with pd.ExcelWriter(SEMI_OUT, engine="openpyxl") as xw:
        pre.to_excel(xw, sheet_name="Prehled", index=False)

    # 2) re-run s navýšením p1 100 -> 200
    ses.ensure_output_semis_excel(df_semis(p1=200, p2=50), df_details=None)

    post = pd.read_excel(SEMI_OUT, sheet_name="Prehled")
    mask_post = (post["polotovar_sk"].astype(str).str.strip()=="300") & \
                (post["polotovar_rc"].astype(str).str.strip()=="88") & \
                (pd.to_datetime(post["datum"], errors="coerce").dt.date.astype(str)=="2025-06-01")
    row = post.loc[mask_post]
    assert not row.empty
    assert float(row.iloc[0]["potreba"]) == 200.0, "Množství musí odrážet nové (200)."
    assert bool(row.iloc[0]["vyrobeno"]) is False, "vyrobeno=True se musí zachovat po přepočtu."


def test_uc9_semis_decrease_and_disappearance_without_crash():
    # 1) první zápis
    ses.ensure_output_semis_excel(df_semis(p1=200, p2=150), df_details=None)

    # 2) snížení p1: 200 -> 100 (stav k dnešku, žádná historie)
    ses.ensure_output_semis_excel(df_semis(p1=100, p2=150), df_details=None)
    pre = pd.read_excel(SEMI_OUT, sheet_name="Prehled")
    m1 = (pre["polotovar_sk"].astype(str).str.strip()=="300") & (pre["polotovar_rc"].astype(str).str.strip()=="88") & \
         (pd.to_datetime(pre["datum"], errors="coerce").dt.date.astype(str)=="2025-06-01")
    assert float(pre.loc[m1].iloc[0]["potreba"]) == 100.0

    # 3) druhý řádek zmizí z plánu
    ses.ensure_output_semis_excel(df_semis(p1=100, include_second=False), df_details=None)
    post = pd.read_excel(SEMI_OUT, sheet_name="Prehled")
    # v Prehledu už nesmí být 2025-06-02
    dates = pd.to_datetime(post["datum"], errors="coerce").dt.date.astype(str).tolist()
    assert "2025-06-02" not in dates, "Zmizelý řádek se musí z výstupu odstranit."
