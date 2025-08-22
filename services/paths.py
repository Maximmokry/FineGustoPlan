# services/paths.py
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

RECEPTY_FILE = DATA_DIR / "recepty.xlsx"
PLAN_FILE    = BASE_DIR / "plan.xlsx"

OUTPUT_EXCEL      = BASE_DIR / "vysledek.xlsx"       # ingredience (nákup)
OUTPUT_SEMI_EXCEL = BASE_DIR / "polotovary.xlsx"     # plán polotovarů (SK 300)
