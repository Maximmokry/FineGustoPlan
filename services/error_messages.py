# services/error_messages.py
import os
import sys
import traceback
import PySimpleGUIQt as sg

MSG = {
    # --- Globální / výpočty ---
    "compute_plan":        "Chyba ve výpočtu (nákup ingrediencí).\nZkontrolujte vstupy a zkuste akci spustit znovu.",
    "compute_semis":       "Chyba ve výpočtu (plán polotovarů).\nZkontrolujte vstupy a zkuste akci spustit znovu.",
    "read_event":          "Chyba při čtení události okna.\nZkuste okno zavřít a znovu otevřít.",
    "unhandled_exception": "Došlo k neočekávané chybě.\nAplikaci doporučujeme restartovat. Pokud problém přetrvává, obraťte se na podporu.",

    # --- Výsledky ingrediencí ---
    "results_empty":       "Výsledný soubor s ingrediencemi je prázdný – není co zobrazit.\nUjistěte se, že máte vyplněný plán i receptury.",
    "results_all_bought":  "Všechny ingredience jsou již označené jako koupené.",
    "results_all_bought_close": "Všechny ingredience jsou již koupené. Okno bude nyní zavřeno.",
    "results_index_map":   "Chybné mapování položky v seznamu.\nZkuste změnit režim zobrazení (agregace/detaily) a poté akci zopakovat.",
    "results_save":        "Nepodařilo se uložit změny do souboru Excel.\nMožná je soubor otevřený v jiné aplikaci. Zavřete ho a zkuste akci znovu.",

    # --- Výsledky polotovarů ---
    "semis_empty":         "Výsledný soubor polotovarů je prázdný – není co zobrazit.\nZkontrolujte plán a receptury, zda obsahují polotovary.",
    "semis_all_done":      "Všechny polotovary jsou již označeny jako vyrobené.",
    "semis_all_done_close": "Všechny polotovary jsou již vyrobené. Okno bude nyní zavřeno.",
    "semis_index_map":     "Chyba mapování řádku.\nZkuste přepnout zobrazení detailů a poté zpět.",
    "semis_weekly_no_src": "Pro tento týdenní součet nebyly nalezeny žádné zdrojové řádky.\nZkontrolujte plán a zkuste jiný týden.",
    "semis_save":          "Nepodařilo se uložit změny do souboru polotovarů.\nMožná je Excel soubor otevřený jinde. Zavřete ho a zkuste akci znovu.",
    "semis_save_weekly":   "Nepodařilo se uložit týdenní součet do souboru polotovarů.\nMožná je Excel soubor otevřený jinde. Zavřete ho a zkuste akci znovu.",

    # --- Ostatní ---
    "results_window":      "Chyba v okně s ingrediencemi.\nZkuste okno zavřít a akci spustit znovu.",
    "semis_window":        "Chyba v okně polotovarů.\nZkuste okno zavřít a akci spustit znovu.",
}

def _in_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))

def _no_qt_app() -> bool:
    try:
        return getattr(sg, "QtWidgets", None) is not None and sg.QtWidgets.QApplication.instance() is None
    except Exception:
        return True

def should_show_popups() -> bool:
    """
    True = smíme zobrazit popup (interaktivně).
    False = test/headless – zobrazit jen log do stderr.
    Lze vynutit env proměnnou FG_SUPPRESS_POPUPS=1.
    """
    if os.environ.get("FG_SUPPRESS_POPUPS") == "1":
        return False
    if _in_pytest():
        return False
    if _no_qt_app():
        return False
    return True

def show_error(user_msg: str, exc: Exception | None = None):
    """
    Zaloguje chybu s tracebackem do konzole a (pokud je to vhodné) zobrazí uživateli popup.
    V test/headless režimu se popup NEzobrazuje, aby neblohoval běh testů.
    """
    tb = traceback.format_exc()

    # Log pro vývojáře (stderr)
    try:
        if exc is not None:
            print(f"[ERROR] {user_msg}: {exc}\n{tb}", file=sys.stderr, flush=True)
        else:
            print(f"[ERROR] {user_msg}\n{tb}", file=sys.stderr, flush=True)
    except Exception:
        pass

    # Popup pro uživatele – jen pokud smíme
    if should_show_popups():
        try:
            sg.popup_error(user_msg)
        except Exception:
            pass
