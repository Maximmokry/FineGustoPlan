# tests/test_uc6_semis_export.py
import pandas as pd
import datetime as dt
import types
import pytest

import services.semi_excel_service as ses
from services.paths import OUTPUT_SEMI_EXCEL


# ------------------ Pomocné fake implementace Excelu (openpyxl + pandas) ------------------

class FakeCell:
    def __init__(self):
        self.value = None
        self.data_type = None

class _Dim:
    def __init__(self):
        self.width = None

class _RowDim:
    def __init__(self):
        self.outlineLevel = 0

class _OutlinePr:
    def __init__(self):
        self.summaryBelow = None

class _SheetProps:
    def __init__(self):
        self.outlinePr = _OutlinePr()

class FakeWorksheet:
    def __init__(self, name):
        self.title = name
        self._rows = []  # list[list[Any]]
        self._cells = {} # (r,c) -> FakeCell
        self.column_dimensions = {}
        self.row_dimensions = {}
        self.sheet_properties = _SheetProps()

    def append(self, row):
        # Ulož řádek a zajisti cell objekty
        self._rows.append(list(row))
        r_idx = len(self._rows)
        for c_idx, _ in enumerate(row, start=1):
            self._cells.setdefault((r_idx, c_idx), FakeCell()).value = row[c_idx-1]

    def cell(self, row, column):
        # Vytvoř řádky až do požadovaného indexu
        while len(self._rows) < row:
            self._rows.append([])
        # Doplň prázdné buňky v daném řádku
        while len(self._rows[row-1]) < column:
            self._rows[row-1].append(None)
        self._cells.setdefault((row, column), FakeCell())
        # Sync: pokud už má cell value, držíme ji v _rows
        self._cells[(row, column)].value = self._rows[row-1][column-1]
        return self._cells[(row, column)]

    def __getitem__(self, col_letter):
        # pro column_dimensions["A"]
        self.column_dimensions.setdefault(col_letter, _Dim())
        return self.column_dimensions[col_letter]

class FakeWorkbook:
    def __init__(self, precreated=None):
        self._sheets = {}
        if precreated:
            for s in precreated:
                self._sheets[s.title] = s
        self._saved_to = None

    @property
    def sheetnames(self):
        return list(self._sheets.keys())

    def create_sheet(self, name):
        ws = FakeWorksheet(name)
        self._sheets[name] = ws
        return ws

    def __delitem__(self, key):
        if key in self._sheets:
            del self._sheets[key]

    def __getitem__(self, key):
        return self._sheets[key]

    def save(self, path):
        self._saved_to = str(path)


class CaptureWriterAndToExcel:
    """
    Zachytí pd.ExcelWriter(...) + DataFrame.to_excel(..., sheet_name=...) volání,
    aby se nic nezapisovalo na disk a měli jsme DF pro Prehled/Detaily.
    """
    def __init__(self, monkeypatch):
        self.writer_opened = False
        self.saved_by_sheet = {}     # sheet_name -> DataFrame

        # fake ExcelWriter context manager
        def fake_writer(path, engine=None, **kwargs):
            assert str(path).endswith(OUTPUT_SEMI_EXCEL.name)
            self.writer_opened = True
            class _W:
                def __enter__(_w): return _w
                def __exit__(_w, *exc): return False
            return _W()
        monkeypatch.setattr(pd, "ExcelWriter", fake_writer)

        # patch DataFrame.to_excel
        orig_to_excel = pd.DataFrame.to_excel

        def to_excel_spy(df, path_or_writer=None, sheet_name=None, index=None, **kwargs):
            # když je sheet_name a path_or_writer je writer -> ukládáme do mapy
            if sheet_name is not None:
                self.saved_by_sheet[sheet_name] = df.copy()
                return None
            # fallback: pokud by někdo volal přímo na cestu (nemělo by nastat v ensure_output_semis_excel)
            return orig_to_excel(df, path_or_writer, sheet_name=sheet_name, index=index, **kwargs)

        monkeypatch.setattr(pd.DataFrame, "to_excel", to_excel_spy, raising=True)


# ------------------ Fixtures ------------------

@pytest.fixture
def sample_frames():
    # Hlavní přehled – 2 řádky, z toho druhý s vyrobeno="1" (string), aby se otestoval převod na bool
    main = pd.DataFrame([
        {"datum": dt.date(2025, 2, 10), "polotovar_sk":"300", "polotovar_rc":"10", "polotovar_nazev":"Polotovar X",
         "potreba": 25, "jednotka":"kg", "vyrobeno": False},
        {"datum": dt.date(2025, 2, 11), "polotovar_sk":"300", "polotovar_rc":"10", "polotovar_nazev":"Polotovar X",
         "potreba": 15, "jednotka":"kg", "vyrobeno": "1"},
    ])

    # Detaily – 2 řádky pro první den
    det = pd.DataFrame([
        {"datum": dt.date(2025, 2, 10), "polotovar_sk":"300", "polotovar_rc":"10",
         "vyrobek_sk":"400", "vyrobek_rc":"1", "vyrobek_nazev":"Hotový A", "mnozstvi":5, "jednotka":"kg"},
        {"datum": dt.date(2025, 2, 10), "polotovar_sk":"300", "polotovar_rc":"10",
         "vyrobek_sk":"401", "vyrobek_rc":"2", "vyrobek_nazev":"Hotový B", "mnozstvi":2, "jednotka":"kg"},
    ])
    return main, det


# ------------------ UC6-A/B/C testy ------------------

def test_uc6A_writes_overview_and_details_and_bools(monkeypatch, sample_frames):
    """
    UC6-A: ensure_output_semis_excel zapisuje 'Prehled' a 'Detaily'
           a normalizuje 'vyrobeno' na bool.
    """
    cap = CaptureWriterAndToExcel(monkeypatch)

    # Fake openpyxl.load_workbook vrátí nový prázdný workbook
    fake_wb = FakeWorkbook()
    monkeypatch.setattr(ses, "load_workbook", lambda path: fake_wb)

    main, det = sample_frames
    ses.ensure_output_semis_excel(main, det)

    # Byl použit ExcelWriter?
    assert cap.writer_opened, "ExcelWriter nebyl použit."

    # Prehled & Detaily existují
    assert "Prehled" in cap.saved_by_sheet, "Sheet 'Prehled' nebyl zapsán."
    assert "Detaily" in cap.saved_by_sheet, "Sheet 'Detaily' nebyl zapsán."

    df_p = cap.saved_by_sheet["Prehled"].copy()
    df_d = cap.saved_by_sheet["Detaily"].copy()

    # 'vyrobeno' jsou booly
    assert "vyrobeno" in df_p.columns, "Sloupec 'vyrobeno' chybí v 'Prehled'."
    assert df_p["vyrobeno"].dtype == bool, "Sloupec 'vyrobeno' není bool."
    # druhý řádek (původně '1' jako text) musí být True
    assert bool(df_p.iloc[1]["vyrobeno"]) is True

    # Detaily zůstaly zachovány
    assert len(df_d) == 2
    assert set(df_d.columns) >= {"datum","polotovar_sk","polotovar_rc","vyrobek_sk","vyrobek_rc","vyrobek_nazev","mnozstvi","jednotka"}


def test_uc6B_builds_pretty_polotovary_sheet_with_children(monkeypatch, sample_frames):
    """
    UC6-B: Vytvoří se list 'Polotovary' s hlavičkou (6. buňka je prázdný text ""),
           hlavní řádek a podřádky (rozpady) se správným rozložením, a poznámka '(obsahuje rozpad)'.
    """
    # zachycení Prehled/Detaily zápisu
    CaptureWriterAndToExcel(monkeypatch)

    # Fake workbook
    wb = FakeWorkbook()
    monkeypatch.setattr(ses, "load_workbook", lambda path: wb)

    main, det = sample_frames
    ses.ensure_output_semis_excel(main, det)

    # Workbook po uložení?
    assert wb._saved_to and wb._saved_to.endswith(OUTPUT_SEMI_EXCEL.name)

    # Existuje list 'Polotovary'?
    assert "Polotovary" in wb.sheetnames
    ws = wb["Polotovary"]

    # 1) Hlavička
    assert len(ws._rows) >= 1
    header = ws._rows[0]
    assert header[:8] == ["Datum","SK","Reg.č.","Polotovar","Množství","","Vyrobeno","Poznámka"]
    # 6. buňka má být textový prázdný řetězec – v našem fake držíme value=="" a data_type je nastavitelný
    c6 = ws.cell(1, 6)
    assert c6.value == "", "6. buňka hlavičky musí být prázdný text \"\"."

    # 2) Hlavní řádky (minimálně 2, protože main má 2)
    #    první hlavní řádek je na row=2
    assert len(ws._rows) >= 2, "Chybí řádky s daty."
    first = ws._rows[1]
    # Sloupce: [Datum, SK, RC, Polotovar, Množství, Jednotka, Vyrobeno, Poznámka]
    assert first[0] == main.iloc[0]["datum"]
    assert str(first[1]) == str(main.iloc[0]["polotovar_sk"])
    assert str(first[2]) == str(main.iloc[0]["polotovar_rc"])
    assert first[3] == main.iloc[0]["polotovar_nazev"]
    assert first[4] == main.iloc[0]["potreba"]
    assert first[5] == main.iloc[0]["jednotka"]
    assert isinstance(first[6], bool)

    # 3) Podřádky: k prvnímu master by měly přibýt 2 detailní řádky
    #    Najdeme řetězce s šipkou "↳ " v prvních ~5 řádcích (1 header + 2 masters + 2 children aspoň)
    rows_texts = ["|".join("" if v is None else str(v) for v in r) for r in ws._rows[:8]]
    child_count = sum("↳ " in t for t in rows_texts)
    assert child_count >= 2, "Očekávám aspoň 2 podřádky s '↳ '."

    # 4) Poznámka '(obsahuje rozpad)' u master řádku s dětmi
    #    Hledáme řádek s poznámkou na 8. sloupci
    note_present = any((len(r) >= 8 and str(r[7]).strip() == "(obsahuje rozpad)") for r in ws._rows[1:4])
    assert note_present, "Master řádek s detaily musí mít poznámku '(obsahuje rozpad)'."


def test_uc6C_handles_empty_details_and_creates_empty_det_sheet(monkeypatch):
    """
    UC6-C: Pokud df_details je None nebo prázdné, vytvoří se 'Detaily' se správnou hlavičkou
           a list 'Polotovary' nebude mít podřádky.
    """
    # zachycení Prehled/Detaily zápisu
    cap = CaptureWriterAndToExcel(monkeypatch)

    # Fake workbook
    wb = FakeWorkbook()
    monkeypatch.setattr(ses, "load_workbook", lambda path: wb)

    main = pd.DataFrame([
        {"datum": dt.date(2025, 3, 1), "polotovar_sk":"301", "polotovar_rc":"77", "polotovar_nazev":"Polo Y",
         "potreba": 10, "jednotka":"kg", "vyrobeno": False},
    ])

    ses.ensure_output_semis_excel(main, df_details=None)

    # Detaily by měly být zapsané alespoň s hlavičkou (prázdný DF se standard sloupci)
    assert "Detaily" in cap.saved_by_sheet, "Sheet 'Detaily' musí existovat i při prázdném vstupu."
    df_d = cap.saved_by_sheet["Detaily"]
    assert list(df_d.columns) == ["datum","polotovar_sk","polotovar_rc","vyrobek_sk","vyrobek_rc","vyrobek_nazev","mnozstvi","jednotka"]

    # Polotovary existují a nemají podřádky (žádné řádky s '↳ ')
    ws = wb["Polotovary"]
    rows_texts = ["|".join("" if v is None else str(v) for v in r) for r in ws._rows]
    assert all("↳ " not in t for t in rows_texts), "Nemají být generovány žádné podřádky."
