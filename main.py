# main.py
from __future__ import annotations
import pandas as pd

from services.excel_service import ensure_output_excel_generic
from services.paths import OUTPUT_EXCEL
from services.ingredients_logic import compute_plan as compute_plan_ingredients, compute_and_write_ingredients_excel
from services.semis_logic import compute_plan_semifinished

# veřejné API beze změny názvů (kvůli kompatibilitě)

def compute_plan() -> pd.DataFrame:
    """
    Spočítá potřebu ingrediencí a zachová 'koupeno'.
    Navíc přidává vazby for_* (for_datum, for_polotovar_*), aby GUI dokázalo
    „zeleně podtrhnout“ polotovary, pro které jsou všechny ingredience koupené.
    """
    return compute_plan_ingredients()

def compute_and_write_plan_excel() -> pd.DataFrame:
    """
    Convenience – spočítat a zapsat ingredience do OUTPUT_EXCEL.
    """
    df = compute_plan_ingredients()
    ensure_output_excel_generic(df, OUTPUT_EXCEL)
    return df

def compute_plan_semifinished_wrapper():
    """
    Zachová starý název symbolu, pokud ho někde používáš.
    """
    return compute_plan_semifinished()
