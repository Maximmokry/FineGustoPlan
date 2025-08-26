# vyvolavac_hlasek_v5.py
# -*- coding: utf-8 -*-
"""
Skript, který postupně provede uživatele všemi chybovými hláškami
POZOR - není dokončen, nefunguje 100%
"""

import os
import sys
import shutil
import tempfile
import time
import contextlib
from pathlib import Path
from typing import Callable, List, Tuple

import pandas as pd

# ---------------- Cesty k souborům ----------------

def _detect_paths():
    """
    Načti cesty z services.paths pokud jde, jinak fallback.
      - PLAN_EXCEL? -> default 'plan.xlsx'
      - OUTPUT_EXCEL -> vysledek ingrediencí
      - OUTPUT_SEMI_EXCEL -> polotovary
    """
    PLAN = Path("plan.xlsx")
    INGR = Path("vysledek.xlsx")
    SEMI = Path("polotovary.xlsx")
    try:
        import services.paths as sp  # type: ignore
        PLAN = Path(getattr(sp, "PLAN_EXCEL", PLAN))
        INGR = Path(getattr(sp, "OUTPUT_EXCEL", INGR))
        SEMI = Path(getattr(sp, "OUTPUT_SEMI_EXCEL", SEMI))
    except Exception:
        pass
    return PLAN, INGR, SEMI

PLAN, INGR, SEMI = _detect_paths()

# ---------------- Utility ----------------

class FileLocker:
    """Zamkne soubor pro zápis (Windows msvcrt.locking + unix fallback držení handle)."""
    def __init__(self, path: Path):
        self.path = path
        self.f = None
        self._lock_size = 1024

    def lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        size = max(self.path.stat().st_size, self._lock_size)
        self.f = open(self.path, "r+b")
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, size)
        except Exception:
            pass

    def unlock(self):
        try:
            if os.name == "nt" and self.f is not None:
                import msvcrt  # type: ignore
                size = max(self.path.stat().st_size, self._lock_size)
                try:
                    self.f.seek(0)
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, size)
                except Exception:
                    pass
        finally:
            if self.f:
                try:
                    self.f.close()
                except Exception:
                    pass
            self.f = None

@contextlib.contextmanager
def locked_file(path: Path):
    locker = FileLocker(path)
    locker.lock()
    try:
        yield
    finally:
        locker.unlock()

def wait_user(msg: str):
    print("\n" + "-"*96)
    input(msg + "\n(Enter pokračuje) ")

def print_header(title: str, i: int, total: int):
    print("\n" + "="*96)
    print(f"[{i}/{total}] {title}")
    print("="*96)

def backup_files(tmp: Path):
    for p in (PLAN, INGR, SEMI):
        if p.exists():
            shutil.copy2(p, tmp / p.name)

def restore_files(tmp: Path):
    for p in (PLAN, INGR, SEMI):
        src = tmp / p.name
        if src.exists():
            shutil.copy2(src, p)

def safe_read_xlsx(path: Path) -> pd.DataFrame:
    try:
        return pd.read_excel(path)
    except Exception:
        return pd.DataFrame()

def ensure_exists_via_user(path: Path, message: str):
    """Jemně vyžádej, aby soubor existoval (uživatel ho vytvoří běžným použitím appky)."""
    if path.exists():
        return
    while not path.exists():
        wait_user(f"{message}\nAž bude soubor '{path.name}' vytvořen, stiskni Enter.")

# ---- helpery pro konkrétní scénáře ----

def corrupt_xlsx(path: Path):
    """Zkorumpuje xlsx (pro compute_*)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"NOT AN XLSX FILE")

def set_all_flag_true(path: Path, flag_col: str, create_min_rows=True):
    """Nastaví příznak (koupeno/vyrobeno) na True všem řádkům, vytvoří minimální data pokud je prázdno."""
    df = safe_read_xlsx(path)
    if df.empty and create_min_rows:
        if flag_col == "koupeno":
            df = pd.DataFrame({
                "datum": pd.to_datetime(["2025-01-06","2025-01-07"]),
                "ingredience_sk": [100, 100],
                "ingredience_rc": [1, 1],
                "nazev": ["Sůl", "Sůl"],
                "potreba": [1, 2],
                "jednotka": ["kg", "kg"],
            })
        else:
            df = pd.DataFrame({
                "datum": pd.to_datetime(["2025-01-06","2025-01-07"]),
                "polotovar_sk": [300, 300],
                "polotovar_rc": [88, 88],
                "polotovar_nazev": ["Uzené", "Uzené"],
                "potreba": [5, 7],
                "jednotka": ["kg", "kg"],
            })
    if flag_col not in df.columns:
        df[flag_col] = False
    df[flag_col] = True
    df.to_excel(path, index=False)

def break_mapping(path: Path):
    """Rozbije mapování (shuffle + lehká mutace názvů + vložení duplikátu)."""
    df = safe_read_xlsx(path)
    if df.empty:
        return
    name_col = None
    for c in df.columns:
        cl = c.lower()
        if cl in ("nazev", "polotovar_nazev"):
            name_col = c
            break
    df = df.sample(frac=1.0, random_state=int(time.time()) % 100000)
    if name_col:
        n = max(1, len(df)//3)
        df.loc[df.index[:n], name_col] = df.loc[df.index[:n], name_col].astype(str) + "_X"
    try:
        if len(df) > 0:
            dup = df.iloc[[0]].copy()
            df = pd.concat([dup, df], ignore_index=True)
    except Exception:
        pass
    df.to_excel(path, index=False)

def make_plan_empty_preserve_headers():
    """
    Přečte aktuální PLAN a zapíše ZPĚT stejné sloupce, ale NULA řádků.
    Pokud PLAN neexistuje, vyzve uživatele k jeho vytvoření standardním způsobem.
    """
    if not PLAN.exists():
        ensure_exists_via_user(PLAN, "PLAN neexistuje. V appce ho prosím vytvoř standardním postupem (otevři/vygeneruj plán).")
    df = safe_read_xlsx(PLAN)
    if df.shape[1] == 0:
        # Konzervativní neutrální hlavičky – jen když nešlo přečíst nic.
        # (Aplikace by však měla mít svůj skutečný formát plánu.)
        cols = ["datum", "ingredience_sk", "ingredience_rc", "nazev", "potreba", "jednotka",
                "polotovar_sk", "polotovar_rc", "polotovar_nazev"]
        empty = pd.DataFrame({c: [] for c in cols})
    else:
        empty = pd.DataFrame({c: [] for c in df.columns})
    empty.to_excel(PLAN, index=False)

# ---------------- Scénáře ----------------

def scenario_compute_plan(tmp, i, total):
    restore_files(tmp)
    print_header("compute_plan — rozbij plán a v appce klikni: 'Spočítat ingredience'", i, total)
    corrupt_xlsx(PLAN)
    wait_user("V appce klikni na **Spočítat ingredience** (nákup). Očekávaná hláška:\n"
              "    'Chyba ve výpočtu (nákup ingrediencí)'.")

def scenario_compute_semis(tmp, i, total):
    restore_files(tmp)
    print_header("compute_semis — rozbij plán a v appce klikni: 'Spočítat polotovary'", i, total)
    corrupt_xlsx(PLAN)
    wait_user("V appce klikni na **Spočítat polotovary**. Očekávaná hláška:\n"
              "    'Chyba ve výpočtu (plán polotovarů)'.")

def scenario_results_empty(tmp, i, total):
    restore_files(tmp)
    print_header("results_empty — 'V plánu nejsou žádné položky – není co zobrazit.'", i, total)
    make_plan_empty_preserve_headers()
    wait_user("Teď v appce klikni na **Spočítat ingredience** (nákup) NEBO otevři okno **Ingredience** tak,\n"
              "aby se načetl plán. Očekávaná hláška výše.")

def scenario_results_all_bought(tmp, i, total):
    restore_files(tmp)
    print_header("results_all_bought — 'Všechny ingredience jsou již označené jako koupené.'", i, total)
    ensure_exists_via_user(INGR, "Vytvoř 'vysledek.xlsx' klikem na **Spočítat ingredience** (nákup) v appce.")
    set_all_flag_true(INGR, "koupeno", create_min_rows=True)
    wait_user("V okně **Ingredience** proveď akci (filtr na nekoupené / klik na **Koupeno**).")

def scenario_results_all_bought_close(tmp, i, total):
    restore_files(tmp)
    print_header("results_all_bought_close — 'Všechny ingredience jsou již koupené. Okno bude nyní zavřeno.'", i, total)
    ensure_exists_via_user(INGR, "Vytvoř 'vysledek.xlsx' klikem na **Spočítat ingredience** (nákup) v appce.")
    set_all_flag_true(INGR, "koupeno", create_min_rows=True)
    wait_user("Otevři okno **Ingredience**.")

def scenario_results_index_map(tmp, i, total):
    restore_files(tmp)
    print_header("results_index_map — 'Chybné mapování položky v seznamu'", i, total)
    ensure_exists_via_user(INGR, "Vytvoř 'vysledek.xlsx' klikem na **Spočítat ingredience** (nákup) v appce.")
    wait_user("V appce otevři okno **Ingredience**, přepni **Detaily ↔ Agregace** a NECH HO OTEVŘENÉ.\n"
              "Až hotovo, stiskni Enter zde a já rozhodím XLSX…")
    break_mapping(INGR)
    wait_user("Teď v okně **Ingredience** klikni na položku/akci (např. **Koupeno**). Očekávaná hláška výše.")

def scenario_results_save(tmp, i, total):
    restore_files(tmp)
    print_header("results_save — 'Nepodařilo se uložit změny do souboru Excel…'", i, total)
    ensure_exists_via_user(INGR, "Vytvoř 'vysledek.xlsx' klikem na **Spočítat ingredience** (nákup) v appce.")
    print("Skript teď zamkne soubor 'vysledek.xlsx'.")
    with locked_file(INGR):
        wait_user("V okně **Ingredience** klikni na **Koupeno** / ulož. Očekávaná hláška výše.\n"
                  "(Po Enter soubor odemknu.)")
    print("Soubor odemčen.")

def scenario_semis_empty(tmp, i, total):
    restore_files(tmp)
    print_header("semis_empty — 'V plánu nejsou žádné položky – není co zobrazit.'", i, total)
    make_plan_empty_preserve_headers()
    wait_user("Teď v appce klikni na **Spočítat polotovary** NEBO otevři okno **Polotovary** tak,\n"
              "aby se načetl plán. Očekávaná hláška výše.")

def scenario_semis_all_done(tmp, i, total):
    restore_files(tmp)
    print_header("semis_all_done — 'Všechny polotovary jsou již označeny jako vyrobené.'", i, total)
    ensure_exists_via_user(SEMI, "Vytvoř 'polotovary.xlsx' klikem na **Spočítat polotovary** v appce.")
    set_all_flag_true(SEMI, "vyrobeno", create_min_rows=True)
    wait_user("V okně **Polotovary** proveď akci (filtr nevyrobené / klik na **Vyrobeno**).")

def scenario_semis_all_done_close(tmp, i, total):
    restore_files(tmp)
    print_header("semis_all_done_close — 'Všechny polotovary jsou již vyrobené. Okno bude nyní zavřeno.'", i, total)
    ensure_exists_via_user(SEMI, "Vytvoř 'polotovary.xlsx' klikem na **Spočítat polotovary** v appce.")
    set_all_flag_true(SEMI, "vyrobeno", create_min_rows=True)
    wait_user("Otevři okno **Polotovary**.")

def scenario_semis_index_map(tmp, i, total):
    restore_files(tmp)
    print_header("semis_index_map — 'Chyba mapování řádku'", i, total)
    ensure_exists_via_user(SEMI, "Vytvoř 'polotovary.xlsx' klikem na **Spočítat polotovary** v appce.")
    wait_user("V appce otevři okno **Polotovary** (režim **Detaily**) a NECH HO OTEVŘENÉ.\n"
              "Až hotovo, Enter zde a já rozhodím XLSX…")
    break_mapping(SEMI)
    wait_user("Teď v okně **Polotovary** klikni na akci (např. **Vyrobeno**). Očekávaná hláška výše.")

def scenario_semis_weekly_no_src(tmp, i, total):
    restore_files(tmp)
    print_header("semis_weekly_no_src — 'Pro tento týdenní součet nebyly nalezeny žádné zdrojové řádky'", i, total)
    ensure_exists_via_user(SEMI, "Vytvoř 'polotovary.xlsx' klikem na **Spočítat polotovary** v appce.")
    wait_user("V appce otevři **Polotovary** a přepni na **Součet na týden**. NECH okno otevřené.\n"
              "Až hotovo, Enter zde a já nastavím všechny zdroje na vyrobeno…")
    nuke_week_sources(SEMI, "vyrobeno")
    wait_user("V okně **Polotovary** klikni na označení týdenního součtu. Očekávaná hláška výše.")

def scenario_semis_save(tmp, i, total):
    restore_files(tmp)
    print_header("semis_save — 'Nepodařilo se uložit změny do souboru polotovarů…'", i, total)
    ensure_exists_via_user(SEMI, "Vytvoř 'polotovary.xlsx' klikem na **Spočítat polotovary** v appce.")
    print("Skript teď zamkne soubor 'polotovary.xlsx'.")
    with locked_file(SEMI):
        wait_user("V okně **Polotovary** klikni na **Vyrobeno** / ulož. Očekávaná hláška výše.\n"
                  "(Po Enter soubor odemknu.)")
    print("Soubor odemčen.")

def scenario_semis_save_weekly(tmp, i, total):
    restore_files(tmp)
    print_header("semis_save_weekly — 'Nepodařilo se uložit týdenní součet…'", i, total)
    ensure_exists_via_user(SEMI, "Vytvoř 'polotovary.xlsx' klikem na **Spočítat polotovary** v appce.")
    with locked_file(SEMI):
        wait_user("V okně **Polotovary** v režimu **Součet na týden** klikni na zápis součtu týdne. "
                  "Očekávaná hláška výše.\n(Po Enter soubor odemknu.)")
    print("Soubor odemčen.")

def scenario_results_window(tmp, i, total):
    restore_files(tmp)
    print_header("results_window — 'Chyba v okně s ingrediencemi' (obecná)", i, total)
    ensure_exists_via_user(INGR, "Vytvoř 'vysledek.xlsx' klikem na **Spočítat ingredience** (nákup) v appce.")
    df = safe_read_xlsx(INGR)
    if df.empty:
        df = pd.DataFrame({"nazev": ["A","B"], "koupeno": [False, False]})
    if "koupeno" in df.columns:
        df = df.drop(columns=["koupeno"])
    df.to_excel(INGR, index=False)
    wait_user("Otevři / refreshni okno **Ingredience**. Očekávaná hláška:\n"
              "    'Chyba v okně s ingrediencemi…'")

def scenario_semis_window(tmp, i, total):
    restore_files(tmp)
    print_header("semis_window — 'Chyba v okně polotovarů' (obecná)", i, total)
    ensure_exists_via_user(SEMI, "Vytvoř 'polotovary.xlsx' klikem na **Spočítat polotovary** v appce.")
    df = safe_read_xlsx(SEMI)
    if df.empty:
        df = pd.DataFrame({"polotovar_nazev": ["A","B"], "vyrobeno": [False, False]})
    if "vyrobeno" in df.columns:
        df = df.drop(columns=["vyrobeno"])
    df.to_excel(SEMI, index=False)
    wait_user("Otevři / refreshni okno **Polotovary**. Očekávaná hláška:\n"
              "    'Chyba v okně polotovarů…'")

def scenario_read_event_manual(tmp, i, total):
    restore_files(tmp)
    print_header("read_event — manuální (dev) scénář", i, total)
    wait_user("Nejspolehlivější je spustit váš UC12 test (simuluje výjimku read()).\n"
              "Alternativa: otevři libovolné okno a NÁSILNĚ ho ukonči přes správce úloh (ne křížkem).\n"
              "Pokud framework propaguje výjimku, uvidíš 'Chyba při čtení události okna'.")

def scenario_unhandled_exception_manual(tmp, i, total):
    restore_files(tmp)
    print_header("unhandled_exception — manuální (dev) scénář", i, total)
    wait_user("Do handleru akce dočasně vlož:\n"
              "    raise RuntimeError('TEST')\n"
              "Spusť akci (např. **Spočítat ingredience**), odklikni hlášku:\n"
              "    'Došlo k neočekávané chybě…'\n"
              "a úpravu hned vrať.")

# Seznam scénářů v pořadí
SCENARIOS: List[Tuple[str, Callable]] = [
    ("compute_plan", scenario_compute_plan),
    ("compute_semis", scenario_compute_semis),

    # POZOR: empty teď z PLÁNU
    ("results_empty", scenario_results_empty),
    ("results_all_bought", scenario_results_all_bought),
    ("results_all_bought_close", scenario_results_all_bought_close),
    ("results_index_map", scenario_results_index_map),
    ("results_save", scenario_results_save),

    ("semis_empty", scenario_semis_empty),
    ("semis_all_done", scenario_semis_all_done),
    ("semis_all_done_close", scenario_semis_all_done_close),
    ("semis_index_map", scenario_semis_index_map),
    ("semis_weekly_no_src", scenario_semis_weekly_no_src),
    ("semis_save", scenario_semis_save),
    ("semis_save_weekly", scenario_semis_save_weekly),

    ("results_window", scenario_results_window),
    ("semis_window", scenario_semis_window),

    ("read_event (manual)", scenario_read_event_manual),
    ("unhandled_exception (manual)", scenario_unhandled_exception_manual),
]

def main():
    total = len(SCENARIOS)

    for p in (PLAN, INGR, SEMI):
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    with tempfile.TemporaryDirectory() as tdir:
        tmp = Path(tdir)
        backup_files(tmp)

        print("="*96)
        print("Vyvolávač hlášek — START (podle nových hlášek)")
        print("="*96)
        print(f"Detekované soubory:\n  PLAN:  {PLAN}\n  VÝSLEDEK (INGR): {INGR}\n  POLOTOVARY:     {SEMI}")
        print("\nTipy:\n"
              "• Vždy přepni do appky, udělej akci dle instrukce, odklikni hlášku a tady stiskni Enter.\n"
              "• Mezi scénáři vracím XLSX do stavu ze začátku (z dočasné zálohy).\n")

        for i, (name, fn) in enumerate(SCENARIOS, start=1):
            try:
                fn(tmp, i, total)
            except KeyboardInterrupt:
                print("\nPřerušeno uživatelem.")
                break
            except Exception as e:
                print(f"[{i}/{total}] [{name}] Chyba vyvolávače: {e}")
                try:
                    restore_files(tmp)
                except Exception:
                    pass
                wait_user("Chceš pokračovat na další scénář?")

        print("\n" + "="*96)
        print("HOTOVO")
        print("="*96)
        print("Soubory vráceny do původního stavu (dočasné zálohy se po skončení odstraní).")

if __name__ == "__main__":
    main()
