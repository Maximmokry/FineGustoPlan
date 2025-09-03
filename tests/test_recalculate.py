import os
import pandas as pd
import pytest

# Lokální implementace kompatibilní logiky "koupeno" vůči předchozímu výstupu
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from services.compute_common import _key_txt
from services.data_utils import to_date_col, to_bool_cell_excel
import services.paths as paths  # důležité: budeme patchovat paths.OUTPUT_EXCEL


def _recalculate_koupeno_against_previous(df_new: pd.DataFrame) -> pd.DataFrame:
    """
    Pokud se celkové množství NEZVÝŠILO oproti starému výstupu, ponecháme koupeno=True.
    Při zvýšení množství reset na False. Čte starý soubor z paths.OUTPUT_EXCEL.
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

    # >>> ZMĚNA: při prvním běhu nastavíme koupeno na False bez ohledu na vstup
    df_new["koupeno"] = False

    # interní klíče a kvantizace množství
    df_new["__sk"] = df_new.get("ingredience_sk", "").map(_key_txt)
    df_new["__rc"] = df_new.get("ingredience_rc", "").map(_key_txt)
    df_new["__qty_i"] = df_new.get("potreba", 0).map(_qty_to_int_micro)

    # načti starý výstup (může, ale nemusí existovat)
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


@pytest.fixture(autouse=True)
def cleanup_excel(tmp_path, monkeypatch):
    """Použije dočasný adresář pro OUTPUT_EXCEL a po testu uklidí."""
    out_file = tmp_path / "out.xlsx"
    monkeypatch.setattr("services.paths.OUTPUT_EXCEL", str(out_file))
    yield
    if out_file.exists():
        out_file.unlink()


def make_df(sk="100", rc="200", naz="Test", qty=1, datum="2025-01-01", koupeno=False):
    return pd.DataFrame([{
        "datum": datum,
        "ingredience_sk": sk,
        "ingredience_rc": rc,
        "nazev": naz,
        "potreba": qty,
        "koupeno": koupeno,
    }])


def test_no_old_file_sets_koupeno_false():
    new = make_df(qty=5, koupeno=True)  # i když True
    df = _recalculate_koupeno_against_previous(new)
    assert df["koupeno"].tolist() == [False]


def test_with_old_file_preserve_true_if_qty_not_increased(tmp_path, monkeypatch):
    old = make_df(qty=5, koupeno=True)
    old.to_excel(paths.OUTPUT_EXCEL, index=False)

    new = make_df(qty=5, koupeno=False)
    df = _recalculate_koupeno_against_previous(new)
    assert df["koupeno"].tolist() == [True]  # zachováno


def test_with_old_file_reset_if_qty_increased(tmp_path, monkeypatch):
    old = make_df(qty=3, koupeno=True)
    old.to_excel(paths.OUTPUT_EXCEL, index=False)

    new = make_df(qty=5, koupeno=False)
    df = _recalculate_koupeno_against_previous(new)
    assert df["koupeno"].tolist() == [False]  # resetováno


def test_old_file_without_datum(tmp_path, monkeypatch):
    old = make_df(qty=2, koupeno=True).drop(columns=["datum"])
    old.to_excel(paths.OUTPUT_EXCEL, index=False)

    new = make_df(qty=2, koupeno=False)
    df = _recalculate_koupeno_against_previous(new)
    assert df["koupeno"].tolist() == [True]


def test_missing_koupeno_column_in_old_file(tmp_path, monkeypatch):
    old = make_df(qty=2, koupeno=True).drop(columns=["koupeno"])
    old.to_excel(paths.OUTPUT_EXCEL, index=False)

    new = make_df(qty=2, koupeno=False)
    df = _recalculate_koupeno_against_previous(new)
    assert "koupeno" in df.columns


def test_missing_sk_or_rc_columns_in_old_file(tmp_path, monkeypatch):
    old = make_df(qty=2).drop(columns=["ingredience_sk", "ingredience_rc"])
    old.to_excel(paths.OUTPUT_EXCEL, index=False)

    new = make_df(qty=2, koupeno=False)
    df = _recalculate_koupeno_against_previous(new)
    assert not df.empty
