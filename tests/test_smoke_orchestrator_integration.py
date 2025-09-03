# -*- coding: utf-8 -*-
import re
import pandas as pd

# Orchestrator pod starým názvem, ale s v2 logikou (podle projektu)
from services import smoke_orchestrator as smo
from services import smoke_paths


def test_plan_and_save_integration(tmp_path, monkeypatch):
    # připrav položky: jedna velká (split do 3 partů), jedna malá (1 slot)
    items = pd.DataFrame([
        {"polotovar_id": "A", "polotovar_nazev": "Šunka", "mnozstvi": 950, "jednotka": "kg", "meat_type": "veprove"},
        {"polotovar_id": "B", "polotovar_nazev": "Krkovička", "mnozstvi": 100, "jednotka": "kg", "meat_type": "veprove"},
    ])

    # fixní pondělí, aby byl deterministický název souboru
    week = pd.Timestamp("2025-09-08").date()

    # přesměruj výstupní cestu orchestrátoru do tmp
    def fake_path(_monday):
        # zkusme si zachovat i konvenci názvu
        return tmp_path / f"plan_uzeni_{_monday:%Y_%m_%d}.xlsx"
    monkeypatch.setattr(smoke_paths, "smoke_plan_excel_path", fake_path)

    plan_df, out_path = smo.plan_and_save(items, week_monday=week)

    # 1) plán existuje a obsahuje rozdělení na 3 + 1 část
    non_empty = plan_df.dropna(subset=["polotovar_id"]).copy()
    doses = [float(x) for x in non_empty["mnozstvi"].dropna().tolist()]
    assert len(non_empty) >= 4
    assert sorted(doses, reverse=True)[:3] == [400.0, 300.0, 250.0]

    # 2) soubor je vytvořen a jméno odpovídá konvenci
    assert out_path.endswith("plan_uzeni_2025_09_08.xlsx")

    # 3) sync příznaků zafunguje
    synced = smo.sync_flags(items, plan_df)
    assert bool(synced.set_index("polotovar_id").loc["A", "planned_for_smoking"]) is True
    assert bool(synced.set_index("polotovar_id").loc["B", "planned_for_smoking"]) is True

    # 4) filter_unplanned vrátí prázdno pro již naplánované (po syncu)
    unplanned = smo.filter_unplanned(synced)
    assert unplanned.empty

    # 5) assign_shift_column doplní shift a nic nerozbije
    def resolver(row):
        # pro ukázku: pondělí denní směna, jinak prázdné
        return "D" if str(row.get("den")) == "Pondělí" else ""
    plan_shift = smo.assign_shift_column(plan_df, resolver)
    assert "shift" in plan_shift.columns
    assert (plan_shift[plan_shift["den"] == "Pondělí"]["shift"] == "D").any()
