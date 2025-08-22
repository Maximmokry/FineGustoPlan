# services/semi_excel_service.py
from pathlib import Path
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font
import services.paths as sp

from services.data_utils import to_bool_cell_excel, to_date_col


def _force_bool(df: pd.DataFrame, col: str):
    if col not in df.columns:
        df[col] = False
    df[col] = df[col].map(to_bool_cell_excel).astype(bool)


def ensure_output_semis_excel(df_main: pd.DataFrame, df_details: pd.DataFrame | None):
    """
    Zapíše polotovary do OUTPUT_SEMI_EXCEL:
      - Sheet 'Prehled'   : přesně df_main (s vyrobeno jako bool)
      - Sheet 'Detaily'   : přesně df_details (pokud je)
      - Sheet 'Polotovary': bloky s outline (master + podřádky rozpadů)
    """
    # Bezpečné kopie vstupů
    if df_main is None:
        df_main = pd.DataFrame()
    else:
        df_main = df_main.copy()

    if df_details is None:
        df_details = pd.DataFrame()
    else:
        df_details = df_details.copy()

    # Normalizace a typy
    df_main.columns = [str(c).strip() for c in df_main.columns]
    to_date_col(df_main, "datum")
    _force_bool(df_main, "vyrobeno")

    if not df_details.empty:
        df_details.columns = [str(c).strip() for c in df_details.columns]
        to_date_col(df_details, "datum")
    else:
        df_details = pd.DataFrame(columns=[
            "datum", "polotovar_sk", "polotovar_rc",
            "vyrobek_sk", "vyrobek_rc", "vyrobek_nazev",
            "mnozstvi", "jednotka"
        ])

    # --- zapiš Prehled + Detaily ---
    out = Path(sp.OUTPUT_SEMI_EXCEL)
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        df_main.to_excel(xw, sheet_name="Prehled", index=False)
        df_details.to_excel(xw, sheet_name="Detaily", index=False)

    # --- vytvoř / obnov sheet "Polotovary" ---
    wb = load_workbook(out)
    if "Polotovary" in wb.sheetnames:
        del wb["Polotovary"]
    ws = wb.create_sheet("Polotovary")


            # Hlavička – na 6. pozici vyžaduje test prázdný řetězec (""), nikoli None
    header = ["Datum", "SK", "Reg.č.", "Polotovar", "Množství", "", "Vyrobeno", "Poznámka"]
    ws.append(header)

    # Donuť openpyxl uložit skutečný prázdný řetězec jako text
    c = ws.cell(row=1, column=6)
    c.value = ""
    c.data_type = "s"   # <— DŮLEŽITÉ

    for col in range(1, len(header) + 1):
        ws.cell(row=1, column=col).font = Font(bold=True)



    # Šířky sloupců
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 6
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 42
    ws.column_dimensions["E"].width = 12
    ws.column_dimensions["F"].width = 6
    ws.column_dimensions["G"].width = 10
    ws.column_dimensions["H"].width = 24

    # Mapa detailů (datum, sk, rc)
    detail_map: dict[tuple, list] = {}
    if not df_details.empty:
        for _, r in df_details.iterrows():
            k = (
                r.get("datum", None),
                str(r.get("polotovar_sk", "")).strip(),
                str(r.get("polotovar_rc", "")).strip(),
            )
            detail_map.setdefault(k, []).append(r)

    # Seřazení df_main
    if "datum" in df_main.columns:
        df_main = df_main.sort_values(["datum", "polotovar_sk", "polotovar_rc"], kind="mergesort")

    current_row = 2
    for _, r in df_main.iterrows():
        k = (
            r.get("datum", None),
            str(r.get("polotovar_sk", "")).strip(),
            str(r.get("polotovar_rc", "")).strip(),
        )
        master = [
            r.get("datum", ""),
            r.get("polotovar_sk", ""),
            r.get("polotovar_rc", ""),
            r.get("polotovar_nazev", "") if "polotovar_nazev" in r else r.get("nazev", ""),
            r.get("potreba", ""),
            r.get("jednotka", ""),   # jednotka patří do 6. sloupce (bez hlavičky)
            bool(r.get("vyrobeno", False)),
            "",
        ]
        ws.append(master)
        ws.cell(current_row, 1).alignment = Alignment(vertical="center")
        master_row = current_row
        current_row += 1

        # Podřádky – ve správných sloupcích
        children = detail_map.get(k, [])
        for ch in children:
            ws.append([
                "",
                str(ch.get("vyrobek_sk", "")).strip(),
                str(ch.get("vyrobek_rc", "")).strip(),
                f"↳ {str(ch.get('vyrobek_nazev', '')).strip()}",
                ch.get("mnozstvi", ""),
                ch.get("jednotka", ""),
                "",
                "",
            ])
            ws.row_dimensions[current_row].outlineLevel = 1
            current_row += 1

        if children:
            ws.cell(master_row, 8, "(obsahuje rozpad)")

    ws.sheet_properties.outlinePr.summaryBelow = True
    wb.save(out)
