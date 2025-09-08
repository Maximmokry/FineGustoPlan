# -*- coding: utf-8 -*-
"""
UC14 — Uložení do Excelu: správný název souboru a cílová složka
- Proč: uživatel klikne 'Uložit' a chce soubor 'plan uzeni/plan_uzeni_YYYY_MM_DD.xlsx'.
- Navíc ověříme, že titulek dnů (Pondělí…Sobota) se vyplní podle týdne.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
import os, sys
import pandas as pd
from openpyxl import load_workbook
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from services.smoke_orchestrator import plan_and_save
from services.smoke_capacity import CapacityRules
from tests._smoke_test_utils import create_smoke_template, patch_smoke_paths, open_xlsx

def test_uc14_save_path_and_titles(monkeypatch, tmp_path):
    print("UC14: Uživatel uloží plán — očekává správný název i titulky dnů v Excelu.")
    from pathlib import Path
    import pandas as pd
    from datetime import date
    from services.smoke_orchestrator import plan_and_save
    from services.smoke_capacity import CapacityRules
    from tests._smoke_test_utils import create_smoke_template, patch_smoke_paths, open_xlsx

    template = create_smoke_template(tmp_path / "tpl.xlsx", smokers=4, days=6, rows_per_smoker=7)
    patch_smoke_paths(monkeypatch, tmp_path, template)

    sel = pd.DataFrame([
        {"polotovar_nazev": "Kýta uzená", "mnozstvi": 5.0, "jednotka": "kg"},
        {"polotovar_nazev": "Bůček",      "mnozstvi": 3.0, "jednotka": "kg"},
    ])
    week = date(2025, 9, 15)
    rules = CapacityRules(base_per_smoker=[1e9, 1e9, 1e9, 1e9])
    plan_df, out_path = plan_and_save(sel, week_monday=week, rules=rules)

    out = Path(out_path)
    assert out.exists()
    assert out.parent.name == "plan uzeni"
    assert out.name == "plan_uzeni_2025_09_15.xlsx"

    wb = open_xlsx(out)
    ws = wb.active

    titles = []
    for r in range(1, 200):
        v = str(ws.cell(r, 1).value or "")
        if any(day in v for day in ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota"]):
            titles.append(v)

    assert any("Pondělí 15.09.2025" in t for t in titles)
    assert any("Sobota 20.09.2025" in t for t in titles)

