# gui/main_window.py
from contextlib import suppress
import sys
import PySimpleGUIQt as sg

import main as core  # compute_plan(), compute_plan_semifinished()
from services.excel_service import ensure_output_excel
from gui.results_window import open_results
from gui.results_semis_window import open_semis_results
from services import error_messages as ERR

APP_TITLE   = "FineGusto"
WINDOW_SIZE = (760, 280)

def _setup_global_exception_hook():
    """
    Neodchycené výjimky:
      - detailní traceback do konzole,
      - popup jen pokud to prostředí dovolí (ne v testech/headless).
    """
    import traceback
    def _hook(exctype, value, tb):
        try:
            print("[FATAL] Neodchycená výjimka!", file=sys.stderr, flush=True)
            traceback.print_exception(exctype, value, tb, file=sys.stderr)
        except Exception:
            pass
        # Přátelská hláška – popup jen pokud smíme
        if ERR.should_show_popups():
            try:
                sg.popup_error(ERR.MSG.get("unhandled_exception", "Došlo k neočekávané chybě."))
            except Exception:
                pass
    sys.excepthook = _hook

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

def run():
    _setup_global_exception_hook()
    window = _build_main_window()

    try:
        while True:
            try:
                ev, vals = window.read()
            except Exception as e:
                # UC12: vždy něco pošli na stderr (sanitační kontrola)
                print("[ERROR] Chyba při čtení události okna", file=sys.stderr, flush=True)
                ERR.show_error(ERR.MSG["read_event"], e)
                break

            if ev in (sg.WINDOW_CLOSED, "-EXIT-", "Konec"):
                with suppress(Exception):
                    while True:
                        ev2, _ = window.read(timeout=0)
                        if ev2 in (None, sg.TIMEOUT_EVENT):
                            break
                with suppress(Exception):
                    q = getattr(sg, "_event_queue", None)
                    if isinstance(q, list):
                        q.clear()
                break

            if ev == "-RUN-ING-":
                try:
                    df = core.compute_plan()
                    ensure_output_excel(df)
                    open_results()
                except Exception as e:
                    ERR.show_error(ERR.MSG["compute_plan"], e)
                    continue

            if ev == "-RUN-SEMI-":
                try:
                    core.compute_plan_semifinished()
                    open_semis_results()
                except Exception as e:
                    ERR.show_error(ERR.MSG["compute_semis"], e)
                    continue

    finally:
        with suppress(Exception):
            window.close()

if __name__ == "__main__":
    run()
