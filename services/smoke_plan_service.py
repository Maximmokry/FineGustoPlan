# -*- coding: utf-8 -*-
"""
Rozšířená doménová logika plánu uzení s kapacitami a dělením položek do více slotů.

Novinky oproti v1:
- Podpora kapacitních limitů na slot podle udírny a druhu masa.
- Automatické dělení položky do více slotů (parts), pokud množství > kapacita slotu.
- Zachování "base" ID položky pro synchronizaci naplánováno (polotovar_id_base).

Základ:
- Po–So (6 dní), 4 udírny, 7 pozic.
- Prefill round-robin, ale vkládá části (parts) podle kapacit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Protocol, Tuple

import math
import pandas as pd

from services.smoke_capacity import CapacityRules

DAYS_PER_WEEK = 6
SMOKERS_COUNT = 4
ROWS_PER_SMOKER = 7

CZECH_WEEKDAYS = [
    "Pondělí",
    "Úterý",
    "Středa",
    "Čtvrtek",
    "Pátek",
    "Sobota",
]


@dataclass(frozen=True)
class Slot:
    day_idx: int
    smoker_idx: int
    row_idx: int

    def key(self) -> Tuple[int, int, int]:
        return (self.day_idx, self.smoker_idx, self.row_idx)


@dataclass
class Item:
    polotovar_id_base: str
    polotovar_nazev: str
    mnozstvi: Optional[float] = None
    jednotka: Optional[str] = None
    poznamka: Optional[str] = None
    meat_type: Optional[str] = None  # druh masa

    # interní pomocné – při splitu vznikají části s vlastním ID
    part_index: Optional[int] = None

    @property
    def polotovar_id(self) -> str:
        if self.part_index is None:
            return self.polotovar_id_base
        return f"{self.polotovar_id_base}::part{self.part_index}"


class SmokePrefillStrategy(Protocol):
    def run(self, plan: "SmokePlan", items: List[Item]) -> None: ...


# -------------------------------- utils --------------------------------

def _first_non_empty(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _ensure_item_id(row: pd.Series) -> str:
    if "polotovar_id" in row and pd.notna(row["polotovar_id"]):
        return str(row["polotovar_id"])
    parts = []
    for key in ("polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka", "mnozstvi"):
        if key in row and pd.notna(row[key]):
            parts.append(str(row[key]))
    if parts:
        return "|".join(parts)
    return f"rowidx:{getattr(row, 'name', 'x')}"


def next_monday(base: Optional[date] = None) -> date:
    d = base or date.today()
    days_ahead = (7 - d.weekday()) % 7
    days_ahead = 7 if days_ahead == 0 else days_ahead
    return d + timedelta(days=days_ahead)


# -------------------------------- model --------------------------------
class SmokePlan:
    def __init__(self, week_monday: date,
                 smokers: int = SMOKERS_COUNT,
                 rows_per_smoker: int = ROWS_PER_SMOKER,
                 capacity_rules: Optional[CapacityRules] = None):
        self.week_monday: date = week_monday
        self.smokers = smokers
        self.rows_per_smoker = rows_per_smoker
        self.days = DAYS_PER_WEEK
        self.rules = capacity_rules or CapacityRules()

        self._grid: Dict[Tuple[int, int, int], Item] = {}

    def free_slots(self, day_idx: int, smoker_idx: int) -> List[Slot]:
        slots = []
        for r in range(self.rows_per_smoker):
            key = (day_idx, smoker_idx, r)
            if key not in self._grid:
                slots.append(Slot(day_idx, smoker_idx, r))
        return slots

    def place(self, item: Item, slot: Slot) -> bool:
        if not (0 <= slot.day_idx < self.days):
            return False
        if not (0 <= slot.smoker_idx < self.smokers):
            return False
        if not (0 <= slot.row_idx < self.rows_per_smoker):
            return False
        key = slot.key()
        if key in self._grid:
            return False  # pro prefill nechceme swap, pouze prázdné
        self._grid[key] = item
        return True

    def to_records(self) -> List[Dict]:
        rows: List[Dict] = []
        for day in range(self.days):
            day_date = self.week_monday + timedelta(days=day)
            den = CZECH_WEEKDAYS[day]
            for smoker in range(self.smokers):
                for row in range(self.rows_per_smoker):
                    key = (day, smoker, row)
                    item = self._grid.get(key)
                    rows.append({
                        "datum": day_date,
                        "den": den,
                        "udirna": smoker + 1,
                        "pozice": row + 1,
                        "polotovar_id": getattr(item, "polotovar_id", None) if item else None,
                        "polotovar_id_base": getattr(item, "polotovar_id_base", None) if item else None,
                        "polotovar_nazev": getattr(item, "polotovar_nazev", None) if item else None,
                        "mnozstvi": getattr(item, "mnozstvi", None) if item else None,
                        "jednotka": getattr(item, "jednotka", None) if item else None,
                        "poznamka": getattr(item, "poznamka", None) if item else None,
                        "meat_type": getattr(item, "meat_type", None) if item else None,
                        "part_index": getattr(item, "part_index", None) if item else None,
                    })
        return rows

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame.from_records(self.to_records())


# ---------------------------- strategie ----------------------------
class CapacityAwarePrefillStrategy:
    """Prefill, který respektuje kapacity – dělí položky na části a plní round-robin.

    Logika:
      1) Pro každý slot (day→smoker→row) spočti max kapacitu dle `rules` a `meat_type`.
      2) Z položky ber po částech tak, aby běžná část = kapacita slotu; poslední část
         může být menší (zbytek).
      3) Každou část vlož do nejbližšího volného slotu.
    """

    def __init__(self, rules: Optional[CapacityRules] = None):
        self.rules = rules or CapacityRules()

    def run(self, plan: SmokePlan, items: List[Item]) -> None:
        # kurzor přes mřížku – POŘADÍ: den -> udírna -> řádek
        day = 0
        smoker = 0
        row = 0

        def next_cursor():
            """Posun v pořadí: smoker -> row -> day (round-robin přes udírny)."""
            nonlocal day, smoker, row
            smoker += 1
            if smoker >= plan.smokers:
                smoker = 0
                row += 1
                if row >= plan.rows_per_smoker:
                    row = 0
                    day += 1
                    if day >= plan.days:
                        day = 0

        total_slots = plan.days * plan.smokers * plan.rows_per_smoker

        def find_next_free_slot() -> Optional[Slot]:
            """Najdi další volný slot od aktuálního kurzoru s pořadím day->smoker->row."""
            nonlocal day, smoker, row
            scanned = 0
            d, s, r = day, smoker, row
            while scanned < total_slots:
                slot = Slot(d, s, r)
                if slot.key() not in plan._grid:
                    # nastav sdílený kurzor na nalezený slot (aby next_cursor navázal správně)
                    day, smoker, row = d, s, r
                    return slot
                # posun v pořadí: smoker -> row -> day
                s += 1
                if s >= plan.smokers:
                    s = 0
                    r += 1
                    if r >= plan.rows_per_smoker:
                        r = 0
                        d += 1
                        if d >= plan.days:
                            d = 0
                scanned += 1
            return None

        used_slots = 0

        for base in items:
            remaining = float(base.mnozstvi or 0.0)
            part_idx = 1

            # Bez množství: vlož jednou bez dávky
            if remaining <= 0:
                slot = find_next_free_slot()
                if slot and plan.place(Item(
                    polotovar_id_base=base.polotovar_id_base,
                    polotovar_nazev=base.polotovar_nazev,
                    mnozstvi=None,
                    jednotka=base.jednotka,
                    poznamka=base.poznamka,
                    meat_type=base.meat_type,
                    part_index=None,
                ), slot):
                    used_slots += 1
                    next_cursor()
                continue

            # Dělení dle KAPACITY SKUTEČNÉHO SLOTU (podle udírny slotu!)
            while remaining > 0 and used_slots < total_slots:
                slot = find_next_free_slot()
                if slot is None:
                    break

                cap = self.rules.capacity_for(base.meat_type, slot.smoker_idx)
                if cap <= 0:
                    cap = remaining
                dose = min(remaining, cap)

                if plan.place(Item(
                    polotovar_id_base=base.polotovar_id_base,
                    polotovar_nazev=base.polotovar_nazev,
                    mnozstvi=dose,
                    jednotka=base.jednotka,
                    poznamka=base.poznamka,
                    meat_type=base.meat_type,
                    part_index=part_idx,
                ), slot):
                    used_slots += 1
                    remaining -= dose
                    part_idx += 1
                    next_cursor()
                else:
                    # teoreticky obsazené – zkus další slot
                    next_cursor()
                    continue



# ---------------------- převod DF -> Item list ----------------------

def dataframe_to_items(df: pd.DataFrame) -> List[Item]:
    name_col = _first_non_empty(df, ["polotovar_nazev", "nazev", "produkt", "name"]) or "polotovar_nazev"
    qty_col = _first_non_empty(df, ["mnozstvi", "qty"]) or "mnozstvi"
    unit_col = _first_non_empty(df, ["jednotka", "mj"]) or "jednotka"
    note_col = _first_non_empty(df, ["poznamka", "pozn"]) or "poznamka"
    type_col = _first_non_empty(df, ["meat_type", "druh", "druh_masa", "skupina"])  # volitelné

    items: List[Item] = []
    for _, row in df.iterrows():
        base_id = _ensure_item_id(row)
        items.append(
            Item(
                polotovar_id_base=base_id,
                polotovar_nazev=str(row.get(name_col, "")),
                mnozstvi=float(row.get(qty_col)) if qty_col in row and pd.notna(row.get(qty_col)) else None,
                jednotka=(row.get(unit_col) if unit_col in row else None),
                poznamka=(row.get(note_col) if note_col in row else None),
                meat_type=(str(row.get(type_col)) if type_col and type_col in df.columns else None),
            )
        )
    return items
