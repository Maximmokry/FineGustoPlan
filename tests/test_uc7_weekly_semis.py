# tests/test_uc7_weekly_semis.py
import pandas as pd
import datetime as dt
import importlib

# --- Pomocný stub pro PySimpleGUIQt, aby testy byly úplně headless ---
class _SGStub:
    def Text(self, *args, **kwargs):
        # Vrací jen jednoduchý popis, samotný obsah nás v testech nezajímá
        return ("Text", args, kwargs)

    def Checkbox(self, *args, **kwargs):
        return ("Checkbox", args, kwargs)

# (Column / Window apod. jsou až ve vyšších vrstvách, které netestujeme.)

def _make_df_main():
    """
    Vytvoří vstupní DataFrame s polotovary:
      - Dvě položky ve STEJNÉM týdnu (Po–Ne), shodné SK/RC/Název/MJ → musí se sečíst.
      - Jedna položka v jiném týdnu / nebo s jinými klíči → vlastní skupina.
    """
    # Pátek 2025-05-02 patří do týdne Po 2025-04-28 – Ne 2025-05-04
    # Středa 2025-05-07 patří do týdne Po 2025-05-05 – Ne 2025-05-11
    data = [
        # Skupina A – stejný týden, stejné klíče → sečte se (10 + 15 = 25)
        {
            "datum": dt.date(2025, 5, 1),  # Čt – týden 28.4.–4.5.
            "polotovar_sk": "300", "polotovar_rc": "11",
            "polotovar_nazev": "Uzený polotovar A", "jednotka": "kg",
            "potreba": 10,
            "vyrobeno": False,
        },
        {
            "datum": dt.date(2025, 5, 2),  # Pá – stejný týden
            "polotovar_sk": "300", "polotovar_rc": "11",
            "polotovar_nazev": "Uzený polotovar A", "jednotka": "kg",
            "potreba": 15,
            "vyrobeno": False,
        },

        # Skupina B – jiný týden
        {
            "datum": dt.date(2025, 5, 7),  # St – týden 5.5.–11.5.
            "polotovar_sk": "301", "polotovar_rc": "12",
            "polotovar_nazev": "Polotovar B", "jednotka": "kg",
            "potreba": 5,
            "vyrobeno": False,
        },
    ]
    return pd.DataFrame(data)

def test_uc7_weekly_aggregate_and_map(monkeypatch):
    """
    UC7: Týdenní souhrn polotovarů (Po–Ne) + mapování checkboxu “Naplánováno”
    na VŠECHNY zdrojové řádky dané týdenní skupiny.
    """
    # Import modulu s funkcemi, které testujeme
    semis_mod = importlib.import_module("gui.results_semis_window")

    # Stubnout celé sg uvnitř modulu, aby se nic GUI nevytvářelo
    monkeypatch.setattr(semis_mod, "sg", _SGStub(), raising=True)

    df_main = _make_df_main()

    # 1) Ověř agregaci po týdnech
    agg = semis_mod._aggregate_weekly(df_main.copy(), "vyrobeno")

    # Očekáváme 2 skupiny: A (28.4.–4.5.) a B (5.5.–11.5.)
    # Najdeme řádky podle klíčů
    # Skupina A (SK=300, RC=11, název=Uzený polotovar A, MJ=kg), suma = 25
    grp_a = agg[(agg["polotovar_sk"] == "300")
                & (agg["polotovar_rc"] == "11")
                & (agg["polotovar_nazev"] == "Uzený polotovar A")
                & (agg["jednotka"] == "kg")]
    assert len(grp_a) == 1, "Skupina A by měla být sloučena do jednoho řádku"
    assert float(grp_a.iloc[0]["potreba"]) == 25.0, "Součet 10 + 15 musí být 25"

    # Kontrola textového labelu týdne (Po–Ne): pro 1.–2.5.2025 je to 28.04.2025 – 04.05.2025
    assert "28.04.2025" in grp_a.iloc[0]["datum"] and "04.05.2025" in grp_a.iloc[0]["datum"]

    # Skupina B (SK=301, RC=12, …), suma = 5, týden 05.05.2025 – 11.05.2025
    grp_b = agg[(agg["polotovar_sk"] == "301")
                & (agg["polotovar_rc"] == "12")
                & (agg["polotovar_nazev"] == "Polotovar B")
                & (agg["jednotka"] == "kg")]
    assert len(grp_b) == 1, "Skupina B má být samostatná"
    assert float(grp_b.iloc[0]["potreba"]) == 5.0
    assert "05.05.2025" in grp_b.iloc[0]["datum"] and "11.05.2025" in grp_b.iloc[0]["datum"]

    # 2) Ověř _build_rows v weekly režimu → buy_map musí ukazovat na všechny zdrojové indexy skupiny
    # Připrav prázdnou detail mapu (pro test UC7 detaily neřešíme)
    detail_map = {}

    rows_layout, buy_map, rowkey_map = semis_mod._build_rows(
        df_main.copy(),
        detail_map,
        col_k="vyrobeno",
        show_details=False,
        weekly_sum=True,
    )

    # Měli bychom mít dvě skupinové checkboxy (pro A a B), jejich klíče začínají "-WSEMI-"
    w_check_keys = [k for k in buy_map.keys() if k.startswith("-WSEMI-")]
    assert len(w_check_keys) == 2, "V weekly režimu očekáváme 2 checkboxy (pro skupinu A a B)"

    # Najdi, který checkbox odpovídá skupině A: musí obsahovat indexy dvou prvních řádků (0 a 1)
    # (Pozn.: indexy z původního df_main – jejich pořadí je tak, jak jsme data vložili)
    idx_set = {0, 1}
    a_key = None
    for k in w_check_keys:
        idxs = set(buy_map[k])
        if idxs == idx_set:
            a_key = k
            break

    assert a_key is not None, "Pro skupinu A neexistuje weekly checkbox s indexy {0,1}"

    # “Zaškrtnutí” → označ všechny zdrojové řádky skupiny A jako vyrobeno=True
    df_after = df_main.copy()
    df_after.loc[list(idx_set), "vyrobeno"] = True

    # Když znovu přestavíme weekly layout, skupina A by měla zmizet z buy_map (už není nevyrobená)
    rows_layout2, buy_map2, _ = semis_mod._build_rows(
        df_after,
        detail_map,
        col_k="vyrobeno",
        show_details=False,
        weekly_sum=True,
    )

    # Zůstane jen skupina B (jeden checkbox)
    w_check_keys2 = [k for k in buy_map2.keys() if k.startswith("-WSEMI-")]
    assert len(w_check_keys2) == 1, "Po označení A jako vyrobené má zůstat jen 1 weekly checkbox (B)."

    # A kontrola, že ten jediný weekly checkbox odkazuje na třetí řádek (index 2)
    assert set(buy_map2[w_check_keys2[0]]) == {2}, "Zbývající weekly skupina musí ukazovat na index 2 (B)."
