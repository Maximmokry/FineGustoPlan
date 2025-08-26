# tests/test_uc12_close_app.py
import builtins
import importlib
import sys
import time
from types import SimpleNamespace
from pathlib import Path

import pytest


# --------- Falešné GUI pro headless běh ---------
class _FakeWindow:
    def __init__(self, title, layout, finalize=True, size=None, location=None):
        # fronta událostí je sdílená na modulu fake_sg
        self._events = list(fake_sg._event_queue)
        self._closed = False
        # volitelně simulace výjimky z read()
        self._raise_on_read = fake_sg._raise_on_read
        # jednoduchá pozice okna
        self._loc = location if location else (0, 0)

    def read(self):
        if self._raise_on_read:
            # vyhoď jen jednou – aby se smyčka korektně ukončila
            self._raise_on_read = False
            raise RuntimeError("Simulated read() failure")
        if not self._events:
            # když už nic není, držíme smyčku na no-op (nemělo by nastat,
            # protože testy předají ukončovací event hned)
            return ("__IDLE__", {})
        return self._events.pop(0)

    def close(self):
        self._closed = True

    # API používané v helperu/oknech (bez efektu, ale ať to nepadá)
    def current_location(self):
        return self._loc

    def move(self, x, y):
        self._loc = (int(x), int(y))

    def __getitem__(self, key):
        # vrací dummy objekt s Widget.verticalScrollBar() -> value()/setValue()
        class _Bar:
            def __init__(self):
                self._v = 0
            def value(self): return self._v
            def setValue(self, v): self._v = int(v)
        class _Widget:
            def __init__(self): self._sb = _Bar()
            def verticalScrollBar(self): return self._sb
        return SimpleNamespace(Widget=_Widget())


class _FakeSG:
    """
    Minimalistický stub PySimpleGUIQt:
    - Window: vrací _FakeWindow
    - konstanty + popupy (no-op)
    - QtCore.QTimer.singleShot: no-op
    """
    WINDOW_CLOSED = "WINDOW_CLOSED"

    def __init__(self):
        self._event_queue = []
        self._raise_on_read = False
        class _QTimer:
            @staticmethod
            def singleShot(ms, fn):
                # no-op; v testech nechceme asynchronní běh
                return None
        class _QtCore:
            QTimer = _QTimer
        self.QtCore = _QtCore

    def Window(self, *a, **kw):
        return _FakeWindow(*a, **kw)

    # UI helpers (no-op)
    @staticmethod
    def popup(*a, **kw): pass
    @staticmethod
    def popup_error(*a, **kw): pass
    @staticmethod
    def Text(*a, **kw): return SimpleNamespace()
    @staticmethod
    def Button(*a, **kw): return SimpleNamespace()
    @staticmethod
    def Column(*a, **kw): return SimpleNamespace()


# globální instance stubu, ať ji vidí buildery oken v importovaných modulech
fake_sg = _FakeSG()


@pytest.fixture(autouse=True)
def inject_fake_pysimpleguiqt(monkeypatch):
    """
    Před každým testem vložíme náš fake modul do sys.modules pod názvem 'PySimpleGUIQt',
    aby ho GUI moduly importovaly místo skutečného balíčku.
    """
    monkeypatch.setitem(sys.modules, "PySimpleGUIQt", fake_sg)
    # čerstvé fronty a chování
    fake_sg._event_queue = []
    fake_sg._raise_on_read = False
    yield
    # po testu úklid není nutný, pytest fixture to izoluje


def _fresh_import_main_window():
    """
    Re-import gui hlavního okna s naší náhradou PySimpleGUIQt.
    Zároveň zaručíme, že předchozí importy se vyhodí, aby se načetl kód s novým stubem.
    """
    # zahoď cache modulů, které tato část používá (z GUI větví)
    for mod in list(sys.modules):
        if mod in ("main_window", "gui.main_window"):
            sys.modules.pop(mod, None)
    # některé GUI moduly importují také results_windows; ty ale s naším stubem nevadí
    return importlib.import_module("main_window")


# ------------- Pomoc pro test perzistence výstupů -------------
def _touch_file(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"dummy")
    # vrať mtime s malou prodlevou – aby bylo co porovnávat
    time.sleep(0.01)
    return p.stat().st_mtime


def _get_outputs_paths():
    # načti services.paths a vrať defaultní cesty
    paths = importlib.import_module("services.paths")
    return Path(paths.OUTPUT_EXCEL), Path(paths.OUTPUT_SEMI_EXCEL)


# ======================= TESTY UC12 =======================

def test_uc12_exit_button_closes_window_without_errors(capsys):
    """
    UC12: Stisk 'Konec' (-EXIT-) bezpečně ukončí hlavní smyčku a zavře okno.
    """
    fake_sg._event_queue = [("-EXIT-", {})]
    mw = _fresh_import_main_window()

    # spuštění smyčky
    mw.run()

    # pokud jsme se sem dostali, smyčka korektně skončila (žádná výjimka)
    # nepřímé ověření: ve frontě nemají zbýt neobsloužené události
    assert fake_sg._event_queue == []


def test_uc12_window_closed_event_ends_loop():
    """
    UC12: Křížek okna (WINDOW_CLOSED) smyčku korektně ukončí.
    """
    fake_sg._event_queue = [(fake_sg.WINDOW_CLOSED, {})]
    mw = _fresh_import_main_window()
    mw.run()
    assert fake_sg._event_queue == []


def test_uc12_read_failure_is_handled_and_window_closed(capsys):
    """
    UC12: Když read() vyhodí výjimku, aplikace chybu zaloguje, smyčku ukončí
          a finálně zavře okno (finally blok main_window.run()).
    """
    # nejprve uděláme jednu chybu z read(); tím se smyčka přeruší
    fake_sg._raise_on_read = True
    # po chybě už žádnou událost nepotřebujeme; smyčka vyběhne do finally
    fake_sg._event_queue = []
    mw = _fresh_import_main_window()
    mw.run()
    

    # Ověř, že se něco zalogovalo na stderr (není nutné striktně, ale sanitační check)
    out, err = capsys.readouterr()
    assert "Chyba při čtení události okna" in err or "[ERROR]" in err or "[FATAL]" in err


def test_uc12_persistence_outputs_not_modified(tmp_path, monkeypatch):
    """
    UC12: Zavření aplikace samo o sobě nesahá na výstupní soubory.
          Ověříme, že jejich mtime zůstane stejné.
    """
    # Přesměruj OUTPUT_EXCEL/OUTPUT_SEMI_EXCEL do dočasné složky
    paths = importlib.import_module("services.paths")
    excel_out = tmp_path / "vysledek.xlsx"
    semi_out  = tmp_path / "polotovary.xlsx"
    monkeypatch.setattr(paths, "OUTPUT_EXCEL", excel_out)
    monkeypatch.setattr(paths, "OUTPUT_SEMI_EXCEL", semi_out)

    # Vytvoř dummy soubory a získej mtime před během
    m1_before = _touch_file(excel_out)
    m2_before = _touch_file(semi_out)

    # Běh aplikace: jen ukončení
    fake_sg._event_queue = [("-EXIT-", {})]
    mw = _fresh_import_main_window()
    mw.run()

    # Současné mtime
    assert excel_out.exists() and semi_out.exists()
    m1_after = excel_out.stat().st_mtime
    m2_after = semi_out.stat().st_mtime

    assert m1_after == pytest.approx(m1_before)
    assert m2_after == pytest.approx(m2_before)
