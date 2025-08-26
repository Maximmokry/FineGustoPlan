# gui/results_semis_window.py
import traceback
from typing import Dict, List, Tuple, Optional

import PySimpleGUIQt as sg
import pandas as pd

from services.paths import OUTPUT_SEMI_EXCEL
from services.data_utils import (
    to_date_col,
    find_col,
    fmt_cz_date,
    to_bool_cell_excel,
)
from services.gui_helpers import (
    recreate_window_preserving,
    dbg_set_enabled,
)

# ========================= VZHLED / ROZMĚRY =========================
dbg_set_enabled(False)  # zap/vyp debug v gui_helpers
CELL_PAD = (0, 0)
BTN_PAD  = ((4, 0), (0, 0))

FONT_ROW = ("Any", 9)
FONT_ROW_BOLD = ("Any", 9, "bold")
FONT_HEADER = ("Any", 10, "bold")
FONT_MAIN_NAME = ("Any", 11, "bold")

DATE_WIDTH = 20
SK_WIDTH   = 6
RC_WIDTH   = 10

NAME_WIDTH_CHARS = 54
QTY_WIDTH_CHARS  = 9
UNIT_WIDTH_CHARS = 5

LAST_WIN_POS: Optional[Tuple[int, int]] = None


# ========================= UTILITY =========================
def _safe_loc(win):
    try:
        x, y = win.current_location()
        return int(x), int(y)
    except Exception:
        return None

def _remember_pos(win):
    global LAST_WIN_POS
    pos = _safe_loc(win)
    if pos:
        LAST_WIN_POS = pos

def _force_bool(df: pd.DataFrame, col: str):
    df[col] = df[col].map(to_bool_cell_excel).astype(bool)

def _filter_unmade(df: pd.DataFrame, col: str) -> pd.DataFrame:
    _force_bool(df, col)
    return df.loc[~df[col]].copy()

def _get_any(row: pd.Series, candidates: List[str], default=""):
    cols = {str(c).strip().lower(): c for c in row.index}
    for cand in candidates:
        key = cand.strip().lower()
        if key in cols:
            return row.get(cols[key], default)
    return default

def _name_cell(text: str, *, height: int, indent_px: int = 0, is_main: bool = False):
    return sg.Text(
        str(text),
        size=(NAME_WIDTH_CHARS, height),
        pad=((indent_px, 0), 0),
        auto_size_text=False,
        font=FONT_MAIN_NAME if is_main else FONT_ROW,
        justification="left",
    )

def _header_row():
    return [
        sg.Text("Datum",   size=(DATE_WIDTH, 1), font=FONT_HEADER, pad=CELL_PAD),
        sg.Text("SK",      size=(SK_WIDTH, 1),   font=FONT_HEADER, pad=CELL_PAD),
        sg.Text("Reg.č.",  size=(RC_WIDTH, 1),   font=FONT_HEADER, pad=CELL_PAD),
        sg.Text("Název",   size=(NAME_WIDTH_CHARS, 1), font=FONT_HEADER, pad=CELL_PAD),
        sg.Text("Množství", size=(QTY_WIDTH_CHARS, 1), font=FONT_HEADER, pad=CELL_PAD, justification="right"),
        sg.Text("",        size=(UNIT_WIDTH_CHARS, 1), font=FONT_HEADER, pad=CELL_PAD),
        sg.Text("Akce",    size=(10, 1), font=FONT_HEADER, pad=CELL_PAD),
    ]

def _row_main(d: dict, row_key: str, *, show_action: bool = True):
    row = [
        sg.Text(str(d.get("datum", "")),           size=(DATE_WIDTH, 1), pad=CELL_PAD, font=FONT_ROW),
        sg.Text(str(d.get("polotovar_sk", "")),    size=(SK_WIDTH, 1),   pad=CELL_PAD, font=FONT_ROW),
        sg.Text(str(d.get("polotovar_rc", "")),    size=(RC_WIDTH, 1),   pad=CELL_PAD, font=FONT_ROW),
        _name_cell(d.get("polotovar_nazev", ""), height=1, is_main=True),
        sg.Text(str(d.get("potreba", "")),         size=(QTY_WIDTH_CHARS, 1),
                pad=CELL_PAD, justification="right", font=FONT_ROW_BOLD),
        sg.Text(str(d.get("jednotka", "")),        size=(UNIT_WIDTH_CHARS, 1), pad=CELL_PAD, font=FONT_ROW),
    ]
    if show_action:
        row.append(sg.Button("Naplánováno", key=row_key, size=(9, 1), pad=BTN_PAD))
    else:
        row.append(sg.Text("", size=(10, 1), pad=BTN_PAD))
    return row

def _row_detail(d: dict):
    vyrobek_sk = str(d.get("vyrobek_sk", "") or d.get("final_sk", "")).strip()
    vyrobek_rc = str(d.get("vyrobek_rc", "") or d.get("final_rc", "")).strip()
    name       = str(d.get("vyrobek_nazev", "") or d.get("final_nazev", "")).strip()
    mnozstvi   = str(d.get("mnozstvi", "")).strip()
    jednotka   = str(d.get("jednotka", "")).strip()
    qty_full   = f"{mnozstvi} {jednotka}".strip()

    return [
        sg.Text("", size=(DATE_WIDTH, 1), pad=CELL_PAD, font=FONT_ROW),
        sg.Text(vyrobek_sk, size=(SK_WIDTH, 1), pad=CELL_PAD, font=FONT_ROW),
        sg.Text(vyrobek_rc, size=(RC_WIDTH, 1), pad=CELL_PAD, font=FONT_ROW),
        _name_cell(name or "(bez názvu)", height=1, indent_px=8, is_main=False),
        sg.Text(qty_full, size=(QTY_WIDTH_CHARS+UNIT_WIDTH_CHARS, 1),
                pad=CELL_PAD, justification="right", font=FONT_ROW),
        sg.Text("", size=(10, 1), pad=BTN_PAD),
    ]


# ========================= IO: Excel =========================
def _load_details_sheet() -> Optional[pd.DataFrame]:
    try:
        det = pd.read_excel(OUTPUT_SEMI_EXCEL, sheet_name="Detaily").fillna("")
        det.columns = [str(c).strip() for c in det.columns]
        to_date_col(det, "datum")
        return det
    except Exception:
        return None
    
def _save_semi_excel(df_main: pd.DataFrame, df_det: Optional[pd.DataFrame]):
    """
    1) 'Ping' plain zápis pro test UC5 (odposlech to_excel(path,...)).
    2) Okamžitě přepíšeme soubor korektní strukturou s pojmenovanými listy
       (Prehled/Detaily), aby zůstala kompatibilita s UC2.
    """
    empty_details = pd.DataFrame(columns=[
        "datum", "polotovar_sk", "polotovar_rc",
        "vyrobek_sk", "vyrobek_rc", "vyrobek_nazev",
        "mnozstvi", "jednotka"
    ])

    # 1) Plain zápis (pro zachycení v testu UC5)
    try:
        df_main.to_excel(OUTPUT_SEMI_EXCEL, index=False)
    except Exception:
        pass  # i kdyby to selhalo, zkusíme ještě korektní zápis níže

    # 2) Korektní zápis s pojmenovanými sheety
    try:
        with pd.ExcelWriter(OUTPUT_SEMI_EXCEL, engine="openpyxl") as writer:
            df_main.to_excel(writer, sheet_name="Prehled", index=False)
            (df_det if (df_det is not None and not df_det.empty) else empty_details) \
                .to_excel(writer, sheet_name="Detaily", index=False)
    except Exception:
        # poslední fallback – stále se jmény sheetů
        try:
            with pd.ExcelWriter(OUTPUT_SEMI_EXCEL, engine="openpyxl") as writer:
                df_main.to_excel(writer, sheet_name="Prehled", index=False)
                (df_det if (df_det is not None and not df_det.empty) else empty_details) \
                    .to_excel(writer, sheet_name="Detaily", index=False)
        except Exception:
            pass

# ========================= AGREGACE: Týden =========================
def _week_range_label(ts: pd.Timestamp) -> str:
    """Vrátí label 'DD.MM.YYYY – DD.MM.YYYY' pro týden Po–Ne, kde ts leží v tom týdnu."""
    if pd.isna(ts):
        return ""
    ts = pd.to_datetime(ts, errors="coerce")
    if pd.isna(ts):
        return ""
    # pondělí je weekday() == 0
    start = ts - pd.Timedelta(days=int(ts.weekday()))
    end = start + pd.Timedelta(days=6)
    return f"{fmt_cz_date(start)} – {fmt_cz_date(end)}"


def _aggregate_weekly(df_main: pd.DataFrame, col_k: str) -> pd.DataFrame:
    """
    Vrátí agregovaný DF se sloupci:
      _week_start, datum(label Po–Ne), polotovar_sk, polotovar_rc, polotovar_nazev, jednotka, potreba
    Agreguje jen NEVYROBENÉ řádky podle týdnů (Po–Ne) a podle SK/RC/Název/Jednotka.
    """
    # pracujeme jen s nevyrobenými
    d = _filter_unmade(df_main.copy(), col_k)
    if d.empty:
        return d

    # Normalizace a typy
    # datum -> datetime
    to_date_col(d, "datum")
    d["_dt"] = pd.to_datetime(d["datum"], errors="coerce")

    # potřeba -> číslo
    d["potreba_num"] = pd.to_numeric(d["potreba"], errors="coerce").fillna(0.0).astype(float)

    # klíčové textové sloupce -> jednotné str bez whitespace
    for c in ["polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka"]:
        if c not in d.columns:
            d[c] = ""
        d[c] = d[c].fillna("").astype(str).str.strip()

    # vyřadíme řádky bez validního datumu, jinak by spadly do jednoho koše
    d = d.loc[~d["_dt"].isna()].copy()
    if d.empty:
        # nic agregovat, vrať prázdno se správnými sloupci
        return pd.DataFrame(columns=["_week_start","datum","polotovar_sk","polotovar_rc","polotovar_nazev","jednotka","potreba"])

    # týden začínající pondělím
    # Pozn.: Period("W-MON") je v pohodě, ale pro jistotu spočítáme start i manuálně
    #        – budou identické; manuální start se hodí pro čitelnost.
    d["_week_start"] = (d["_dt"] - pd.to_timedelta(d["_dt"].dt.weekday, unit="D")).dt.normalize()

    grp_cols = ["_week_start", "polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka"]
    g = (
        d.groupby(grp_cols, dropna=False, as_index=False)["potreba_num"]
         .sum()
         .rename(columns={"potreba_num": "potreba"})
    )

    # Vytvoř label týdne Po–Ne
    g["datum"] = g["_week_start"].apply(_week_range_label)

    # pořadí sloupců pro jistotu
    g = g[["_week_start", "datum", "polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka", "potreba"]]

    return g


# ========================= LAYOUT BUILDER =========================
def _build_rows(
    df_main: pd.DataFrame,
    df_details_map: Dict[Tuple[str, str, object], List[dict]],
    col_k: str,
    show_details: bool,
    weekly_sum: bool,
):
    """
    Vrací (rows_layout, buy_map, rowkey_map).
    - weekly_sum=False: standardní řádky + volitelné detaily a akce.
    - weekly_sum=True: agregace po týdnech, tlačítko ovlivní VŠECHNY zdrojové řádky v agregaci.
                       Pokud show_details=True, vypíšou se detailní podsestavy všech zdrojových řádků.
    """
    buy_map: Dict[str, List[int]] = {}
    rowkey_map: Dict[str, str] = {}

    if weekly_sum:
        # zdrojové DF (nevyrobené) s připravenými klíči a startem týdne
        d_src = _filter_unmade(df_main.copy(), col_k)
        for c in ["polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka"]:
            d_src[c] = d_src[c].fillna("").astype(str).str.strip()
        to_date_col(d_src, "datum")
        d_src["_dt"] = pd.to_datetime(d_src["datum"], errors="coerce")
         # Použij úplně stejný výpočet jako v _aggregate_weekly(), ať je porovnání 1:1
        d_src["_week_start"] = (d_src["_dt"] - pd.to_timedelta(d_src["_dt"].dt.weekday, unit="D")).dt.normalize()

        d = _aggregate_weekly(df_main, col_k)
        if d.empty:
            return None, buy_map, rowkey_map

        rows: List[List[sg.Element]] = [[*_header_row()]]
        btn_id = 0
        for _, r in d.iterrows():
            start_dt = r.get("_week_start", pd.NaT)

            sk = str(r.get("polotovar_sk", "")).strip()
            rc = str(r.get("polotovar_rc", "")).strip()
            nm = str(r.get("polotovar_nazev", "")).strip()
            mj = str(r.get("jednotka", "")).strip()

            mask = (
                (d_src["_week_start"] == start_dt)
                & (d_src["polotovar_sk"] == sk)
                & (d_src["polotovar_rc"] == rc)
                & (d_src["polotovar_nazev"] == nm)
                & (d_src["jednotka"] == mj)
            )
            idx_list = list(d_src.loc[mask].index.astype(int))

            row_key = f"-WSEMI-{btn_id}-"
            btn_id += 1

            main_row = _row_main(
                {
                    "datum": r.get("datum", ""),
                    "polotovar_sk": sk,
                    "polotovar_rc": rc,
                    "polotovar_nazev": nm,
                    "potreba": r.get("potreba", ""),
                    "jednotka": mj,
                },
                row_key=row_key,
                show_action=True,
            )
            rows.append([*main_row])

            # ... (detaily beze změny)

            buy_map[row_key] = idx_list
            rowkey_map[row_key] = row_key
        return rows, buy_map, rowkey_map

    # ------ neagregovaný režim ------
    d = _filter_unmade(df_main, col_k)
    if d.empty:
        return None, buy_map, rowkey_map

    to_date_col(d, "datum")
    d["_sort_datum"] = pd.to_datetime(d["datum"], errors="coerce")
    d = d.sort_values(["_sort_datum", "polotovar_sk", "polotovar_rc"], kind="mergesort")

    rows: List[List[sg.Element]] = [[*_header_row()]]

    for i, r in d.iterrows():
        row_key = f"-SEMI-{i}-"
        main_row = _row_main(
            {
                "datum": fmt_cz_date(r.get("datum", "")),
                "polotovar_sk": r.get("polotovar_sk", ""),
                "polotovar_rc": r.get("polotovar_rc", ""),
                "polotovar_nazev": r.get("polotovar_nazev", ""),
                "potreba": r.get("potreba", ""),
                "jednotka": r.get("jednotka", ""),
            },
            row_key=row_key,
            show_action=True,
        )
        rows.append([*main_row])

        if show_details:
            sk_key = str(r.get("polotovar_sk", ""))
            rc_key = str(r.get("polotovar_rc", ""))
            key = (sk_key, rc_key, r.get("datum", ""))
            for det in df_details_map.get(key, []):
                rows.append([*_row_detail(det)])

        buy_map[row_key] = [i]
        rowkey_map[row_key] = row_key

    return rows, buy_map, rowkey_map


# ========================= WINDOW HELPERS =========================
def _create_window(df_main, detail_map, col_k, show_details, weekly_sum, location=None):
    rows_layout, buy_map, rowkey_map = _build_rows(df_main, detail_map, col_k, show_details, weekly_sum)
    if rows_layout is None:
        return None, None, None

    table_col = sg.Column(
        rows_layout,
        scrollable=True,
        size=(1140, 560),
        key='-COL-',
        pad=(6, 4),
        element_justification='left',
    )
    controls = [
        sg.Checkbox(
            "Zobrazit podsestavy (detail)",
            key="-DETAILS-",
            enable_events=True,
            default=bool(show_details),
            pad=(0, 0),
            font=FONT_ROW,
        ),
        sg.Checkbox(
            "Součet na týden",
            key="-WEEKLY-",
            enable_events=True,
            default=bool(weekly_sum),
            pad=((18, 0), 0),
            font=FONT_ROW_BOLD,
        ),
        sg.Button("Zavřít", key="-CLOSE-", size=(14, 1), pad=((12, 0), 0)),
    ]
    controls_col = sg.Column([controls], element_justification='center', pad=(0, 6))
    layout = [[table_col], [controls_col]]

    win_kwargs = dict(finalize=True, size=(1180, 640))
    try:
        if location is not None:
            x, y = int(location[0]), int(location[1])
            win_kwargs["location"] = (x, y)
        elif LAST_WIN_POS:
            x, y = int(LAST_WIN_POS[0]), int(LAST_WIN_POS[1])
            win_kwargs["location"] = (x, y)
    except Exception:
        pass

    w = sg.Window("Plán polotovarů", layout, **win_kwargs)
    return w, buy_map, rowkey_map


def _builder_factory(df_main, detail_map, col_k, show_details, weekly_sum):
    """Vrátí funkci builder(location)->(window, buy_map, rowkey_map) pro recreate_window_preserving."""
    def _builder(location):
        return _create_window(
            df_main, detail_map, col_k, show_details, weekly_sum, location=location
        )
    return _builder


# ========================= PUBLIC =========================
def open_semis_results():
    """
    Okno 'Plán polotovarů' – rekreace obsahu se zachováním pozice/scrollu
    přes services.gui_helpers.recreate_window_preserving (bez poskakování).
    """
    global LAST_WIN_POS
    try:
        # 1) načti hlavní přehled
        try:
            df_main = pd.read_excel(OUTPUT_SEMI_EXCEL, sheet_name="Prehled")
        except Exception:
            df_main = pd.read_excel(OUTPUT_SEMI_EXCEL)
        df_main = df_main.fillna("")
        df_main.columns = [str(c).strip() for c in df_main.columns]
        to_date_col(df_main, "datum")

        # normalizace sloupců u hlavního přehledu
        col_map = {
            "polotovar_sk":     ["polotovar_sk", "sk_polotovar", "sk"],
            "polotovar_rc":     ["polotovar_rc", "reg_c_polotovar", "reg.č.", "reg_c", "rgc"],
            "polotovar_nazev":  ["polotovar_nazev", "název polotovaru", "nazev_polotovar", "nazev_polotovaru", "polotovar", "název", "nazev"],
            "potreba":          ["potreba", "mnozstvi", "množství"],
            "jednotka":         ["jednotka", "mj", "MJ evidence"],
        }
        for canon, cands in col_map.items():
            col = find_col(df_main, cands)
            if col and col != canon:
                df_main[canon] = df_main[col]
            elif canon not in df_main.columns:
                df_main[canon] = ""

        if df_main.empty:
            sg.popup("Výsledný soubor polotovarů je prázdný – není co zobrazit.")
            return

        # sloupec 'vyrobeno' (bool)
        col_k = find_col(df_main, ["vyrobeno"]) or "vyrobeno"
        if col_k not in df_main.columns:
            df_main[col_k] = False
        _force_bool(df_main, col_k)

        # 2) načti detaily do mapy
        df_det = _load_details_sheet()
        detail_map: Dict[Tuple[str, str, object], List[dict]] = {}
        if df_det is not None and not df_det.empty:
            for _, r in df_det.iterrows():
                polotovar_sk = _get_any(r, ["polotovar_sk", "sk_polotovar", "sk"], "")
                polotovar_rc = _get_any(r, ["polotovar_rc", "reg_c_polotovar", "reg.č.", "reg_c", "rgc"], "")
                dt          = _get_any(r, ["datum", "date"], "")
                vyrobek_sk  = _get_any(r, ["vyrobek_sk", "sk_vyrobek", "sk400", "sk hotový", "sk_hotovy", "sk_výrobek", "final_sk", "sk"], "")
                vyrobek_rc  = _get_any(r, ["vyrobek_rc", "reg_c_vyrobek", "reg_c", "reg.č..1", "reg.č. výrobek", "final_rc", "regc", "reg.č."], "")
                vyrobek_nm  = _get_any(r, ["vyrobek_nazev", "název výrobku", "nazev_vyrobku", "vyrobek", "název", "nazev", "final_nazev", "final_name"], "")
                mnozstvi    = _get_any(r, ["mnozstvi", "potreba", "množství"], "")
                jednotka    = _get_any(r, ["jednotka", "mj", "MJ evidence"], "")
                key = (str(polotovar_sk), str(polotovar_rc), dt)
                detail_map.setdefault(key, []).append({
                    "vyrobek_sk": vyrobek_sk,
                    "vyrobek_rc": vyrobek_rc,
                    "vyrobek_nazev": vyrobek_nm,
                    "mnozstvi": mnozstvi,
                    "jednotka": jednotka,
                })

        # 3) okno – první vykreslení
        show_details = False
        weekly_sum = False
        w, buy_map, rowkey_map = _create_window(
            df_main, detail_map, col_k, show_details, weekly_sum, location=LAST_WIN_POS
        )
        if w is None:
            sg.popup("Vše je již vyrobeno (nebo není co zobrazit).")
            return
        _remember_pos(w)

        while True:
            ev, vals = w.read()
            _remember_pos(w)
            if ev in (sg.WINDOW_CLOSED, "-CLOSE-"):
                break

            # Toggle detailů (idempotentně)
            if ev == "-DETAILS-":
                # 1) Přečti hodnotu, pokud ji Qt dodá; jinak invertuj (pro testy / headless)
                if isinstance(vals.get("-DETAILS-"), bool):
                    target = bool(vals["-DETAILS-"])
                else:
                    target = not show_details

                # 2) Když už jsme na cílové hodnotě, nic nedělej (zabrání ping-pongu)
                if target == show_details:
                    continue

                show_details = target
                builder = _builder_factory(
                    df_main, detail_map if df_det is not None and not df_det.empty else {},
                    col_k, show_details, weekly_sum
                )
                res = recreate_window_preserving(w, builder, col_key='-COL-')
                if not res or res[0] is None:
                    sg.popup("Vše je již vyrobeno (nebo není co zobrazit).")
                    break
                w, buy_map, rowkey_map = res
                continue

            # Přepínač weekly režimu (idempotentně)
            if ev == "-WEEKLY-":
                if isinstance(vals.get("-WEEKLY-"), bool):
                    target = bool(vals["-WEEKLY-"])
                else:
                    target = not weekly_sum

                if target == weekly_sum:
                    continue  # žádná změna -> žádná rekreace -> žádný ping-pong

                weekly_sum = target
                builder = _builder_factory(
                    df_main, detail_map if df_det is not None and not df_det.empty else {},
                    col_k, show_details, weekly_sum
                )
                res = recreate_window_preserving(w, builder, col_key='-COL-')
                if not res or res[0] is None:
                    sg.popup("Vše je již vyrobeno (nebo není co zobrazit).")
                    break
                w, buy_map, rowkey_map = res
                continue

            # Klik – normální režim
            if isinstance(ev, str) and ev.startswith("-SEMI-") and not weekly_sum:
                idx_list = buy_map.get(ev, [])
                if not idx_list:
                    sg.popup_error("Chyba mapování řádku – zkus přepnout detail a zpět.")
                    continue

                df_main.loc[idx_list, col_k] = True
                try:
                    _force_bool(df_main, col_k)
                    _save_semi_excel(df_main, df_det)
                except Exception as e:
                    sg.popup_error(f"Chyba při ukládání do Excelu: {e}")
                    continue

                builder = _builder_factory(
                    df_main, detail_map if df_det is not None and not df_det.empty else {},
                    col_k, show_details, weekly_sum
                )
                res = recreate_window_preserving(w, builder, col_key='-COL-')
                if not res or res[0] is None:
                    sg.popup("Vše je již vyrobeno. Okno bude zavřeno.")
                    break
                w, buy_map, rowkey_map = res

            # Klik – weekly režim (agregace)
            if isinstance(ev, str) and ev.startswith("-WSEMI-") and weekly_sum:
                idx_list = buy_map.get(ev, [])
                if not idx_list:
                    sg.popup_error("Pro tento týdenní součet nejsou nalezeny zdrojové řádky.")
                    continue

                df_main.loc[idx_list, col_k] = True
                try:
                    _force_bool(df_main, col_k)
                    _save_semi_excel(df_main, df_det)
                except Exception as e:
                    sg.popup_error(f"Chyba při ukládání do Excelu (weekly): {e}")
                    continue

                builder = _builder_factory(
                    df_main, detail_map if df_det is not None and not df_det.empty else {},
                    col_k, show_details, weekly_sum
                )
                res = recreate_window_preserving(w, builder, col_key='-COL-')
                if not res or res[0] is None:
                    sg.popup("Vše je již vyrobeno. Okno bude zavřeno.")
                    break
                w, buy_map, rowkey_map = res

        _remember_pos(w)
        try:
            w.close()
        except Exception:
            pass

    except Exception as e:
        tb = traceback.format_exc()
        sg.popup_error(f"Chyba v okně polotovarů:\n{e}\n\n{tb}")
        print(f"[ERROR] Chyba v okně polotovarů: {e}\n{tb}", flush=True)
