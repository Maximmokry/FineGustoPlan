# tests/test_data_utils.py
import pandas as pd
from services.data_utils import find_col, to_date_col, to_bool_cell_excel

def test_find_col_case_insensitive():
    df = pd.DataFrame({" KoUpEnO ": [1], "DATUM": ["2025-01-02"]})
    assert find_col(df, ["koupeno"]) == " KoUpEnO "
    assert find_col(df, ["datum"]) == "DATUM"
    assert find_col(df, ["neexistuje"]) is None

def test_to_date_col_mutates_series_to_date():
    df = pd.DataFrame({"datum": ["2025-01-01 13:45:00", "not-a-date", None]})
    to_date_col(df, "datum")
    assert str(df.loc[0, "datum"]) == "2025-01-01"
    assert pd.isna(df.loc[1, "datum"])  # špatná hodnota -> NaT -> NaN (po .dt.date)
    assert pd.isna(df.loc[2, "datum"])

def test_to_bool_cell_excel_conversions():
    # základní typy
    assert to_bool_cell_excel(True) is True
    assert to_bool_cell_excel(False) is False
    # čísla
    assert to_bool_cell_excel(1) is True
    assert to_bool_cell_excel(0) is False
    assert to_bool_cell_excel(3.14) is True
    # string čísla
    assert to_bool_cell_excel("1") is True
    assert to_bool_cell_excel("0") is False
    assert to_bool_cell_excel("  1  ") is True
    assert to_bool_cell_excel("0,0") is False  # evropská čárka
    # prázdno a texty -> False (neřešíme jazyky)
    assert to_bool_cell_excel("") is False
    assert to_bool_cell_excel("PRAVDA") is False
    assert to_bool_cell_excel("YES") is False
    assert to_bool_cell_excel(None) is False
