# -*- coding: utf-8 -*-
"""
Sync příznaků naplánováno s podporou splitovaných položek (parts).

`plan_df` může obsahovat `polotovar_id` ve tvaru "<base>::partN" a také sloupec
`polotovar_id_base`. Pro vyhodnocení planned_for_smoking bereme vždy BASE ID.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Dict

import pandas as pd

ID_FALLBACK_KEYS = ["polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka", "mnozstvi"]
PART_RE = re.compile(r"^(?P<base>.+?)::part\d+$")


def _ensure_base_id_series(df: pd.DataFrame) -> pd.Series:
    if "polotovar_id_base" in df.columns:
        return df["polotovar_id_base"].astype(str)
    if "polotovar_id" in df.columns:
        # odstraň případný suffix ::partN
        def strip_part(x: str) -> str:
            m = PART_RE.match(str(x))
            return m.group("base") if m else str(x)
        return df["polotovar_id"].astype(str).map(strip_part)
    parts = []
    for k in ID_FALLBACK_KEYS:
        parts.append(df[k].astype(str) if k in df.columns else "")
    if not parts:
        raise ValueError("Nelze sestavit identifikátor polotovaru – chybí polotovar_id i fallback sloupce.")
    sid = parts[0]
    for p in parts[1:]:
        sid = sid.astype(str) + "|" + p.astype(str)
    return sid


def apply_plan_flags(items_df: pd.DataFrame, plan_df: pd.DataFrame) -> pd.DataFrame:
    if items_df is None or items_df.empty:
        return items_df.copy() if items_df is not None else pd.DataFrame()

    out = items_df.copy()
    sid = _ensure_base_id_series(out).rename("polotovar_id_base")

    plan = plan_df.copy() if plan_df is not None else pd.DataFrame()
    id_to_date: Dict[str, date] = {}
    if not plan.empty:
        # preferuj explicitní base sloupec
        if "polotovar_id_base" in plan.columns:
            base = plan[plan["polotovar_id_base"].notna()][["polotovar_id_base", "datum"]].copy()
            base["datum"] = pd.to_datetime(base["datum"]).dt.date
            grp = base.groupby("polotovar_id_base")["datum"].min()
            id_to_date = grp.to_dict()
        elif "polotovar_id" in plan.columns:
            # strip ::part
            def to_base(x: str) -> str:
                m = PART_RE.match(str(x))
                return m.group("base") if m else str(x)
            base = plan[plan["polotovar_id"].notna()][["polotovar_id", "datum"]].copy()
            base["datum"] = pd.to_datetime(base["datum"]).dt.date
            base["polotovar_id_base"] = base["polotovar_id"].map(to_base)
            grp = base.groupby("polotovar_id_base")["datum"].min()
            id_to_date = grp.to_dict()

    out["planned_for_smoking"] = sid.map(lambda x: x in id_to_date)
    out["smoking_date"] = sid.map(lambda x: id_to_date.get(x))
    return out
