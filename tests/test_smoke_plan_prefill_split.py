# -*- coding: utf-8 -*-
import pandas as pd

from services.smoke_plan_service import SmokePlan, CapacityAwarePrefillStrategy, dataframe_to_items, next_monday
from services.smoke_capacity import CapacityRules


def test_prefill_splits_item_across_slots_round_robin():
    week = next_monday(pd.Timestamp("2025-09-03").date())
    rules = CapacityRules(base_per_smoker=[400, 300, 400, 400])

    # one item of 950 kg, should split: 400 + 300 + 250 (3 parts)
    df = pd.DataFrame([
        {"polotovar_nazev": "Šunka", "mnozstvi": 950, "jednotka": "kg", "meat_type": "veprove"},
    ])

    items = dataframe_to_items(df)
    plan = SmokePlan(week, capacity_rules=rules)
    strategy = CapacityAwarePrefillStrategy(rules)
    strategy.run(plan, items)

    out = plan.to_dataframe()
    # expect 3 non-empty rows with doses 400, 300, 250
    doses = [float(x) for x in out["mnozstvi"].dropna().tolist()]
    assert sorted(doses, reverse=True)[:3] == [400.0, 300.0, 250.0]

    # they should be in three distinct slots
    assert out.dropna(subset=["polotovar_id"]).shape[0] == 3


def test_prefill_respects_per_type_override():
    week = next_monday(pd.Timestamp("2025-09-03").date())
    rules = CapacityRules(
        base_per_smoker=[400, 300, 400, 400],
        per_type_overrides={"hovezi": [300, 250, 300, 300]},
    )

    # 620 kg hovezi should split by first smoker cap=300 then next cap=250 then 70
    df = pd.DataFrame([
        {"polotovar_nazev": "Hovězí kýta", "mnozstvi": 620, "jednotka": "kg", "meat_type": "hovezi"},
    ])

    plan = SmokePlan(week, capacity_rules=rules)
    CapacityAwarePrefillStrategy(rules).run(plan, dataframe_to_items(df))

    doses = [float(x) for x in plan.to_dataframe()["mnozstvi"].dropna().tolist()]
    assert sorted(doses, reverse=True)[:3] == [300.0, 250.0, 70.0]
