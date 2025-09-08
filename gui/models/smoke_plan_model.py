# -*- coding: utf-8 -*-
"""
SmokePlanModel – lehká datová vrstva nad `plan_df` pro GUI grid.

Záměrně bez Qt závislostí. GUI komponenta gridu může tuto třídu používat
pro načtení a úpravy dat. Controller drží instanci modelu nebo s ním pracuje
přímo přes metody controlleru; tato třída ale pomáhá s operacemi nad DF.
"""
from __future__ import annotations

from typing import Optional, Tuple
import pandas as pd
from datetime import date, timedelta

Coord = Tuple[int, int, int]


class SmokePlanModel:
    def __init__(self, week_monday: date) -> None:
        self._week = week_monday
        self._df: Optional[pd.DataFrame] = None

    # ------------------- core -------------------
    def load_from_df(self, plan_df: pd.DataFrame) -> None:
        self._df = plan_df.copy()

    def to_dataframe(self) -> pd.DataFrame:
        return self._df.copy() if self._df is not None else pd.DataFrame()

    # ------------------- helpers -------------------
    def _row_index(self, coord: Coord) -> Optional[int]:
        if self._df is None or self._df.empty:
            return None
        d, s, r = coord
        day_date = pd.Timestamp(self._week) + pd.Timedelta(days=d)
        m = (
            (pd.to_datetime(self._df["datum"]).dt.date == day_date.date()) &
            (self._df["udirna"] == (s + 1)) &
            (self._df["pozice"] == (r + 1))
        )
        idx = self._df[m].index
        return int(idx[0]) if len(idx) else None

    # ------------------- mutations -------------------
    def apply_move(self, src: Coord, dst: Coord) -> None:
        if self._df is None or self._df.empty:
            return
        a = self._row_index(src)
        b = self._row_index(dst)
        if a is None or b is None:
            return
        cols = [
            "polotovar_id", "polotovar_id_base", "polotovar_nazev",
            "mnozstvi", "jednotka", "poznamka", "meat_type", "part_index", "shift",
        ]
        tmp = self._df.loc[a, cols].copy()
        self._df.loc[a, cols] = self._df.loc[b, cols].values
        self._df.loc[b, cols] = tmp.values

    def set_note(self, coord: Coord, text: str) -> None:
        i = self._row_index(coord)
        if i is None:
            return
        self._df.loc[i, "poznamka"] = text

    def set_dose(self, coord: Coord, qty: Optional[float], unit: Optional[str]) -> None:
        i = self._row_index(coord)
        if i is None:
            return
        self._df.loc[i, "mnozstvi"] = qty
        if unit is not None:
            self._df.loc[i, "jednotka"] = unit

    # ------------------- read -------------------
    def cell_payload(self, coord: Coord) -> dict:
        i = self._row_index(coord)
        if i is None:
            return {}
        row = self._df.loc[i]
        return {
            "nazev": row.get("polotovar_nazev"),
            "poznamka": row.get("poznamka"),
            "mnozstvi": row.get("mnozstvi"),
            "jednotka": row.get("jednotka"),
            "shift": row.get("shift"),
            "polotovar_id": row.get("polotovar_id"),
            "polotovar_id_base": row.get("polotovar_id_base"),
            "meat_type": row.get("meat_type"),
            "part_index": row.get("part_index"),
        }
