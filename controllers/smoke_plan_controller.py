# -*- coding: utf-8 -*-
"""
SmokePlanController – řídicí vrstva mezi GUI a doménovou logikou.

Nezávislé na Qt; pracuje pouze s pandas DataFrame a services.* moduly.

Zodpovědnosti:
- drží `week_monday` (pondělí týdne) a `CapacityRules`
- vystaví metody pro předvyplnění plánu (prefill), ruční úpravy gridu,
  uložení do Excelu a synchronizaci příznaků do tabulky polotovarů

Koordináty slotu: `coord = (day_idx, smoker_idx, row_idx)`
- day_idx: 0..5 (Po..So)
- smoker_idx: 0..3 (Udírna 1..4)
- row_idx: 0..6 (řádky 1..7)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

import pandas as pd

# logika (v1 název modulů, ale s v2 chováním dle projektu)
from services import smoke_orchestrator as smo
from services.smoke_capacity import CapacityRules
from services.smoke_paths import smoke_plan_excel_path
from services.smoke_excel_service import write_smoke_plan_excel


Coord = Tuple[int, int, int]


@dataclass
class ControllerState:
    week_monday: date
    rules: CapacityRules


class SmokePlanController:
    def __init__(self,
                 capacity_rules: Optional[CapacityRules] = None,
                 week_monday: Optional[date] = None) -> None:
        wm = week_monday or smo.compute_week_monday()
        self._state = ControllerState(
            week_monday=wm,
            rules=capacity_rules or CapacityRules(),
        )
        self._plan_df: Optional[pd.DataFrame] = None
        self._selected_df: Optional[pd.DataFrame] = None

    # ======================== PŘEDVYPLNĚNÍ ========================
    def prefill(self, selected_items_df: pd.DataFrame) -> pd.DataFrame:
        """Postaví plán z vybraných polotovarů a uloží DF do controlleru.
        Vrací `plan_df`.
        """
        self._selected_df = selected_items_df.copy()
        plan_df = smo.build_plan_df(selected_items_df,
                                    week_monday=self._state.week_monday,
                                    rules=self._state.rules)  # type: ignore[arg-type]
        self._plan_df = plan_df
        return plan_df.copy()

    def load_plan(self, plan_df: pd.DataFrame) -> None:
        self._plan_df = plan_df.copy()

    def plan_df(self) -> pd.DataFrame:
        if self._plan_df is None:
            return pd.DataFrame()
        return self._plan_df.copy()

    def week_monday(self) -> date:
        return self._state.week_monday

    # ======================== RUČNÍ ÚPRAVY ========================
    @staticmethod
    def _key_tuple(day_idx: int, smoker_idx: int, row_idx: int) -> Tuple[int, int, int]:
        return (int(day_idx), int(smoker_idx), int(row_idx))

    def _find_row_index(self, coord: Coord) -> Optional[int]:
        if self._plan_df is None or self._plan_df.empty:
            return None
        day_idx, smoker_idx, row_idx = coord
        df = self._plan_df
        # ve storage je udirna/pozice 1-based, dny držíme přes datum
        day_date = pd.Timestamp(self._state.week_monday) + pd.Timedelta(days=day_idx)
        mask = (
            (pd.to_datetime(df["datum"]).dt.date == day_date.date()) &
            (df["udirna"] == (smoker_idx + 1)) &
            (df["pozice"] == (row_idx + 1))
        )
        idx = df[mask].index
        return int(idx[0]) if len(idx) else None

    def apply_move(self, src: Coord, dst: Coord) -> None:
        """Vymění obsah dvou slotů (swap)."""
        if self._plan_df is None or self._plan_df.empty:
            return
        a = self._find_row_index(src)
        b = self._find_row_index(dst)
        if a is None or b is None:
            return
        cols_payload = [
            "polotovar_id", "polotovar_id_base", "polotovar_nazev",
            "mnozstvi", "jednotka", "poznamka", "meat_type", "part_index", "shift",
        ]
        df = self._plan_df
        tmp = df.loc[a, cols_payload].copy()
        df.loc[a, cols_payload] = df.loc[b, cols_payload].values
        df.loc[b, cols_payload] = tmp.values

    def set_note(self, coord: Coord, text: str) -> None:
        if self._plan_df is None:
            return
        i = self._find_row_index(coord)
        if i is None:
            return
        self._plan_df.loc[i, "poznamka"] = text

    def set_dose(self, coord: Coord, qty: Optional[float], unit: Optional[str]) -> None:
        if self._plan_df is None:
            return
        i = self._find_row_index(coord)
        if i is None:
            return
        # množství v plánu je per-slot
        self._plan_df.loc[i, "mnozstvi"] = qty
        if unit is not None:
            self._plan_df.loc[i, "jednotka"] = unit

    # ======================== ULOŽENÍ / SYNC ========================
    def save_excel(self, sheet_name: str = "Plan") -> str:
        if self._plan_df is None:
            raise ValueError("Plan není připraven")
        out_path = smoke_plan_excel_path(self._state.week_monday)
        write_smoke_plan_excel(str(out_path), self._plan_df, self._state.week_monday, sheet_name=sheet_name)
        return str(out_path)

    def mark_planned(self, items_df: pd.DataFrame) -> pd.DataFrame:
        if self._plan_df is None:
            return items_df.copy()
        updated = smo.sync_flags(items_df, self._plan_df)
        return updated

    # ======================== NÁHRADNÍ PREFILL (pokud je třeba) ========================
    def rebuild_after_manual_moves(self) -> pd.DataFrame:
        """Není povinné – pokud byste chtěli znovu přepočítat/zarovnat DF po větších zásazích."""
        return self.plan_df()
