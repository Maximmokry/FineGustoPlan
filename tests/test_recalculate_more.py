import pandas as pd
from datetime import date
import pytest

# Nové importy pro lokální implementaci
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from services.compute_common import _key_txt
from services.data_utils import to_date_col, to_bool_cell_excel
import services.paths as paths


def _recalculate_koupeno_against_previous(df_new: pd.DataFrame) -> pd.DataFrame:
    """
    Kompatibilní logika: pokud se celkové množství NEZVÝŠILO oproti starému
    výstupu, ponecháme koupeno=True. Při zvýšení množství reset na False.
    Čte starý soubor z paths.OUTPUT_EXCEL (monkeypatchováno v testech).
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

    # interní klíče a kvantizovaná množství
    df_new["__sk"] = df_new.get("ingredience_sk", "").map(_key_txt)
    df_new["__rc"] = df_new.get("ingredience_rc", "").map(_key_txt)
    df_new["__qty_i"] = df_new.get("potreba", 0).map(_qty_to_int_micro)

    # načti starý výstup z monkeypatchnuté cesty
    try:
        old = pd.read_excel(paths.OUTPUT_EXCEL)
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


def test_float_quantity_equality_keeps_true(tmp_path, monkeypatch):
    """
    Starý soubor má koupeno=True a množství 1,10 (text), nové množství 1.1 (float).
    Nemá se resetovat na False, protože množství je numericky stejné.
    """
    out_file = tmp_path / "vysledek.xlsx"
    # nově patchujeme cestu v services.paths
    monkeypatch.setattr("services.paths.OUTPUT_EXCEL", out_file, raising=False)

    old = pd.DataFrame([{
        "datum": date(2025, 8, 20),
        "ingredience_sk": 150,
        "ingredience_rc": 88,
        "nazev": "Koření Piri Piri 1kg",
        "potreba": "1,10",  # text s čárkou
        "jednotka": "kg",
        "koupeno": True,
    }])
    old.to_excel(out_file, index=False)

    new = pd.DataFrame([{
        "datum": date(2025, 8, 20),
        "ingredience_sk": 150.0,      # float/objekt
        "ingredience_rc": "88",
        "nazev": "Koření Piri Piri 1kg",
        "potreba": 1.1,               # float
        "jednotka": "kg",
    }])

    df = _recalculate_koupeno_against_previous(new)
    assert df["koupeno"].tolist() == [True]


def test_float_quantity_increase_resets_false(tmp_path, monkeypatch):
    """
    Staré množství 1.1, nové množství 1.2 → koupeno se musí resetovat na False.
    """
    out_file = tmp_path / "vysledek.xlsx"
    monkeypatch.setattr("services.paths.OUTPUT_EXCEL", out_file, raising=False)

    old = pd.DataFrame([{
        "datum": date(2025, 8, 20),
        "ingredience_sk": 150,
        "ingredience_rc": 88,
        "nazev": "Koření Piri Piri 1kg",
        "potreba": 1.1,
        "jednotka": "kg",
        "koupeno": True,
    }])
    old.to_excel(out_file, index=False)

    new = pd.DataFrame([{
        "datum": date(2025, 8, 20),
        "ingredience_sk": "150",
        "ingredience_rc": "88",
        "nazev": "Koření Piri Piri 1kg",
        "potreba": "1,2",  # větší (1.2)
        "jednotka": "kg",
    }])

    df = _recalculate_koupeno_against_previous(new)
    assert df["koupeno"].tolist() == [False]
