import os
import pandas as pd
import pytest

from main import _recalculate_koupeno_against_previous
from services.paths import OUTPUT_EXCEL


@pytest.fixture(autouse=True)
def cleanup_excel(tmp_path, monkeypatch):
    """Použije dočasný adresář pro OUTPUT_EXCEL."""
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
    old.to_excel(OUTPUT_EXCEL, index=False)

    new = make_df(qty=5, koupeno=False)
    df = _recalculate_koupeno_against_previous(new)
    assert df["koupeno"].tolist() == [True]  # zachováno


def test_with_old_file_reset_if_qty_increased(tmp_path, monkeypatch):
    old = make_df(qty=3, koupeno=True)
    old.to_excel(OUTPUT_EXCEL, index=False)

    new = make_df(qty=5, koupeno=False)
    df = _recalculate_koupeno_against_previous(new)
    assert df["koupeno"].tolist() == [False]  # resetováno


def test_old_file_without_datum(tmp_path, monkeypatch):
    old = make_df(qty=2, koupeno=True).drop(columns=["datum"])
    old.to_excel(OUTPUT_EXCEL, index=False)

    new = make_df(qty=2, koupeno=False)
    df = _recalculate_koupeno_against_previous(new)
    assert df["koupeno"].tolist() == [True]


def test_missing_koupeno_column_in_old_file(tmp_path, monkeypatch):
    old = make_df(qty=2, koupeno=True).drop(columns=["koupeno"])
    old.to_excel(OUTPUT_EXCEL, index=False)

    new = make_df(qty=2, koupeno=False)
    df = _recalculate_koupeno_against_previous(new)
    assert "koupeno" in df.columns


def test_missing_sk_or_rc_columns_in_old_file(tmp_path, monkeypatch):
    old = make_df(qty=2).drop(columns=["ingredience_sk", "ingredience_rc"])
    old.to_excel(OUTPUT_EXCEL, index=False)

    new = make_df(qty=2, koupeno=False)
    df = _recalculate_koupeno_against_previous(new)
    assert not df.empty
