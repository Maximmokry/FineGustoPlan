# tests/test_uc4_mark_bought.py
import os
from pathlib import Path
import pandas as pd
import pytest

# Headless/CI režim
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import services.paths as sp
import services.excel_service as es
import gui.results_window as rw


TEST_OUT = Path("test_vysledek_uc4.xlsx")


# ---------- helpers ----------
def _df_sample():
    """Dvě položky, z nichž první je na dvou různých datech (kvůli agregaci)."""
    return pd.DataFrame(
        [
            {"datum": "2025-05-12", "ingredience_sk": "100", "ingredience_rc": "1", "nazev": "Sůl",    "potreba": 5, "jednotka": "kg"},
            {"datum": "2025-05-13", "ingredience_sk": "100", "ingredience_rc": "1", "nazev": "Sůl",    "potreba": 3, "jednotka": "kg"},
            {"datum": "2025-05-13", "ingredience_sk": "200", "ingredience_rc": "9", "nazev": "Cibule", "potreba": 2, "jednotka": "kg"},
        ]
    )


class _FakeWindow:
    """Minimal fake okno pro simulaci event smyčky bez skutečného GUI."""
    def __init__(self, events):
        self._events = list(events)

    def read(self, timeout=None):
        if self._events:
            return self._events.pop(0)
        return (None, {})

    def close(self):
        pass

    def current_location(self):
        return (100, 100)


# ---------- fixtures ----------
@pytest.fixture(autouse=True)
def _isolate_output(monkeypatch):
    # přesměruj cesty do testovacího souboru
    monkeypatch.setattr(sp, "OUTPUT_EXCEL", TEST_OUT, raising=False)
    monkeypatch.setattr(rw, "OUTPUT_EXCEL", TEST_OUT, raising=False)

    # umlč pop‑upy (headless)
    monkeypatch.setattr(rw.sg, "popup", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(rw.sg, "popup_error", lambda *a, **k: None, raising=False)

    if TEST_OUT.exists():
        TEST_OUT.unlink()
    yield
    if TEST_OUT.exists():
        TEST_OUT.unlink()


# ---------- UC4-1: Klik v NEagregovaném režimu označí řádek jako True a uloží ----------
def test_mark_single_row_non_aggregated(monkeypatch):
    df = _df_sample()
    es.ensure_output_excel_generic(df, TEST_OUT, bool_col="koupeno")

    # vyrobíme okno tak, aby první event byl klik na první -BUY- a pak zavření
    orig_create = rw._create_results_window

    def fake_create(df_full, col_k, agg_flag, location=None):
        w, buy_map, rowkey_map = orig_create(df_full, col_k, agg_flag, location=location)
        first = next((k for k in buy_map if k.startswith("-BUY-") and not k.startswith("-BUY-G-")), None)
        events = []
        if first:
            events.append((first, {}))  # klik na „Koupeno“
        events.append((None, {}))       # ukončit smyčku
        return _FakeWindow(events), buy_map, rowkey_map

    # rekreace okna bez skutečného GUI
    def fake_recreate(old, builder, col_key='-COL-', **kw):
        return builder((100, 100))

    monkeypatch.setattr(rw, "_create_results_window", fake_create, raising=False)
    monkeypatch.setattr(rw, "recreate_window_preserving", fake_recreate, raising=False)

    rw.open_results()

    out = pd.read_excel(TEST_OUT)
    assert "koupeno" in out.columns
    assert out["koupeno"].astype(bool).sum() >= 1, "Po kliku má být aspoň jeden řádek označen jako koupený."


# ---------- UC4-2: Agregovaný režim – klik označí celou skupinu (stejné SK/RC napříč dny) ----------
def test_mark_group_aggregated(monkeypatch):
    df = _df_sample()
    es.ensure_output_excel_generic(df, TEST_OUT, bool_col="koupeno")

    # fake create: první vykreslení -> pošleme -AGG-; druhé -> klikneme na první -BUY-G-
    created = []

    def fake_create(df_full, col_k, agg_flag, location=None):
        rows, buy_map, rowkey_map = rw._build_table_layout(df_full, col_k, aggregate=agg_flag)
        if not created:
            # první okno: přepnout do agregace
            events = [("-AGG-", {"-AGG-": True})]
        else:
            # druhé okno (agregované): klik na první group tlačítko
            group_key = next((k for k in buy_map if k.startswith("-BUY-G-")), None)
            events = [(group_key, {})] if group_key else []
            events.append((None, {}))
        created.append("x")
        return _FakeWindow(events), buy_map, rowkey_map

    def fake_recreate(old, builder, col_key='-COL-', **kw):
        return builder((100, 100))

    monkeypatch.setattr(rw, "_create_results_window", fake_create, raising=False)
    monkeypatch.setattr(rw, "recreate_window_preserving", fake_recreate, raising=False)

    rw.open_results()

    out = pd.read_excel(TEST_OUT).fillna("")
    # položka (100/1) byla ve dvou dnech → po kliknutí v agregaci musí být oba řádky True
    mask_100_1 = (out["ingredience_sk"].astype(str).str.strip() == "100") & \
                 (out["ingredience_rc"].astype(str).str.strip() == "1")
    assert mask_100_1.any(), "Očekávám řádky pro SK=100, RC=1."
    assert out.loc[mask_100_1, "koupeno"].astype(bool).all(), "Všechny řádky skupiny mají být po kliku True."


# ---------- UC4-3: Stav koupeno se zachová po dalším přepočtu/mergi ----------
def test_koupeno_persists_after_recompute_merge():
    df = _df_sample()
    es.ensure_output_excel_generic(df, TEST_OUT, bool_col="koupeno")

    # simuluj, že uživatel dřív označil oba řádky Sůl jako True
    out = pd.read_excel(TEST_OUT).fillna("")
    mask_100_1 = (out["ingredience_sk"].astype(str).str.strip() == "100") & \
                 (out["ingredience_rc"].astype(str).str.strip() == "1")
    out.loc[mask_100_1, "koupeno"] = True
    out.to_excel(TEST_OUT, index=False)

    # „Nový výpočet“ – mění se množství, ale položky zůstávají (merge by měl zachovat koupeno=True)
    df_new = df.copy()
    df_new.loc[0, "potreba"] = 7  # 5 -> 7
    es.ensure_output_excel_generic(df_new, TEST_OUT, bool_col="koupeno")

    merged = pd.read_excel(TEST_OUT).fillna("")
    mask = (merged["ingredience_sk"].astype(str).str.strip() == "100") & \
           (merged["ingredience_rc"].astype(str).str.strip() == "1")
    assert mask.any()
    assert merged.loc[mask, "koupeno"].astype(bool).all(), "Po merži musí zůstat koupeno=True pro stejné klíče."


# ---------- UC4-4: Když je vše koupené, open_results se korektně ukončí ----------
def test_open_results_when_all_bought(monkeypatch):
    df = _df_sample()
    es.ensure_output_excel_generic(df, TEST_OUT, bool_col="koupeno")

    # vše na True
    full = pd.read_excel(TEST_OUT)
    full["koupeno"] = True
    full.to_excel(TEST_OUT, index=False)

    # _create_results_window by normálně vrátil None (není co zobrazit) → simulujeme
    monkeypatch.setattr(rw, "_create_results_window", lambda *a, **k: (None, None, None), raising=False)
    # umlčet pop‑up už máme v fixture

    # nemělo by to vyhodit výjimku (jen se tiše ukončit)
    rw.open_results()
