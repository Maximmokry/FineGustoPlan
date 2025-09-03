# -*- coding: utf-8 -*-
import pandas as pd
from openpyxl import load_workbook

from services.smoke_excel_service import write_smoke_plan_excel


def test_excel_layout_readback(tmp_path):
    week = pd.Timestamp("2025-09-08").date()  # pondělí
    # připrav miniplán na pondělí (ostatní dny writer vypíše prázdné bloky)
    plan_df = pd.DataFrame([
        {"datum": "2025-09-08", "den": "Pondělí", "udirna": 1, "pozice": 1, "polotovar_nazev": "Šunka", "mnozstvi": 200, "jednotka": "kg"},
        {"datum": "2025-09-08", "den": "Pondělí", "udirna": 2, "pozice": 1, "polotovar_nazev": "Krkovička", "mnozstvi": 150, "jednotka": "kg"},
    ])

    out = tmp_path / "plan_uzeni_layout.xlsx"
    write_smoke_plan_excel(str(out), plan_df, week)

    # ověř list a pár buněk (A1 by měla obsahovat text "Pondělí 2025-09-08")
    wb = load_workbook(out)
    ws = wb["Plan"]
    assert ws["A1"].value.startswith("Pondělí ")
    assert "Udírna číslo 1." in (ws["A2"].value or "")
    assert ws["A3"].value == "Pořadové číslo"
    # první data v buňkách bloku 1 (řada 4): pořadové číslo 1, název šunky viz A4..E4 rozprostřeno přes bloky
    assert ws["A4"].value == 1
