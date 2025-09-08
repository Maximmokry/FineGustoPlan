# -*- coding: utf-8 -*-
"""
UC13 — Otevření plánovače týdne (výpočet pondělí) + vytvoření prázdného plánu
- Proč: uživatel chce rychle začít plánovat nejbližší týden.
- Očekávání: správné pondělí týdne, mřížka 6 dní × 4 udírny × 7 pozic = 168 řádků.
"""
from __future__ import annotations
from datetime import date
import os, sys
from pathlib import Path
import pandas as pd
import pytest

# offscreen pro případné Qt importy v downstream kódu
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# projektové importy
from services.smoke_orchestrator import compute_week_monday, build_plan_df

def test_uc13_compute_week_monday_basic():
    print("UC13: Uživatel otevře plán — očekává pondělí následujícího týdne (i když je dnes pondělí).")
    # pondělí → další pondělí
    assert compute_week_monday(date(2025, 9, 8)) == date(2025, 9, 15)
    # středa → nejbližší následující pondělí
    assert compute_week_monday(date(2025, 9, 10)) == date(2025, 9, 15)
    # neděle → zítřejší pondělí
    assert compute_week_monday(date(2025, 9, 14)) == date(2025, 9, 15)

def test_uc13_empty_plan_shape():
    print("UC13: Prázdný plán — uživatel chce jen vyplnit dávky, bez položek.")
    from services.smoke_orchestrator import build_plan_df
    from datetime import date
    import pandas as pd

    week = date(2025, 9, 15)
    df = build_plan_df(pd.DataFrame(), week_monday=week, rules=None)

    # 6 dní (Po–So), 4 udírny, 7 pozic
    assert len(df) == 6 * 4 * 7

    # build_plan_df vrací jen doménové sloupce (writer doplňuje 'davka'/'shift')
    must = {"datum", "udirna", "pozice", "polotovar_nazev", "mnozstvi", "jednotka"}
    assert must.issubset(set(df.columns))

