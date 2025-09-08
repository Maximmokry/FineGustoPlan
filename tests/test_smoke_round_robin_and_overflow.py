# -*- coding: utf-8 -*-
import pandas as pd

from services.smoke_plan_service import SmokePlan, CapacityAwarePrefillStrategy, dataframe_to_items, next_monday
from services.smoke_capacity import CapacityRules


def _collect_coords(df):
    return df.dropna(subset=["polotovar_id"]) [["den", "udirna", "pozice", "mnozstvi"]].values.tolist()


def test_round_robin_across_smokers_before_next_row():
    week = next_monday(pd.Timestamp("2025-09-03").date())
    rules = CapacityRules(base_per_smoker=[400, 300, 400, 400])

    # dvě položky tak, aby bylo vidět pořadí slotů: nejdřív smoker1, pak 2, 3, 4, pak další řádek
    df = pd.DataFrame([
        {"polotovar_nazev": "A", "mnozstvi": 1000, "jednotka": "kg", "meat_type": "veprove"},
        {"polotovar_nazev": "B", "mnozstvi": 1000, "jednotka": "kg", "meat_type": "veprove"},
    ])

    plan = SmokePlan(week, capacity_rules=rules)
    CapacityAwarePrefillStrategy(rules).run(plan, dataframe_to_items(df))

    out = plan.to_dataframe()
    # Prvních 4 obsazení by mělo být v pozici pozice=1 a udirna 1..4
    first_four = out.dropna(subset=["polotovar_id"]).sort_values(["pozice", "udirna"]).head(4)
    assert first_four["pozice"].tolist() == [1, 1, 1, 1]
    assert first_four["udirna"].tolist() == [1, 2, 3, 4]


def test_overflow_moves_to_next_rows_and_days():
    week = next_monday(pd.Timestamp("2025-09-03").date())
    rules = CapacityRules(base_per_smoker=[400, 300, 400, 400])

    # naplníme víc než jeden den: 4 udírny * 7 řádků * 400 ~= 11200, dáme 12000
    df = pd.DataFrame([
        {"polotovar_nazev": "Mega", "mnozstvi": 12000, "jednotka": "kg", "meat_type": "veprove"},
    ])

    plan = SmokePlan(week, capacity_rules=rules)
    CapacityAwarePrefillStrategy(rules).run(plan, dataframe_to_items(df))

    out = plan.to_dataframe()
    # mělo by být zaplněno hodně řádků přes více dnů; kontrola, že existují záznamy aspoň ve dvou dnech
    days_present = out.dropna(subset=["polotovar_id"]).groupby("den").size()
    assert (days_present > 0).sum() >= 2
