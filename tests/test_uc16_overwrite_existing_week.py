# -*- coding: utf-8 -*-
"""
UC16 — Přepsání existujícího týdne: změna obsahu po dalším uložení
- Proč: uživatel upraví dávku a uloží znovu; očekává, že Excel bude aktualizován.
"""
from __future__ import annotations
from datetime import date
import pandas as pd
from pathlib import Path
from openpyxl import load_workbook

from services.smoke_excel_service import write_smoke_plan_excel
from tests._smoke_test_utils import create_smoke_template, open_xlsx

def test_uc16_overwrite_changes_content(monkeypatch, tmp_path):
    print("UC16: Druhé uložení přepíše obsah Excelu (např. změněná 'Dávka').")
    from tests._smoke_test_utils import create_smoke_template, open_xlsx
    from services.smoke_excel_service import write_smoke_plan_excel
    from services.smoke_plan_service import SmokePlan, Item, Slot
    from datetime import date

    template = create_smoke_template(tmp_path / "tpl.xlsx")
    week = date(2025, 9, 15)

    plan = SmokePlan(week)
    plan.place(Item("id1","Výrobek A",2.0,"kg",None,None), Slot(0,0,0))
    df = plan.to_dataframe()
    for c in ["rc", "davka", "shift", "poznamka"]:
        if c not in df.columns:
            df[c] = None

    mask = (df["datum"] == week) & (df["udirna"] == 1) & (df["pozice"] == 1)
    df.loc[mask, "rc"] = "101"
    df.loc[mask, "davka"] = "A"
    out = tmp_path / "plan.xlsx"
    write_smoke_plan_excel(str(out), df, week_monday=week, template_path=str(template))

    # druhé uložení se změnou dávky
    df.loc[mask, "davka"] = "B"
    write_smoke_plan_excel(str(out), df, week_monday=week, template_path=str(template))

    wb = open_xlsx(out)
    ws = wb.active
    assert ws.cell(7, 4).value == "B"
