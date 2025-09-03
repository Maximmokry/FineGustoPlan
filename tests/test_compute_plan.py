# tests/test_compute_plan.py
import pandas as pd
import pytest
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# helpery z projektu
from services.compute_common import _key_txt
from services.data_utils import to_date_col, to_bool_cell_excel

# nová grafová pipeline
from services.data_loader import nacti_data as _nacti_data
from services.graph_model import Graph
from services.graph_builder import build_nodes_from_recipes, expand_plan_to_demands, attach_status_from_excels
from services.projections.ingredients_projection import to_ingredients_df


# ------------------------- Lokální aliasy/wrappery -------------------------

def nacti_data():
    """Alias na loader; v testech se dá monkeypatchnout přímo v tomto modulu."""
    return _nacti_data()


def _recalculate_koupeno_against_previous(df_new: pd.DataFrame, output_excel_path: str) -> pd.DataFrame:
    """
    Kompatibilní logika: pokud se celkové množství nezvýšilo oproti starému
    výstupu, ponecháme koupeno=True. Při zvýšení množství reset na False.
    """
    SCALE = 6

    def _qty_to_int_micro(v) -> int:
        try:
            s = str(v).strip().replace(",", ".")
            if s == "" or s.lower() in {"nan", "none"}:
                return 0
            d = Decimal(s)
        except (InvalidOperation, Exception):
            return 0
        q = d.quantize(Decimal(10) ** (-SCALE), rounding=ROUND_HALF_UP)
        return int((q * (Decimal(10) ** SCALE)).to_integral_value(rounding=ROUND_HALF_UP))

    df_new = df_new.copy()
    df_new.columns = [str(c).strip() for c in df_new.columns]
    to_date_col(df_new, "datum")
    if "for_datum" in df_new.columns:
        to_date_col(df_new, "for_datum")
    if "koupeno" not in df_new.columns:
        df_new["koupeno"] = False

    df_new["__sk"] = df_new.get("ingredience_sk", "").map(_key_txt)
    df_new["__rc"] = df_new.get("ingredience_rc", "").map(_key_txt)
    df_new["__qty_i"] = df_new.get("potreba", 0).map(_qty_to_int_micro)

    # načti starý výstup
    try:
        old = pd.read_excel(output_excel_path)
    except Exception:
        return df_new.drop(columns=["__sk", "__rc", "__qty_i"], errors="ignore")

    old = old.fillna("")
    old.columns = [str(c).strip() for c in old.columns]
    to_date_col(old, "datum")
    if "for_datum" in old.columns:
        to_date_col(old, "for_datum")

    for col in ("ingredience_sk", "ingredience_rc", "koupeno"):
        if col not in old.columns:
            old[col] = "" if col != "koupeno" else False

    old["koupeno"] = old["koupeno"].apply(to_bool_cell_excel).astype(bool)
    old["__sk"] = old["ingredience_sk"].map(_key_txt)
    old["__rc"] = old["ingredience_rc"].map(_key_txt)

    old_qty_col = None
    for c in ("mnozstvi", "množství", "potreba", "quantity", "qty"):
        if c in old.columns:
            old_qty_col = c
            break
    old["__qty_i"] = old[old_qty_col].map(_qty_to_int_micro) if old_qty_col else 0
    old["__k"] = old["koupeno"].astype(bool)

    new_has_date = "datum" in df_new.columns
    old_has_date = "datum" in old.columns
    key_cols = (["datum"] if (new_has_date and old_has_date) else []) + ["__sk", "__rc"]

    old_grp = old.groupby(key_cols, as_index=False).agg(prev_qty_i=("__qty_i", "sum"),
                                                        prev_koupeno=("__k", "max"))
    new_grp = df_new.groupby(key_cols, as_index=False).agg(new_qty_i=("__qty_i", "sum"))

    merged = new_grp.merge(old_grp, on=key_cols, how="left")
    merged["prev_qty_i"] = merged["prev_qty_i"].fillna(0).astype(int)
    merged["prev_koupeno"] = merged["prev_koupeno"].fillna(False).astype(bool)
    increased = merged["new_qty_i"].astype(int) > merged["prev_qty_i"].astype(int)
    merged["keep_true"] = (~increased) & merged["prev_koupeno"]

    df_new = df_new.merge(merged[key_cols + ["keep_true"]], on=key_cols, how="left")
    df_new["keep_true"] = df_new["keep_true"].fillna(False).astype(bool)
    df_new["koupeno"] = (df_new["koupeno"].astype(bool)) | df_new["keep_true"]
    return df_new.drop(columns=["__sk", "__rc", "__qty_i", "keep_true"], errors="ignore")


def compute_plan(output_excel_path: str) -> pd.DataFrame:
    """
    Wrapper nad grafovou pipeline:
      - recepty + plán → graf
      - attach stavů z Excelů (koupeno/vyrobeno)
      - projekce ingrediencí
      - kompatibilní re-aplikace 'koupeno' vůči předchozímu výstupu
    """
    recepty, plan = nacti_data()
    nodes = build_nodes_from_recipes(recepty)
    g = Graph(nodes=nodes, demands=expand_plan_to_demands(plan, nodes))
    attach_status_from_excels(g)            # promítne stavy ze stávajících Excelů
    df = to_ingredients_df(g)
    df = _recalculate_koupeno_against_previous(df, output_excel_path)
    return df


# ------------------------- Pomocné továrny -------------------------

def _fake_recepty(sk_parent=400, reg_parent=111, sk_child=150, reg_child=555,
                  qty_per_unit=2.0, mj="kg", nazev="Koření Piri Piri 1kg"):
    """
    Vytvoří DataFrame se stejným schématem, jaké očekává builder:
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


# ------------------------------ Testy ------------------------------

def test_compute_plan_first_run_sets_koupeno_false(tmp_output, monkeypatch):
    """
    První běh: neexistuje žádný starý výsledek → 'koupeno' musí být False.
    """
    # Přesměruj OUTPUT_EXCEL (čte se uvnitř attach/recalc)
    monkeypatch.setattr("services.paths.OUTPUT_EXCEL", tmp_output, raising=False)

    # Stub nacti_data() → žádné čtení z disku
    recepty_df = _fake_recepty(qty_per_unit=2.0)
    plan_df = _fake_plan(mnozstvi=1.0)
    monkeypatch.setattr(__name__ + ".nacti_data", lambda: (recepty_df, plan_df))

    out = compute_plan(tmp_output)

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
    # Přesměruj OUTPUT_EXCEL
    monkeypatch.setattr("services.paths.OUTPUT_EXCEL", tmp_output, raising=False)

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
    monkeypatch.setattr(__name__ + ".nacti_data", lambda: (recepty_df, plan_df))

    out = compute_plan(tmp_output)
    assert len(out) == 1
    row = out.iloc[0]
    assert float(row["potreba"]) == 2.0
    assert bool(row["koupeno"]) is False
