# -*- coding: utf-8 -*-
import pandas as pd

from services.smoke_sync_service import apply_plan_flags


def test_sync_flags_uses_base_id_from_parts():
    items = pd.DataFrame([
        {"polotovar_id": "A" , "polotovar_nazev": "Šunka"},
        {"polotovar_id": "B" , "polotovar_nazev": "Krkovička"},
    ])

    plan = pd.DataFrame([
        {"polotovar_id": "A::part1", "datum": "2025-09-08"},
        {"polotovar_id": "A::part2", "datum": "2025-09-09"},
    ])

    out = apply_plan_flags(items, plan)
    assert out.loc[out["polotovar_id"] == "A", "planned_for_smoking"].iloc[0] == True
    assert out.loc[out["polotovar_id"] == "B", "planned_for_smoking"].iloc[0] in (False, None, pd.NA)

    # earliest date wins
    dt = out.loc[out["polotovar_id"] == "A", "smoking_date"].iloc[0]
    assert str(dt) == "2025-09-08"
