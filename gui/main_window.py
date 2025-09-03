# gui/main_window.py
from contextlib import suppress
import sys
import PySimpleGUIQt as sg

from services import error_messages as ERR
from gui.results_window import open_results
from gui.results_semis_window import open_semis_results

# graf – načíst při startu a přidat RELOAD
from services import graph_store

APP_TITLE   = "FineGusto"
WINDOW_SIZE = (880, 280)

def _setup_global_exception_hook():
    import traceback
    def _hook(exctype, value, tb):
        try:
            print("[FATAL] Neodchycená výjimka!", file=sys.stderr, flush=True)
            traceback.print_exception(exctype, value, tb, file=sys.stderr)
        except Exception:
            pass
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
            sg.Button("Načíst znovu",      key="-RELOAD-", size=(18, 2)),
            sg.Button("Konec",             key="-EXIT-", size=(14, 2)),
        ]],
        element_justification='center', pad=(0, 0)
    )
    layout = [[header_col], [btn_row_col]]
    return sg.Window(APP_TITLE, layout, finalize=True, size=WINDOW_SIZE)

def run():
    _setup_global_exception_hook()

    # Graf se načte JEN při startu
    try:
        graph_store.init_on_startup()
    except Exception as e:
        ERR.show_error("Chyba při inicializaci grafu.", e)

    window = _build_main_window()

    try:
        while True:
            try:
                ev, vals = window.read()
            except Exception as e:
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

            if ev == "-RELOAD-":
                try:
                    graph_store.reload_all()
                    sg.popup("Data znovu načtena.")
                except Exception as e:
                    ERR.show_error("Chyba při znovunačtení dat.", e)
                continue

            if ev == "-RUN-ING-":
                try:
                    open_results()       # projekce hotové z init/reload
                except Exception as e:
                    ERR.show_error(ERR.MSG["compute_plan"], e)
                    continue

            if ev == "-RUN-SEMI-":
                try:
                    open_semis_results() # projekce hotové z init/reload
                except Exception as e:
                    ERR.show_error(ERR.MSG["compute_semis"], e)
                    continue

    finally:
        with suppress(Exception):
            window.close()

if __name__ == "__main__":
    run()
