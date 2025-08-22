# tests/test_uc1_ingredients.py
import types
from pathlib import Path
import pandas as pd
import pytest

# === Moduly z projektu ===
import services.data_utils as du
import services.excel_service as es
import gui.results_window as rw
import gui.main_window as mw


# ---------------------------------------------------------------------
# Společné cesty/soubory pro testování (nezasahujeme do ostrých souborů)
# ---------------------------------------------------------------------
TEST_OUT = Path("test_vysledek.xlsx")


@pytest.fixture(autouse=True)
def clean_files():
    """Před a po každém testu uklidíme testovací výstup."""
    if TEST_OUT.exists():
        TEST_OUT.unlink()
    yield
    if TEST_OUT.exists():
        TEST_OUT.unlink()


# --------------------
#       UNIT: utils
# --------------------
def test_utils_bool_and_dates_and_norm():
    assert du.to_bool_cell_excel(True) is True
    assert du.to_bool_cell_excel(1) is True
    assert du.to_bool_cell_excel("0") is False
    assert du.to_bool_cell_excel(None) is False

    assert du.fmt_cz_date("2025-01-02") == "02.01.2025"
    # Na špatné datum vrací prázdno, ale nezpůsobí pád
    assert du.fmt_cz_date("nonsense") in ("", "nonsense")

    # Normalizační pomocníci (stabilní textové klíče)
    assert du.norm_num_to_str(150.0) == "150"
    assert du.norm_num_to_str("150,0") == "150.0" or du.norm_num_to_str("150,0") == "150"  # tolerantní
    assert du.norm_num_to_str(None) == ""


# -------------------------------------------
#       UNIT/INTEG: excel_service (merge)
# -------------------------------------------
def test_ensure_output_excel_creates_and_has_bool():
    df = pd.DataFrame(
        [
            {
                "datum": "2025-01-01",
                "ingredience_sk": "100",
                "ingredience_rc": "1",
                "nazev": "sul",
                "potreba": 5,
                "jednotka": "kg",
            }
        ]
    )
    es.ensure_output_excel_generic(df, TEST_OUT, bool_col="koupeno")
    assert TEST_OUT.exists(), "Soubor se měl vytvořit."
    out = pd.read_excel(TEST_OUT)
    assert "koupeno" in out.columns
    assert out.loc[0, "koupeno"] is False


def test_merge_preserves_true_flags():
    # 1) první zápis – koupeno=True
    base = pd.DataFrame(
        [
            {
                "datum": "2025-01-01",
                "ingredience_sk": "200",
                "ingredience_rc": "99",
                "nazev": "cibule",
                "potreba": 2,
                "jednotka": "kg",
                "koupeno": True,
            }
        ]
    )
    es.ensure_output_excel_generic(base, TEST_OUT, bool_col="koupeno")

    # 2) druhý zápis – stejné klíče, koupeno=False (musí zůstat True)
    mod = base.copy()
    mod["koupeno"] = False
    es.ensure_output_excel_generic(mod, TEST_OUT, bool_col="koupeno")

    out = pd.read_excel(TEST_OUT)
    assert out.loc[0, "koupeno"] is True, "True flag se nesmí přepsat na False."


# -------------------------------------------------------
#   UNIT: results_window – builder neaggr i agregovaný
# -------------------------------------------------------
def _mini_df_for_layout():
    return pd.DataFrame(
        [
            {
                "datum": "2025-01-03",
                "ingredience_sk": "100",
                "ingredience_rc": "1",
                "nazev": "sul",
                "potreba": 5,
                "jednotka": "kg",
                "koupeno": False,
            },
            {
                "datum": "2025-01-04",
                "ingredience_sk": "100",
                "ingredience_rc": "1",
                "nazev": "sul",
                "potreba": 3,
                "jednotka": "kg",
                "koupeno": False,
            },
        ]
    )


def test_build_table_layout_non_aggregate_maps_buy_buttons():
    df = _mini_df_for_layout()
    rows_layout, buy_map, rowkey_map = rw._build_table_layout(df, col_k="koupeno", aggregate=False)
    assert rows_layout is not None and len(rows_layout) >= 2
    # Měli bychom mít 2 tlačítka -BUY-<index>-
    keys = list(buy_map.keys())
    assert any(k.startswith("-BUY-") for k in keys)
    # Rowkey map naplněn pro indexy
    assert len(rowkey_map) == 2


def test_build_table_layout_aggregate_groups_and_maps():
    df = _mini_df_for_layout()
    rows_layout, buy_map, _ = rw._build_table_layout(df, col_k="koupeno", aggregate=True)
    assert rows_layout is not None
    # V agregaci bude jediný řádek se součtem (2 stejné skupiny -> 1 tlačítko)
    btn_keys = [k for k in buy_map.keys() if k.startswith("-BUY-G-")]
    assert len(btn_keys) == 1, "Agregace měla vytvořit jeden skupinový button."
    idxs = buy_map[btn_keys[0]]
    assert len(idxs) == 2, "Skupinový button by měl mapovat oba neagregované řádky."


# ----------------------------------------------------------------
#   INTEG: results_window.open_results – simulace GUI kliknutí
# ----------------------------------------------------------------
class _FakeWindow:
    """Minimalistický fake PySimpleGUIQt okna pro čtení eventů."""
    def __init__(self, events):
        # events: list of (event, values_dict)
        self._events = list(events)

    def read(self):
        if self._events:
            return self._events.pop(0)
        # žádné další eventy → simuluj zavření
        return (None, {})

    def close(self):
        return

    def current_location(self):
        return (100, 100)


def test_open_results_clicks_buy_and_saves(monkeypatch):
    """
    Simulujeme:
      1) příprava výsledného excelu s 1 nevyřízenou položkou
      2) open_results() → GUI vrátí event '-BUY-<index>-'
      3) funkce uloží 'koupeno=True' a okno se rekreuje
    """
    # 1) příprava excelu
    df = pd.DataFrame(
        [
            {
                "datum": "2025-01-05",
                "ingredience_sk": "300",
                "ingredience_rc": "7",
                "nazev": "kmín",
                "potreba": 1,
                "jednotka": "kg",
                "koupeno": False,
            }
        ]
    )
    df.to_excel(TEST_OUT, index=False)

    # 2) monkeypatch výsledné cesty v results_window
    monkeypatch.setattr(rw, "OUTPUT_EXCEL", TEST_OUT)

    # 3) Zabalíme původní creator, aby nevolal skutečné GUI; vrátíme FakeWindow.
    orig_create = rw._create_results_window

    created_buy_map = {}

    def fake_create(df_full, col_k, agg_flag, location=None):
        # použijeme originální builder, ale okno nahradíme FakeWindow
        w, buy_map, rowkey_map = orig_create(df_full, col_k, agg_flag, location=location)
        nonlocal created_buy_map
        created_buy_map = buy_map.copy()

        # najděme první neagregovaný button '-BUY-<i>-'
        first_btn = next((k for k in buy_map if k.startswith("-BUY-")), None)
        # Po stisku buttonu chceme ještě jeden read → zavřít okno
        events = []
        if first_btn:
            events.append((first_btn, {}))
        events.append((None, {}))  # zavření

        fake = _FakeWindow(events)
        return fake, buy_map, rowkey_map

    monkeypatch.setattr(rw, "_create_results_window", fake_create)

    # 4) Rekreace okna bez skutečného přesunu/scrollu
    def fake_recreate(old_win, builder, col_key="-COL-", target_loc=None):
        # Vyrobíme nové okno opět jako FakeWindow (builder už je fake_create)
        new_tuple = builder(target_loc)
        return new_tuple

    monkeypatch.setattr(rw, "recreate_window_preserving", fake_recreate)

    # 5) Vypneme popupy, aby test neběhal s GUI
    monkeypatch.setattr(rw.sg, "popup", lambda *a, **k: None)
    monkeypatch.setattr(rw.sg, "popup_error", lambda *a, **k: None)

    # 6) Spuštění testované funkce
    rw.open_results()

    # 7) Ověření – koupeno by mělo být True po kliknutí
    out = pd.read_excel(TEST_OUT)
    assert "koupeno" in out.columns
    assert out.loc[0, "koupeno"] is True


# ----------------------------------------------------------------
#   INTEG: main_window.run – klik na "nákup ingrediencí"
#   (bez skutečných GUI oken – vše mockujeme)
# ----------------------------------------------------------------
class _WMFake:
    """Fake window pro hlavní okno: vrátí události RUN-ING a pak EXIT."""
    def __init__(self):
        self._events = [("-RUN-ING-", {}), ("-EXIT-", {})]

    def read(self):
        if self._events:
            return self._events.pop(0)
        return (None, {})

    def close(self):
        return

    def current_location(self):
        return (200, 200)


def test_main_window_run_triggers_compute_and_open(monkeypatch):
    # 1) fake compute_plan – vrátí mini dataframe
    def fake_compute_plan():
        return pd.DataFrame(
            [
                {
                    "datum": "2025-02-01",
                    "ingredience_sk": "400",
                    "ingredience_rc": "11",
                    "nazev": "paprika",
                    "potreba": 2,
                    "jednotka": "kg",
                }
            ]
        )

    # 2) zachytíme volání ensure_output_excel a open_results
    called = {"ensure": False, "open": False}

    def fake_ensure_output_excel(df):
        # Zapíše do TEST_OUT (ne do ostrého), abychom ověřili IO
        es.ensure_output_excel_generic(df, TEST_OUT, bool_col="koupeno")
        called["ensure"] = True

    def fake_open_results():
        called["open"] = True

    # 3) fake hlavní okno (PySimpleGUIQt)
    monkeypatch.setattr(mw.sg, "Window", lambda *a, **k: _WMFake())

    # 4) injektujeme fake výpočty/akce
    monkeypatch.setattr(mw.core, "compute_plan", fake_compute_plan)
    monkeypatch.setattr(mw, "ensure_output_excel", fake_ensure_output_excel)
    monkeypatch.setattr(mw, "open_results", fake_open_results)

    # 5) popupy pryč
    monkeypatch.setattr(mw.sg, "popup_error", lambda *a, **k: None)

    # 6) spustit smyčku
    mw.run()

    # 7) ověření
    assert called["ensure"] is True, "Po kliknutí se měl uložit výsledek do Excelu."
    assert called["open"] is True, "Po kliknutí se mělo otevřít okno výsledků."
    assert TEST_OUT.exists(), "Soubor s výsledkem měl vzniknout."
    out = pd.read_excel(TEST_OUT)
    assert "koupeno" in out.columns
    assert out.loc[0, "koupeno"] in (False, 0), "Nové řádky mají defaultně nekoupeno."
