# gui/main_window.py
import sys
import traceback
import PySimpleGUIQt as sg

import main as core  # compute_plan(), compute_plan_semifinished()
from services.excel_service import ensure_output_excel
from gui.results_window import open_results
from gui.results_semis_window import open_semis_results

APP_TITLE   = "FineGusto"
WINDOW_SIZE = (760, 280)


# -------------------- Jednotné hlášení chyb: konzole + popup --------------------

def _report_error(user_msg: str, exc: Exception | None = None):
    """
    Vypíše chybu do terminálu (stderr) a zároveň zobrazí popup s trace.
    """
    tb = traceback.format_exc()
    try:
        if exc is not None:
            print(f"[ERROR] {user_msg}: {exc}\n{tb}", file=sys.stderr, flush=True)
        else:
            print(f"[ERROR] {user_msg}\n{tb}", file=sys.stderr, flush=True)
    except Exception:
        pass
    try:
        if exc is not None:
            sg.popup_error(f"{user_msg}:\n{exc}\n\n{tb}")
        else:
            sg.popup_error(f"{user_msg}\n\n{tb}")
    except Exception:
        # i kdyby popup selhal, máme log v terminálu
        pass


def _setup_global_exception_hook():
    """
    Zajistí, že i neodchycené výjimky skončí v terminálu a zároveň se ukážou v popupu.
    """
    def _hook(exctype, value, tb):
        try:
            print("[FATAL] Neodchycená výjimka!", file=sys.stderr, flush=True)
            traceback.print_exception(exctype, value, tb, file=sys.stderr)
        except Exception:
            pass
        try:
            msg = "".join(traceback.format_exception(exctype, value, tb))
            sg.popup_error("Neodchycená výjimka!", msg)
        except Exception:
            pass
    sys.excepthook = _hook


# -------------------- GUI layout --------------------

def _build_main_window():
    header_col = sg.Column(
        [[sg.Text("FineGusto plánovač", font=('Any', 16, 'bold'))]],
        element_justification='center', pad=(0, 10)
    )
    btn_row_col = sg.Column(
        [[
            sg.Button("nákup ingrediencí", key="-RUN-ING-", size=(22, 2)),
            sg.Button("plán polotovarů",   key="-RUN-SEMI-", size=(22, 2)),
            sg.Button("Konec",             key="-EXIT-", size=(14, 2)),
        ]],
        element_justification='center', pad=(0, 0)
    )
    layout = [[header_col], [btn_row_col]]
    return sg.Window(APP_TITLE, layout, finalize=True, size=WINDOW_SIZE)


# -------------------- Aplikační smyčka --------------------

def run():
    _setup_global_exception_hook()
    window = _build_main_window()

    try:
        while True:
            try:
                ev, vals = window.read()
            except Exception as e:
                _report_error("Chyba při čtení události okna", e)
                break

            if ev in (sg.WINDOW_CLOSED, "-EXIT-", "Konec"):
                break

            # --- nákup ingrediencí ---
            if ev == "-RUN-ING-":
                try:
                    df = core.compute_plan()   # výpočet ingrediencí
                    ensure_output_excel(df)    # zápis/merge do vysledek.xlsx (sloupec 'koupeno')
                    open_results()             # okno s nákupním seznamem
                except Exception as e:
                    _report_error("Chyba ve výpočtu (nákup ingrediencí)", e)
                    continue

            # --- plán polotovarů ---
            if ev == "-RUN-SEMI-":
                try:
                    core.compute_plan_semifinished()  # zapisuje do polotovary.xlsx (sloupec 'vyrobeno')
                    open_semis_results()              # okno s plánem polotovarů
                except Exception as e:
                    _report_error("Chyba ve výpočtu (plán polotovarů)", e)
                    continue

    finally:
        try:
            window.close()
        except Exception:
            pass


if __name__ == "__main__":
    run()
