# -*- coding: utf-8 -*-
"""
Export plánu uzení do Excelu přesně podle šablony (1 list, Po–So, 4 udírny, 7 řádků).

Vstupem je DataFrame z `SmokePlan.to_dataframe()` nebo ekvivalent se sloupci:
  - datum (datetime.date nebo pandas Timestamp)
  - den (text "Pondělí".."Sobota")
  - udirna (1..4)
  - pozice (1..7)
  - polotovar_id, polotovar_nazev, mnozstvi, jednotka, poznamka

Výstupní rozložení kopíruje šablonu: pro každý den hlavička se jménem dne a datem,
řádek s titulky čtyř udíren a pod nimi 7 řádků s kolonkami:
  "Pořadové číslo", "Druhy výrobku", "Poznámka", "Dávka", "Směna"

Pozn.: Druhý list se NEvytváří.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

try:
    import xlsxwriter  # noqa: F401
except Exception:
    xlsxwriter = None  # bude použito přes pandas.ExcelWriter(engine="xlsxwriter")

CZECH_WEEKDAYS = [
    "Pondělí",
    "Úterý",
    "Středa",
    "Čtvrtek",
    "Pátek",
    "Sobota",
]

HEADER_LABELS = ["Pořadové číslo", "Druhy výrobku", "Poznámka", "Dávka", "Směna"]
BLOCK_COLS = len(HEADER_LABELS)  # 5 sloupců na jednu udírnu
SMOKERS = 4
ROWS_PER_SMOKER = 7


def _ensure_datetime(d):
    if isinstance(d, pd.Timestamp):
        return d.to_pydatetime()
    return d

def write_smoke_plan_excel(path: str,
                           plan_df: pd.DataFrame,
                           week_monday: Optional[date] = None,
                           sheet_name: str = "Plan") -> None:
    if plan_df.empty:
        plan_df = _empty_plan_dataframe(week_monday)

    cols_needed = [
        "datum", "den", "udirna", "pozice",
        "polotovar_id", "polotovar_nazev", "mnozstvi", "jednotka", "poznamka", "shift",
    ]
    for c in cols_needed:
        if c not in plan_df.columns:
            plan_df[c] = pd.NA

    df = plan_df.copy()
    df["datum"] = pd.to_datetime(df["datum"]).dt.date

    if week_monday is None:
        if df["datum"].notna().any():
            week_monday = min(d for d in df["datum"] if d is not None)
        else:
            week_monday = date.today()

    df["_day_idx"] = (pd.to_datetime(df["datum"]) - pd.Timestamp(week_monday)).dt.days
    df.sort_values(["_day_idx", "udirna", "pozice"], inplace=True, kind="mergesort")

    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet(sheet_name)

        CZECH_WEEKDAYS = ["Pondělí","Úterý","Středa","Čtvrtek","Pátek","Sobota"]
        HEADER_LABELS = ["Pořadové číslo","Druhy výrobku","Poznámka","Dávka","Směna"]
        BLOCK_COLS = len(HEADER_LABELS)
        SMOKERS = 4
        ROWS_PER_SMOKER = 7

        fmt_day_title = workbook.add_format({"bold": True, "font_size": 12})
        fmt_ud_title  = workbook.add_format({"bold": True, "align": "center"})
        fmt_header    = workbook.add_format({"bold": True, "bg_color": "#F2F2F2", "border": 1})
        fmt_cell      = workbook.add_format({"border": 1})
        fmt_center    = workbook.add_format({"border": 1, "align": "center"})

        col_widths = [12, 28, 24, 10, 10]
        row_cursor = 0
        def _s(val):
            try:
                import pandas as pd  # jistota dostupnosti v rozsahu
                if pd.isna(val):
                    return ""
            except Exception:
                pass
            return "" if val is None else str(val)

        for day_offset, day_name in enumerate(CZECH_WEEKDAYS):
            day_date = pd.Timestamp(week_monday) + pd.Timedelta(days=day_offset)
            day_rows = df[df["_day_idx"] == day_offset]

            worksheet.write(row_cursor, 0, f"{day_name} {day_date.date()}", fmt_day_title)
            row_cursor += 1

            for s in range(SMOKERS):
                block_start_col = s * BLOCK_COLS
                worksheet.write(row_cursor, block_start_col, f"Udírna číslo {s+1}.", fmt_ud_title)
                for c in range(1, BLOCK_COLS):
                    worksheet.write(row_cursor, block_start_col + c, "", fmt_ud_title)
            row_cursor += 1

            for s in range(SMOKERS):
                block_start_col = s * BLOCK_COLS
                for c, label in enumerate(HEADER_LABELS):
                    worksheet.write(row_cursor, block_start_col + c, label, fmt_header)
                    worksheet.set_column(block_start_col + c, block_start_col + c, col_widths[c])
            row_cursor += 1

            for r in range(ROWS_PER_SMOKER):
                for s in range(SMOKERS):
                    block_start_col = s * BLOCK_COLS
                    worksheet.write(row_cursor, block_start_col + 0, r + 1, fmt_center)

                    rec = day_rows[(day_rows["udirna"] == (s + 1)) & (day_rows["pozice"] == (r + 1))]
                    name = note = dose = shift = ""
                    if not rec.empty:
                        row = rec.iloc[0]
                        name = _s(row.get("polotovar_nazev"))
                        note = _s(row.get("poznamka"))
                        unit = _s(row.get("jednotka"))
                        qty  = row.get("mnozstvi")
                        if pd.notna(qty):
                            dose = f"{qty} {unit}".strip()
                        shift = _s(row.get("shift"))

                    worksheet.write(row_cursor, block_start_col + 1, name, fmt_cell)
                    worksheet.write(row_cursor, block_start_col + 2, note, fmt_cell)
                    worksheet.write(row_cursor, block_start_col + 3, dose, fmt_center)
                    worksheet.write(row_cursor, block_start_col + 4, shift, fmt_center)
                row_cursor += 1

            row_cursor += 1


def _empty_plan_dataframe(week_monday: Optional[date]) -> pd.DataFrame:
    if week_monday is None:
        week_monday = date.today()
    records = []
    for day in range(6):
        cur = pd.Timestamp(week_monday) + pd.Timedelta(days=day)
        for smoker in range(1, 5):
            for pos in range(1, 8):
                records.append({
                    "datum": cur.date(),
                    "den": CZECH_WEEKDAYS[day],
                    "udirna": smoker,
                    "pozice": pos,
                })
    return pd.DataFrame.from_records(records)
