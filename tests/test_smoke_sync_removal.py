# -*- coding: utf-8 -*-
import pandas as pd

from services.smoke_sync_service import apply_plan_flags


def test_sync_removal_resets_flags():
    # původně naplánované
    items = pd.DataFrame([
        {"polotovar_id": "A", "polotovar_nazev": "Šunka", "planned_for_smoking": True, "smoking_date": "2025-09-08"},
        {"polotovar_id": "B", "polotovar_nazev": "Krkovička", "planned_for_smoking": True, "smoking_date": "2025-09-08"},
    ])

    # prázdný plán → vše se má odplánovat
    plan = pd.DataFrame(columns=["polotovar_id", "datum"])  # žádné záznamy
    out = apply_plan_flags(items, plan)

    assert out.set_index("polotovar_id").loc["A", "planned_for_smoking"] in (False, None, pd.NA)
    assert out.set_index("polotovar_id").loc["B", "planned_for_smoking"] in (False, None, pd.NA)
    assert pd.isna(out.set_index("polotovar_id").loc["A", "smoking_date"]) or out.set_index("polotovar_id").loc["A", "smoking_date"] in (None, "")
