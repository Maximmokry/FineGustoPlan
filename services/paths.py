# services/paths.py
from pathlib import Path
import sys

if getattr(sys, "frozen", False):
    # cesta vedle EXE (Planovac_app.exe)
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    # běh z repo/prototypu
    BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

RECEPTY_FILE = DATA_DIR / "recepty.xlsx"
PLAN_FILE    = BASE_DIR / "plan.xlsx"

OUTPUT_EXCEL      = BASE_DIR / "ingredience.xlsx"
OUTPUT_SEMI_EXCEL = BASE_DIR / "polotovary.xlsx"
