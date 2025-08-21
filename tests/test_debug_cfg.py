import io
import sys
import pandas as pd
from datetime import date

from gui.results_window import _debug_dump, DEBUG_CFG

def _df_for_debug():
    return pd.DataFrame([
        {"datum": date(2025,8,20), "ingredience_sk":"150","ingredience_rc":"88","nazev":"Piri","potreba":1,"jednotka":"kg","koupeno":False},
        {"datum": date(2025,8,21), "ingredience_sk":"200","ingredience_rc":"33","nazev":"Jina","potreba":2,"jednotka":"ks","koupeno":True},
    ])

def test_debug_disabled_prints_nothing(monkeypatch):
    DEBUG_CFG["enabled"] = False
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf, raising=False)
    _debug_dump(_df_for_debug(), "TEST", "koupeno")
    assert buf.getvalue() == ""

def test_debug_enabled_with_pairs_filters_output(monkeypatch):
    DEBUG_CFG["enabled"] = True
    DEBUG_CFG["pairs"] = [("150","88")]
    DEBUG_CFG["limit"] = 10
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf, raising=False)
    _debug_dump(_df_for_debug(), "TEST", "koupeno")
    out = buf.getvalue()
    assert "(SK,RC)=(150,88)" in out
    assert "Jina" not in out  # druhý řádek není v páru
    # reset
    DEBUG_CFG["enabled"] = False
    DEBUG_CFG["pairs"] = []
