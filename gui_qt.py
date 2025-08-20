# gui_qt_safe.py
import traceback
from pathlib import Path
import pandas as pd
import PySimpleGUIQt as sg
import main

OUTPUT_EXCEL = Path("vysledek.xlsx")

# pomocná funkce: najde skutečný název sloupce (case-insensitive, ořezané mezery)
def _find_col(df, candidates):
    cols = {c.strip().lower(): c for c in df.columns}
    for cand in candidates:
        key = cand.strip().lower()
        if key in cols:
            return cols[key]
    return None


def ensure_output_excel(data):
    """Zajistí, že v Excelu existuje sloupec 'koupeno' a že se při přepisování zachovají existující hodnoty."""
    df = None
    if isinstance(data, pd.DataFrame):
        df_new = data.copy()
    else:
        try:
            df_new = pd.DataFrame(data)
        except Exception:
            return

    # základní normalizace
    df_new = df_new.fillna("")
    df_new.columns = df_new.columns.str.strip()

    # najdeme, jestli new už obsahuje sloupec koupeno
    new_k = _find_col(df_new, ["koupeno"])

    # pokud výstupní soubor ještě neexistuje, chovejme se jako dříve
    if not OUTPUT_EXCEL.exists():
        if new_k is None:
            df_new["koupeno"] = False
        try:
            df_new.to_excel(OUTPUT_EXCEL, index=False)
        except Exception:
            pass
        return

    # pokud existuje starý soubor, načteme ho a pokusíme se zachovat koupeno
    try:
        df_old = pd.read_excel(OUTPUT_EXCEL).fillna("")
    except Exception:
        # pokud nelze načíst starý soubor, fallback: vytvořit nový jak dříve
        if new_k is None:
            df_new["koupeno"] = False
        try:
            df_new.to_excel(OUTPUT_EXCEL, index=False)
        except Exception:
            pass
        return

    df_old.columns = df_old.columns.str.strip()
    old_k = _find_col(df_old, ["koupeno"])
    if old_k is None:
        df_old["koupeno"] = False
        old_k = "koupeno"

    # klíčové sloupce pro porovnání = všechny sloupce new kromě 'koupeno'
    key_cols = [c for c in df_new.columns if c.strip().lower() != "koupeno"]

    # zajistíme, že df_old má všechny key_cols (jinak doplníme prázdnými řetězci)
    for c in key_cols:
        if c not in df_old.columns:
            df_old[c] = ""

    # připravíme subset starého souboru obsahující jen key_cols a staré 'koupeno'
    df_old_subset = df_old[key_cols + [old_k]].copy()

    # proveď levý merge - zachováme pořadí a řádky z df_new
    try:
        merged = pd.merge(df_new, df_old_subset, on=key_cols, how="left", suffixes=("","_old"))
    except Exception:
        # pokud merge selže (např. žádné společné sloupce), fallback k přímému přepsání
        if new_k is None:
            df_new["koupeno"] = False
        try:
            df_new.to_excel(OUTPUT_EXCEL, index=False)
        except Exception:
            pass
        return

    # rozhodnutí o výsledném 'koupeno':
    # - pokud existuje hodnota ze starého souboru (old_k), použijeme ji,
    # - jinak použijeme hodnotu z new (pokud existuje),
    # - jinak False.
    if old_k in merged.columns:
        merged['koupeno'] = merged[old_k]
    else:
        merged['koupeno'] = False

    if new_k is not None and new_k in merged.columns:
        # tam, kde je koupeno z old prázdné/NA, vezmeme hodnotu z new
        merged['koupeno'] = merged['koupeno'].where(merged['koupeno'].notna(), merged[new_k])

    # odstraníme pomocné sloupce old/new (kromě finálního 'koupeno')
    for c in [old_k, new_k]:
        if c and c in merged.columns and c != 'koupeno':
            try:
                merged = merged.drop(columns=[c])
            except Exception:
                pass

    # finální uložení
    try:
        merged.to_excel(OUTPUT_EXCEL, index=False)
    except Exception:
        # jako poslední možnost ulož new s koupeno=False pokud chybí
        if 'koupeno' not in df_new.columns:
            df_new["koupeno"] = False
        try:
            df_new.to_excel(OUTPUT_EXCEL, index=False)
        except Exception:
            pass

def to_rows(data):
    wanted = ["datum","ingredience_sk","ingredience_rc","nazev","potreba","jednotka","koupeno"]
    cols = [c for c in data.columns if c.strip().lower() in wanted]

    df = data[cols].astype(str)
    rows = df.values.tolist()
    ids = [f"{r[cols.index(c)] if c in cols else ''}" for r in rows for c in cols[:3]]
    return rows, ids

# GUI layout
layout = [
    [sg.Text("FineGusto plánovač")],
    [sg.Button("Spočítat", key="-RUN-"), sg.Button("Konec")],
    [sg.Text("Debug:"), sg.Text("", key="-DBG-", size=(80,1))],
]

window = sg.Window("FineGusto", layout, finalize=True)

def open_results():
    """Otevře okno s výsledky a umožní označit položky jako koupené bez přeskakování okna."""
    try:
        df_full = pd.read_excel(OUTPUT_EXCEL, dtype=str).fillna("")
        df_full.columns = df_full.columns.str.strip()

        col_k = _find_col(df_full, ["koupeno"])
        if col_k is None:
            # pokud tam není, vytvoříme sloupec prázdný
            df_full["koupeno"] = ""
            col_k = "koupeno"

        def build_rows_layout(df_full_local):
            # vrátí layout (seznam řádků) pro Column podle aktuálního df_full_local
            mask = ~df_full_local[col_k].astype(str).str.lower().isin(["true", "1", "yes", "y", "PRAVDA".lower()])
            df_to_show_local = df_full_local.loc[mask]

            if df_to_show_local.empty:
                return None, df_to_show_local

            # upravené záhlaví: odstraněno 'MJ', 'potreba' přejmenováno na 'Množství', odstraněn bool sloupec před tlačítkem
            header = ["Datum", "SK", "Reg.č.", "Název", "Množství","", "Akce"]
            # velikosti sloupců upraveny pro lepší zarovnání
            rows_layout_local = [[
                sg.Text(header[0], size=(12,1), font=('Any', 10, 'bold')),
                sg.Text(header[1], size=(6,1), font=('Any', 10, 'bold')),
                sg.Text(header[2], size=(10,1), font=('Any', 10, 'bold')),
                sg.Text(header[3], size=(36,1), font=('Any', 10, 'bold')),
                sg.Text(header[4], size=(12,1), font=('Any', 10, 'bold')),
                sg.Text(header[5], size=(8,1), font=('Any', 10, 'bold')),
                sg.Text(header[6], size=(8,1), font=('Any', 10, 'bold')),
            ]]

            for i, r in df_to_show_local.iterrows():
                # pozor: používáme 'potreba' hodnotu, ale v hlavičce ji zobrazíme jako 'Množství'
                row_elems = [
                    sg.Text(str(r.get("datum","")), size=(12,1)),
                    sg.Text(str(r.get("ingredience_sk","")), size=(6,1)),
                    sg.Text(str(r.get("ingredience_rc","")), size=(10,1)),
                    sg.Text(str(r.get("nazev","")), size=(36,1)),
                    sg.Text(str(r.get("potreba","")), size=(12,1)),
                    sg.Text(str(r.get("jednotka","")), size=(6,1)),
                    sg.Button("Koupeno", key=f"-BUY-{i}-", size=(8,1))
                ]
                rows_layout_local.append(row_elems)

            return rows_layout_local, df_to_show_local

        rows_layout, df_to_show = build_rows_layout(df_full)

        if rows_layout is None:
            sg.popup("Žádné položky k zobrazení (vše koupeno nebo prázdné).")
            return

        # Sloupec s klíčem, aby šel updateovat bez zavírání okna
        col = sg.Column(rows_layout, scrollable=True, size=(950,520), key='-COL-')
        lay = [[col],[sg.Button("Zavřít")]]
        w = sg.Window("Výsledek", lay, finalize=True)

        while True:
            ev, vals = w.read()
            window['-DBG-'].update(f"Ev: {repr(ev)}")
            if ev in (sg.WINDOW_CLOSED, "Zavřít"):
                break

            if isinstance(ev, str) and ev.startswith("-BUY-"):
                try:
                    idx = int(ev.split("-")[2])
                except Exception:
                    # pokud index není integer, ignorujeme
                    sg.popup_error("Chybný index položky.")
                    continue

                # označíme v df_full položku jako koupenou a uložíme do excelu
                df_full.at[idx, col_k] = True
                try:
                    df_full.to_excel(OUTPUT_EXCEL, index=False)
                except Exception as e:
                    tb = traceback.format_exc()
                    sg.popup_error(f"Chyba při ukládání do Excelu: {e}\n\n{tb}")
                    continue

                # překreslíme obsah Column bez zavírání okna
                new_rows_layout, new_df_to_show = build_rows_layout(df_full)
                if new_rows_layout is None:
                    sg.popup("Všechny položky jsou koupené. Okno bude zavřeno.")
                    break
                try:
                    # update layout - některé verze PySimpleGUI podporují update(layout=...)
                    w['-COL-'].update(layout=new_rows_layout)
                except Exception:
                    # pokud update layout neprojde, pokusíme se alternativně zavřít a znovu otevřít okno na stejné pozici
                    try:
                        # pokus o získání pozice (pokud dostupné)
                        try:
                            pos = w.current_location()
                        except Exception:
                            pos = None
                        w.close()
                        col = sg.Column(new_rows_layout, scrollable=True, size=(950,520), key='-COL-')
                        lay = [[col],[sg.Button("Zavřít")]]
                        if pos:
                            w = sg.Window("Výsledek", lay, finalize=True, location=pos)
                        else:
                            w = sg.Window("Výsledek", lay, finalize=True)
                    except Exception as e2:
                        tb = traceback.format_exc()
                        sg.popup_error(f"Chyba při obnově okna výsledků: {e2}\n\n{tb}")
                        break

        w.close()
    except Exception as e:
        tb = traceback.format_exc()
        sg.popup_error(f"Chyba v results window:\n{e}\n\n{tb}")

while True:
    try:
        ev, vals = window.read()
        window['-DBG-'].update(f"Ev: {repr(ev)}")
        if ev in (sg.WINDOW_CLOSED, "Konec"):
            break
        if ev == "-RUN-":
            try:
                data = main.main()
            except Exception as e:
                tb = traceback.format_exc()
                sg.popup_error(f"Chyba při spuštění main.main(): {e}\n\n{tb}")
                continue
            ensure_output_excel(data)
            open_results()
    except Exception as e:
        tb = traceback.format_exc()
        print("EXC in main loop:", tb)
        sg.popup_error(f"Chyba v hlavním okně:\n{e}\n\n{tb}")

window.close()
