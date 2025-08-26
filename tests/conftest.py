# tests/conftest.py
import sys
from pathlib import Path
import pytest

# Přidej kořen projektu do sys.path (pro jistotu na Windows)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))



@pytest.fixture()
def tmp_output(monkeypatch, tmp_path: Path):
    """
    Přesměruje OUTPUT_EXCEL do dočasného souboru,
    aby testy nešahaly na reálný 'vysledek.xlsx'.
    """
    test_excel = tmp_path / "vysledek.xlsx"

    # Přepiš konstantu v obou modulech
    monkeypatch.setattr("services.paths.OUTPUT_EXCEL", test_excel, raising=False)
    monkeypatch.setattr("services.excel_service.OUTPUT_EXCEL", test_excel, raising=False)

    return test_excel
