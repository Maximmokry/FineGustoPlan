# -*- coding: utf-8 -*-
"""
Cesty pro plán uzení – generování názvu souboru a cílové složky "plan uzeni".

Snaží se odvodit základní výstupní adresář z `services.paths.OUTPUT_SEMI_EXCEL`.
Pokud není k dispozici, použije aktuální pracovní adresář.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

try:
    # Váš existující modul s cestami – použijeme pro odvození výstupního adresáře
    from services.paths import OUTPUT_SEMI_EXCEL  # type: ignore
except Exception:
    OUTPUT_SEMI_EXCEL = None  # fallback níže


def _base_results_dir() -> Path:
    if OUTPUT_SEMI_EXCEL:
        try:
            p = Path(OUTPUT_SEMI_EXCEL).resolve().parent
            if p.exists():
                return p
        except Exception:
            pass
    # fallback – ./results
    p = Path.cwd() / "results"
    p.mkdir(parents=True, exist_ok=True)
    return p


def smoke_template_path() -> Path:
    
    base = _base_results_dir()
    return base /  "data" / "plan_udiren_template.xlsx"
    
    

def plan_uzeni_dir() -> Path:
    base = _base_results_dir()
    target = base / "plan uzeni"
    target.mkdir(parents=True, exist_ok=True)
    return target


def smoke_plan_excel_path(monday: date) -> Path:
    """Název souboru: plan_uzeni_YYYY_MM_DD.xlsx (pondělí týdne)."""
    fname = f"plan_uzeni_{monday:%Y_%m_%d}.xlsx"
    return plan_uzeni_dir() / fname
