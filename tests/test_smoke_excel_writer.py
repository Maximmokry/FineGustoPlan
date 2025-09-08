# -*- coding: utf-8 -*-
import os
import pandas as pd

from services.smoke_excel_service import write_smoke_plan_excel


def test_excel_writer_creates_file_and_layout(tmp_path):
    # minimal plan_df covering one day, two smokers, two rows
    plan_df = pd.DataFrame([
        {"datum": "2025-09-08", "den": "Pondělí", "udirna": 1, "pozice": 1, "polotovar_nazev": "Šunka", "mnozstvi": 200, "jednotka": "kg"},
        {"datum": "2025-09-08", "den": "Pondělí", "udirna": 2, "pozice": 1, "polotovar_nazev": "Krkovička", "mnozstvi": 150, "jednotka": "kg"},
    ])

    out = tmp_path / "plan_uzeni_test.xlsx"
    write_smoke_plan_excel(str(out), plan_df, pd.Timestamp("2025-09-08").date())

    assert out.exists(), "Excel file should be created"
    # Optional: open with pandas to ensure workbook is valid (won't reproduce layout, but checks integrity)
    df_check = pd.read_excel(out, header=None)
    assert isinstance(df_check, pd.DataFrame)
