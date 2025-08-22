# tests/test_gui_helpers.py
import types
import builtins
import pytest

# Modul s helperem:
from services import gui_helpers as gh


class FakeCol:
    """Fake Column element s pseudo-scrollbarem."""
    class _W:
        def __init__(self):
            self._scroll = 0
        def verticalScrollBar(self):
            return self
        # "API" jako Qt scrollbar
        def value(self):
            return self._scroll
        def setValue(self, v):
            self._scroll = int(v)
    def __init__(self):
        self.Widget = self._W()


class FakeWindow:
    """Minimal fake okno – simuluje move() a current_location()."""
    def __init__(self, x=100, y=100):
        self._x = int(x)
        self._y = int(y)
        self.AllKeysDict = {'-COL-': FakeCol()}  # aby helper našel Column
    def current_location(self):
        return (self._x, self._y)
    def move(self, x, y):
        self._x, self._y = int(x), int(y)
    def close(self):
        self._closed = True
    def __getitem__(self, key):
        return self.AllKeysDict[key]


def test_compensated_move_immediate(monkeypatch):
    """
    Ověříme, že kompenzační posun dorovná offset –
    simulujeme, že nové okno se otevírá na +30px Y oproti cílové poloze.
    """
    # zapnout debug (není kritické, ale ať je jasné chování)
    gh.dbg_set_enabled(True)

    # fake QTimer: singleShot -> hned volej funkci
    monkeypatch.setattr(gh.QtCore.QTimer, "singleShot", lambda *_args, **_kw: _args[1]())

    target = (200, 150)
    # "Nové" okno se zrodí se skokem +30px (tj. 180)
    w = FakeWindow(x=target[0], y=target[1] + 30)

    # interni utilita je volaná z recreate_window_preserving – obejdeme builder a zavoláme rovnou utilitu
    # připravíme column scroll před přesunem
    w['-COL-'].Widget.setValue(42)

    # zavoláme privátní interní funkci přes veřejné API: builder vrátí w "tak jak je"
    def builder(location):
        # builder dostane target location; vrací stejné okno (simulace čerstvě vytvořeného)
        assert location == target
        return w, {"_bm": []}, {"_rk": []}

    # původní okno (před rekreací) – nechť je na targetu
    old_w = FakeWindow(x=target[0], y=target[1])
    old_w['-COL-'].Widget.setValue(42)

    # Spusť helper – očekáváme, že po sérii kompenzací skončí přesně na targetu a obnoví scroll
    new_w, buy_map, rowkey_map = gh.recreate_window_preserving(old_w, builder, col_key='-COL-')
    assert (new_w.current_location() == target)
    assert new_w['-COL-'].Widget.value() == 42
    assert isinstance(buy_map, dict)
    assert isinstance(rowkey_map, dict)


def test_recreate_calls_builder_with_old_location(monkeypatch):
    """Builder dostane lokalitu starého okna (preserve location)."""
    gh.dbg_set_enabled(False)
    old = FakeWindow(321, 654)

    captured_location = {}
    def builder(location):
        captured_location['loc'] = tuple(location) if location else None
        # vrať nové okno už rovnou v té cílové lokaci
        return FakeWindow(*location), {}, {}

    # QTimer „okamžitý“
    monkeypatch.setattr(gh.QtCore.QTimer, "singleShot", lambda *_a, **_k: _a[1]())

    new_w, _bm, _rk = gh.recreate_window_preserving(old, builder, col_key='-COL-')
    assert captured_location['loc'] == (321, 654)
    assert new_w.current_location() == (321, 654)
