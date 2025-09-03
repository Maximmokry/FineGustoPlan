# services/data_loader.py
from __future__ import annotations
import pandas as pd
from services.paths import RECEPTY_FILE, PLAN_FILE
from services.data_utils import clean_columns, to_date_col

def nacti_data():
    """
    Načte receptury a plán z Excelů a provede základní očistu.
    Receptury: sheet 'HEO - Kusovníkové vazby platné '
    Plán:      libovolný sheet (default)
    """
    recepty = pd.read_excel(RECEPTY_FILE, sheet_name="HEO - Kusovníkové vazby platné ")
    plan    = pd.read_excel(PLAN_FILE)
    clean_columns(recepty)
    clean_columns(plan)
    if "datum" in plan.columns:
        to_date_col(plan, "datum")
    return recepty, plan
