from __future__ import annotations
from datetime import date
from typing import Optional, Tuple
import pandas as pd

from services.smoke_plan_service import SmokePlan, CapacityAwarePrefillStrategy, dataframe_to_items, next_monday
from services.smoke_capacity import CapacityRules
from services.smoke_excel_service import write_smoke_plan_excel
from services.smoke_paths import smoke_plan_excel_path, smoke_template_path

def compute_week_monday(base: Optional[date] = None) -> date:
    return next_monday(base)

def build_plan_df(selected_items_df: pd.DataFrame,
                  week_monday: Optional[date] = None,
                  rules: Optional[CapacityRules] = None) -> pd.DataFrame:
    week_monday = week_monday or compute_week_monday()
    items = dataframe_to_items(selected_items_df)
    plan = SmokePlan(week_monday, capacity_rules=rules)
    plan.prefill = CapacityAwarePrefillStrategy(rules).run
    plan.prefill(plan, items)
    return plan.to_dataframe()

def plan_and_save(selected_items_df: pd.DataFrame,
                  week_monday: Optional[date] = None,
                  rules: Optional[CapacityRules] = None) -> Tuple[pd.DataFrame, str]:
    """
    Vytvoří kopii šablony a doplní data + správné nadpisy dnů.
    Název výstupního XLSX zůstává dle smoke_plan_excel_path().
    """
    week_monday = week_monday or compute_week_monday()
    plan_df = build_plan_df(selected_items_df, week_monday, rules)
    out_path = smoke_plan_excel_path(week_monday)
    write_smoke_plan_excel(
        str(out_path),
        plan_df,
        week_monday=week_monday,
        sheet_name=None,                  
        template_path=str(smoke_template_path()),
    )
    return plan_df, str(out_path)
