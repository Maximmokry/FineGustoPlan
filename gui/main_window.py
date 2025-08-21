# gui/main_window.py
import traceback
import PySimpleGUIQt as sg
from gui.results_window import open_results
from services.excel_service import ensure_output_excel
from services.paths import OUTPUT_EXCEL
import main as core

def start_app():
    header_col = sg.Column(
        [[sg.Text("FineGusto plánovač", font=('Any', 16, 'bold'))]],
        element_justification='center', pad=(0, 10)
    )
    btn_row_col = sg.Column(
        [[sg.Button("Spočítat", key="-RUN-", size=(18,2)),
          sg.Button("Konec", size=(18,2))]],
        element_justification='center', pad=(0, 0)
    )
    layout = [[header_col], [btn_row_col]]
    window = sg.Window("FineGusto", layout, finalize=True, size=(720, 280))

    while True:
        try:
            ev, _ = window.read()
            if ev in (sg.WINDOW_CLOSED, "Konec"):
                break
            if ev == "-RUN-":
                try:
                    data = core.compute_plan()  # vrací DataFrame včetně 'koupeno'
                except Exception as e:
                    tb = traceback.format_exc()
                    sg.popup_error(f"Chyba při výpočtu: {e}\n\n{tb}")
                    continue
                ensure_output_excel(data)     # merge + zápis do OUTPUT_EXCEL
                open_results()                # zobraz okno s výsledky
        except Exception as e:
            tb = traceback.format_exc()
            sg.popup_error(f"Chyba v hlavním okně:\n{e}\n\n{tb}")

    window.close()
