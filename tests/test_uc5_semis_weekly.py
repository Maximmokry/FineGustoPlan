# tests/test_uc5_semis_weekly.py
import types
import builtins
import pandas as pd
import datetime as dt
import pytest

# Testujeme weekly režim a kliknutí v gui.results_semis_window
import gui.results_semis_window as semis
from services.paths import OUTPUT_SEMI_EXCEL

# ---------- Pomocné třídy / monkeypatch GUI ----------

class DummyWindow:
    """Minimal headless náhrada za PySimpleGUIQt Window."""
    def __init__(self, title, layout, **kwargs):
        self.title = title
        self.layout = layout
        self.events = []
        self.closed = False
        # simulovaná pozice
        self._loc = (100, 100)
        # najdeme checkbox klíče, ať víme jaké eventy poslat
        self.keys = set()
        for row in layout:
            for elem in row:
                if isinstance(elem, list):
                    for e in elem:
                        key = getattr(e, "Key", None) or getattr(e, "key", None)
                        if isinstance(key, str):
                            self.keys.add(key)
                else:
                    key = getattr(elem, "Key", None) or getattr(elem, "key", None)
                    if isinstance(key, str):
                        self.keys.add(key)

    # API volané z kódu
    def read(self):
        if self.closed:
            return (None, {})
        if self.events:
            ev = self.events.pop(0)
            # checkbox hodnoty podle weekly/detail přepínání
            vals = {}
            if ev == "-WEEKLY-":
                vals["-WEEKLY-"] = True
            if ev == "-DETAILS-":
                vals["-DETAILS-"] = True
            return (ev, vals)
        # když nic dalšího, zavři
        self.closed = True
        return ("-CLOSE-", {})

    def move(self, x, y):
        self._loc = (int(x), int(y))

    def current_location(self):
        return self._loc

    def close(self):
        self.closed = True

# malý objekt napodobující sg.Text/Button/Checkbox tak, aby kód nepadal při čtení .Key
class _Elt:
    def __init__(self, key=None):
        self.key = key
    def __iter__(self):  # umožní rozbalení v layoutech
        yield self

class DummySGModule:
    """Minimal SG „modul“ se vším, co testovaný kód volá."""
    class QtCore:
        class QTimer:
            @staticmethod
            def singleShot(ms, fn):  # v testu nečekáme, rovnou voláme
                try:
                    fn()
                except Exception:
                    pass

    # „Widget“ konstrukce vrací prosté objekty s .key
    @staticmethod
    def Text(*args, **kwargs):
        return _Elt()

    @staticmethod
    def Button(*args, **kwargs):
        return _Elt(kwargs.get("key"))

    @staticmethod
    def Checkbox(*args, **kwargs):
        return _Elt(kwargs.get("key"))

    @staticmethod
    def Column(*args, **kwargs):
        # Column(layout=[...]) → vrátíme list tak, aby jej kód mohl vnořovat
        lay = kwargs.get("layout") or kwargs.get("values")
        return lay if isinstance(lay, list) else [_Elt(kwargs.get("key"))]

    @staticmethod
    def Window(title, layout, **kwargs):
        return DummyWindow(title, layout, **kwargs)

    # Popup funkce jen „spolkneme“, ať test neběží do UI
    @staticmethod
    def popup(*args, **kwargs): pass
    @staticmethod
    def popup_error(*args, **kwargs): pass

    WINDOW_CLOSED = None


# ---------- Fikce I/O vrstvy nad Excelem ----------

class CaptureExcelWrites:
    """
    Zachytí volání pd.ExcelWriter(...) i DataFrame.to_excel(...) do OUTPUT_SEMI_EXCEL,
    aby se nic fyzicky nezapisovalo na disk a mohli jsme zkontrolovat, co by se uložilo.
    """
    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.writer_opened = False
        self.saved_main = None
        self.saved_det = None
        self.last_plain_saved = None  # fallback režim v _save_semi_excel
        self.saved_by_sheet = {}      # pro ensure_output_semis_excel
        self.ensure_mode = False

        # patch ExcelWriter
        def fake_writer(path, engine=None, **kwargs):
            self.writer_opened = True
            # object se __enter__/__exit__
            class _W:
                def __enter__(_w): return _w
                def __exit__(_w, *exc): return False
            return _W()

        self.monkeypatch.setattr(pd, "ExcelWriter", fake_writer)

        # patch DataFrame.to_excel
        orig_to_excel = pd.DataFrame.to_excel

        def to_excel_spy(df, path_or_writer, sheet_name=None, index=None, **kwargs):
            # Pokud se volá s writerem, jsme uvnitř context manageru ensure_output_semis_excel
            if isinstance(path_or_writer, object) and sheet_name is not None:
                self.ensure_mode = True
                # ukládej per-sheet
                self.saved_by_sheet[sheet_name] = df.copy()
                return None

            # Jinak očekáváme cestu (OUTPUT_SEMI_EXCEL) – to používá _save_semi_excel
            if isinstance(path_or_writer, (str, bytes)) or getattr(path_or_writer, "__fspath__", None):
                self.last_plain_saved = df.copy()
                return None

            # fallback – pro jistotu zavolej originál, kdyby něco jiného
            return orig_to_excel(df, path_or_writer, sheet_name=sheet_name, index=index, **kwargs)

        self.monkeypatch.setattr(pd.DataFrame, "to_excel", to_excel_spy, raising=True)

# ---------- Fikce čtení „polotovary.xlsx“ ----------

@pytest.fixture
def weekly_source_frames():
    """
    Připraví „Prehled“ se třemi nevyrobenými řádky:
      - dva v JEDNOM týdnu se stejným (SK, RC, Název, MJ)
      - jeden v jiném týdnu
    A „Detaily“ (není podmínkou weekly, ale kód je umí načítat).
    """
    # pondělí 2025-01-06 → týden Po–Ne 6.–12.1.
    d1 = dt.date(2025, 1, 6)
    d2 = dt.date(2025, 1, 8)   # stejný týden
    d3 = dt.date(2025, 1, 15)  # jiný týden

    main = pd.DataFrame([
        {"datum": d1, "polotovar_sk":"300", "polotovar_rc":"88", "polotovar_nazev":"Polotovar A", "potreba": 10, "jednotka":"kg", "vyrobeno": False},
        {"datum": d2, "polotovar_sk":"300", "polotovar_rc":"88", "polotovar_nazev":"Polotovar A", "potreba": 15, "jednotka":"kg", "vyrobeno": False},
        {"datum": d3, "polotovar_sk":"300", "polotovar_rc":"88", "polotovar_nazev":"Polotovar A", "potreba": 20, "jednotka":"kg", "vyrobeno": False},
    ])

    details = pd.DataFrame([
        {"datum": d1, "polotovar_sk":"300", "polotovar_rc":"88", "vyrobek_sk":"400", "vyrobek_rc":"1", "vyrobek_nazev":"Hotový 1", "mnozstvi":5, "jednotka":"kg"},
        {"datum": d2, "polotovar_sk":"300", "polotovar_rc":"88", "vyrobek_sk":"400", "vyrobek_rc":"2", "vyrobek_nazev":"Hotový 2", "mnozstvi":7, "jednotka":"kg"},
        {"datum": d3, "polotovar_sk":"300", "polotovar_rc":"88", "vyrobek_sk":"400", "vyrobek_rc":"3", "vyrobek_nazev":"Hotový 3", "mnozstvi":9, "jednotka":"kg"},
    ])

    return main, details


@pytest.fixture(autouse=True)
def patch_sg_and_helpers(monkeypatch):
    """Vymění PySimpleGUIQt i helpery tak, aby běžely headless."""
    # nahradíme celý modul sg
    monkeypatch.setattr(semis, "sg", DummySGModule(), raising=True)

    # gui_helpers.recreate_window_preserving vrací rovnou výsledek builderu
    import services.gui_helpers as gh
    def fake_recreate(old_win, builder, **kwargs):
        # zavři staré okno
        try:
            old_win.close()
        except Exception:
            pass
        return builder((100, 100))
    monkeypatch.setattr(gh, "recreate_window_preserving", fake_recreate, raising=True)


def _install_fake_reader(monkeypatch, frames):
    """Načítání Excelu nahradíme tak, aby vracelo připravené DF."""
    main_df, det_df = frames

    def fake_read_excel(path, sheet_name=None, *args, **kwargs):
        assert str(path).endswith(OUTPUT_SEMI_EXCEL.name)
        if sheet_name is None:
            return main_df.copy()
        if sheet_name == "Prehled":
            return main_df.copy()
        if sheet_name == "Detaily":
            return det_df.copy()
        # jiné sheety – prázdno
        return pd.DataFrame()

    monkeypatch.setattr(pd, "read_excel", fake_read_excel, raising=True)


# ---------- TESTY UC5: Weekly součet ----------

def test_uc5_weekly_grouping_click_marks_all_in_week(monkeypatch, weekly_source_frames):
    """
    UC5-A: Po přepnutí na „Součet na týden“ a kliknutí na první weekly řádek
           se označí jako vyrobené VŠECHNY zdrojové řádky z daného týdne
           (se stejným SK/RC/Název/MJ).
    """
    _install_fake_reader(monkeypatch, weekly_source_frames)

    captured = CaptureExcelWrites(monkeypatch)

    # Při prvním vykreslení přidáme do okna: nejdřív přepnutí weekly, pak klik na první WSEMI, pak close
    def window_with_events(title, layout, **kw):
        w = DummyWindow(title, layout, **kw)
        # sekvence událostí
        w.events = ["-WEEKLY-", "-WSEMI-0-", "-CLOSE-"]
        return w
    monkeypatch.setattr(semis, "sg", types.SimpleNamespace(**{**DummySGModule.__dict__, "Window": window_with_events, "QtCore": DummySGModule.QtCore, "popup": lambda *a, **k: None, "popup_error": lambda *a, **k: None, "WINDOW_CLOSED": None}))

    # Spusť okno
    semis.open_semis_results()

    # Po kliknutí by _save_semi_excel volal DataFrame.to_excel(...), což jsme zachytili do last_plain_saved
    saved = captured.last_plain_saved
    assert isinstance(saved, pd.DataFrame), "Nebyl zachycen zápis df_main do Excelu."

    # Ověř, že u dvou řádků z prvního týdne je vyrobeno=True, u třetího (jiný týden) zůstává
