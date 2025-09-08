def test_uc17_empty_slots_with_dose_only(tmp_path):
    print("UC17: I bez položek se uloží 'Dávka' do Excelu na odp. slotech.")
    from tests._smoke_test_utils import create_smoke_template, open_xlsx
    from services.smoke_excel_service import write_smoke_plan_excel
    from services.smoke_plan_service import SmokePlan
    from datetime import date

    template = create_smoke_template(tmp_path / "tpl.xlsx")
    week = date(2025, 9, 15)

    plan = SmokePlan(week)
    df = plan.to_dataframe()
    for c in ["rc", "davka", "shift", "poznamka"]:
        if c not in df.columns:
            df[c] = None

    # Po / Udírna 2 / Pozice 3
    mask = (df["datum"] == week) & (df["udirna"] == 2) & (df["pozice"] == 3)
    df.loc[mask, "davka"] = "pomalé sušení"

    out = tmp_path / "plan.xlsx"
    write_smoke_plan_excel(str(out), df, week_monday=week, template_path=str(template))

    # U2 blok začíná ve sloupci 6 → name=7, poznámka=8, DÁVKA=9; řádek = 6 + pozice(3) = 9
    wb = open_xlsx(out)
    ws = wb.active
    assert (ws.cell(9, 9).value or "").strip() == "pomalé sušení"  # správně Dávka ve sloupci 9
    assert (ws.cell(9, 7).value or "") == ""  # 'Druh' (name) zůstává prázdný
