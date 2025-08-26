# tests/test_uc3_ingredients.py
import os
from pathlib import Path
import pandas as pd
import pytest

# Headless/CI režim (Qt offscreen)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import services.excel_service as es
import services.paths as sp
import gui.results_window as rw

TEST_OUT = Path("test_vysledek_uc3.xlsx")


# ---------------------------
# Fixtures & helpers
# ---------------------------
@pytest.fixture(autouse=True)
def _isolate_output(monkeypatch):
    # přesměruj výstupní soubor do testovacího
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


def _df_sample():
    # dva dny, stejná položka → pro agregaci se má sečíst
    return pd.DataFrame(
        [
            {
                "datum": "2025-05-12",
                "ingredience_sk": "100",
                "ingredience_rc": "1",
                "nazev": "Sůl",
                "potreba": 5,
                "jednotka": "kg",
            },
            {
                "datum": "2025-05-13",
                "ingredience_sk": "100",
                "ingredience_rc": "1",
                "nazev": "Sůl",
                "potreba": 3,
                "jednotka": "kg",
            },
            {
                "datum": "2025-05-13",
                "ingredience_sk": "200",
                "ingredience_rc": "9",
                "nazev": "Cibule",
                "potreba": 2,
                "jednotka": "kg",
            },
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


# ---------------------------
# UC3-1: Zápis výsledku + neagregovaný layout (mapa tlačítek)
# ---------------------------
def test_build_table_layout_non_aggregated_creates_buy_map():
    df = _df_sample()
    es.ensure_output_excel_generic(df, TEST_OUT, bool_col="koupeno")
    full = pd.read_excel(TEST_OUT).fillna("")
    rows, buy_map, rowkey_map = rw._build_table_layout(full, "koupeno", aggregate=False)

    # hlavička + 3 řádky
    assert rows is not None and len(rows) >= 4
    # existují tlačítka pro každý ne‑koupený řádek
    keys = [k for k in buy_map if k.startswith("-BUY-")]
    assert len(keys) == 3
    # rowkey_map naplněno
    assert len(rowkey_map) >= 3


# ---------------------------
# UC3-2: Agregovaný layout – seskupení napříč daty
# ---------------------------
def test_build_table_layout_aggregated_groups_and_sums():
    df = _df_sample()
    es.ensure_output_excel_generic(df, TEST_OUT, bool_col="koupeno")
    full = pd.read_excel(TEST_OUT).fillna("")
    rows, buy_map, _ = rw._build_table_layout(full, "koupeno", aggregate=True)

    assert rows is not None
    # očekáváme 2 skupiny: (100/1) a (200/9)
    grp_btns = [k for k in buy_map if k.startswith("-BUY-G-")]
    assert len(grp_btns) == 2

    # ve skupině (100/1) by měly být 2 indexy zdrojových řádků
    idxs_100_1 = max((buy_map[k] for k in grp_btns), key=lambda L: len(L))
    assert len(idxs_100_1) == 2


# ---------------------------
# UC3-3: open_results (headless) – klik na „Koupeno“ v neagregovaném režimu
# ---------------------------
def test_open_results_click_marks_true_and_saves(monkeypatch):
    df = _df_sample()
    es.ensure_output_excel_generic(df, TEST_OUT, bool_col="koupeno")
    full = pd.read_excel(TEST_OUT).fillna("")

    # fake create window: vyrobí mapu a klikne na první -BUY-
    orig_create = rw._create_results_window

    def fake_create(df_full, col_k, agg_flag, location=None):
        w, buy_map, rowkey_map = orig_create(df_full, col_k, agg_flag, location=location)
        first = next((k for k in buy_map if k.startswith("-BUY-")), None)
        events = []
        if first:
            events.append((first, {}))  # klik na Koupeno
        events.append((None, {}))       # zavření
        return _FakeWindow(events), buy_map, rowkey_map

    monkeypatch.setattr(rw, "_create_results_window", fake_create)

    # rekreace okna: přímo zavoláme builder a vrátíme nové okno
    monkeypatch.setattr(
        rw,
        "recreate_window_preserving",
        lambda old, builder, col_key='-COL-', **kw: builder((100, 100)),
        raising=False,
    )

    rw.open_results()

    out = pd.read_excel(TEST_OUT)
    assert "koupeno" in out.columns
    # aspoň jeden řádek musí být True po kliknutí
    assert out["koupeno"].astype(bool).any()


# ---------------------------
# UC3-4: open_results (headless) – přepnutí agregace a refresh
# ---------------------------
def test_open_results_toggle_aggregation_recreates(monkeypatch):
    df = _df_sample()
    es.ensure_output_excel_generic(df, TEST_OUT, bool_col="koupeno")

    created_variants = []

    def fake_create(df_full, col_k, agg_flag, location=None):
        # zaznamenáme, v jakém režimu se builder volá
        created_variants.append(("agg" if agg_flag else "nonagg"))
        rows, buy_map, rowkey_map = rw._build_table_layout(df_full, col_k, aggregate=agg_flag)
        # simulace: po prvním vykreslení pošleme event -AGG- a pak zavření
        if len(created_variants) == 1:
            events = [("-AGG-", {"-AGG-": True})]
        else:
            events = [(None, {})]
        return _FakeWindow(events), buy_map, rowkey_map

    def fake_recreate(old_win, builder, col_key='-COL-', **kw):
        # druhé volání builderu (po -AGG-) → agg režim
        return builder((100, 100))

    monkeypatch.setattr(rw, "_create_results_window", fake_create)
    monkeypatch.setattr(rw, "recreate_window_preserving", fake_recreate, raising=False)

    rw.open_results()

    # očekáváme, že builder byl volán nejprve v non-agg a pak v agg režimu
    assert created_variants[:2] == ["nonagg", "agg"]


# ---------------------------
# UC3-5: Robustnost – prázdný/nenalezitelný soubor
# ---------------------------
def test_open_results_gracefully_handles_empty_file(monkeypatch):
    # vytvoř prázdný Excel (správné hlavičky, ale žádné řádky)
    pd.DataFrame(columns=["datum", "ingredience_sk", "ingredience_rc", "nazev", "potreba", "jednotka", "koupeno"]).to_excel(TEST_OUT, index=False)

    # fake Window – žádné eventy, hned zavřít
    def fake_create(*args, **kwargs):
        return None, None, None  # simulace: „není co zobrazit“

    monkeypatch.setattr(rw, "_create_results_window", fake_create, raising=False)

    # pop‑up je umlčený, funkce se jen bezpečně ukončí
    rw.open_results()
