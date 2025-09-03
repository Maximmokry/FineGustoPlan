# -*- coding: utf-8 -*-
"""
Orchestrátor – předává pravidla kapacit a používá capacity-aware prefill.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Tuple

import pandas as pd

from services.smoke_plan_service import SmokePlan, CapacityAwarePrefillStrategy, dataframe_to_items, next_monday
from services.smoke_capacity import CapacityRules
from services.smoke_excel_service import write_smoke_plan_excel
from services.smoke_sync_service import apply_plan_flags
from services.smoke_paths import smoke_plan_excel_path


def compute_week_monday(base: Optional[date] = None) -> date:
    return next_monday(base)


def build_plan_df(selected_items_df: pd.DataFrame,
                  week_monday: Optional[date] = None,
                  rules: Optional[CapacityRules] = None) -> pd.DataFrame:
    week_monday = week_monday or compute_week_monday()
    items = dataframe_to_items(selected_items_df)
    plan = SmokePlan(week_monday, capacity_rules=rules)
    plan.prefill = CapacityAwarePrefillStrategy(rules).run  # přiřadíme strategii
    plan.prefill(plan, items)  # spustíme
    return plan.to_dataframe()


def plan_and_save(selected_items_df: pd.DataFrame,
                  week_monday: Optional[date] = None,
                  rules: Optional[CapacityRules] = None,
                  sheet_name: str = "Plan") -> Tuple[pd.DataFrame, str]:
    week_monday = week_monday or compute_week_monday()
    plan_df = build_plan_df(selected_items_df, week_monday, rules)
    out_path = smoke_plan_excel_path(week_monday)
    write_smoke_plan_excel(str(out_path), plan_df, week_monday, sheet_name=sheet_name)
    return plan_df, str(out_path)


def sync_flags(items_df: pd.DataFrame, plan_df: pd.DataFrame) -> pd.DataFrame:
    return apply_plan_flags(items_df, plan_df)



# ========================= UTILITY =========================
def filter_unplanned(items_df: pd.DataFrame) -> pd.DataFrame:
    """Vrátí jen nenaplánované položky (planned_for_smoking != True)."""
    if items_df is None or items_df.empty:
        return items_df.copy() if items_df is not None else pd.DataFrame()
    df = items_df.copy()
    if "planned_for_smoking" not in df.columns:
        return df
    return df[(df["planned_for_smoking"].isna()) | (df["planned_for_smoking"] == False)]


def assign_shift_column(plan_df: pd.DataFrame, shift_resolver=None) -> pd.DataFrame:
    """Volitelně doplní do `plan_df` sloupec `shift` (Směna) dle vlastní logiky."""
    out = plan_df.copy()
    if shift_resolver is None:
        return out
    out["shift"] = out.apply(shift_resolver, axis=1)
    return out
