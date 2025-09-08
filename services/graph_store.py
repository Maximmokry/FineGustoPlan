# services/graph_store.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, Tuple, Set, Iterable
import pandas as pd
from datetime import date, datetime
from services import error_messages as ERR
from services.paths import OUTPUT_EXCEL, OUTPUT_SEMI_EXCEL
from services.excel_service import ensure_output_excel
from services.semi_excel_service import ensure_output_semis_excel


# ============== JEDINÝ ZDROJ PRAVDY: GRAF ==============
from services.graph_model import Graph, NodeId, WorkKey

_G: Optional[Graph] = None

# Projekční cache (lazy, invaliduje se po změnách)
_DIRTY_ING = True
_DIRTY_SEMIS = True
_ING_DF: Optional[pd.DataFrame] = None               # ingredience (DataFrame)
_SEMIS_PRE: Optional[pd.DataFrame] = None            # polotovary – přehled
_SEMIS_DET: Optional[pd.DataFrame] = None            # polotovary – detaily

# Stavové per-řádek (datum, SK, RC) – to je to, co uživatel „odklikává“ v GUI:
#  - ingredience: koupeno
#  - polotovary: vyrobeno (naplánováno)
_BOUGHT_KEYS: Set[Tuple[object, int, int]] = set()   # (datum, ingredience_sk, ingredience_rc)
_PRODUCED_SEMIS_KEYS: Set[Tuple[object, int, int]] = set()  # (datum, polotovar_sk=300, polotovar_rc)


# ----------------------------- Pomocné -------------------------------------------------
def _to_date(v) -> object:
    try:
        if isinstance(v, (date, datetime)):
            return v.date() if isinstance(v, datetime) else v
        dt = pd.to_datetime(v, errors="coerce")
        return dt.date() if not pd.isna(dt) else v
    except Exception:
        return v

def _to_int(v) -> Optional[int]:
    try:
        s = str(v).strip()
        s = s.replace(",", ".")
        f = float(s)
        if pd.isna(f):
            return None
        return int(f)
    except Exception:
        return None

def _key_triplet(dt, sk, rc) -> Tuple[object, int, int]:
    d = _to_date(dt)
    i_sk = _to_int(sk)
    i_rc = _to_int(rc)
    return (d, (i_sk if i_sk is not None else int(sk)), (i_rc if i_rc is not None else int(rc)))


# ----------------------------- Build grafu a projekce -----------------------------------
def _build_graph() -> Graph:
    from services.data_loader import nacti_data
    from services.graph_builder import build_nodes_from_recipes, expand_plan_to_demands, attach_status_from_excels
    recepty, plan = nacti_data()
    nodes = build_nodes_from_recipes(recepty)
    g = Graph(nodes=nodes, demands=expand_plan_to_demands(plan, nodes))
    # přenést stavy z dřívějších Excelů do uzlů (globální list bought / semi produced)
    try:
        attach_status_from_excels(g)
    except Exception:
        pass
    return g

def _recompute_ingredients_df(g: Graph) -> pd.DataFrame:
    # projekce ingrediencí ze stromu
    from services.projections.ingredients_projection import to_ingredients_df
    df = to_ingredients_df(g)
    # doplň per-řádek koupeno dle _BOUGHT_KEYS (GUI filtruje podle tohoto sloupce)
    if not df.empty:
        df["koupeno"] = df.apply(
            lambda r: (_key_triplet(r.get("datum"), r.get("ingredience_sk"), r.get("ingredience_rc")) in _BOUGHT_KEYS),
            axis=1
        )
    else:
        df["koupeno"] = []
    return df

def _recompute_semis_dfs(g: Graph) -> Tuple[pd.DataFrame, pd.DataFrame]:
    # projekce polotovarů ze stromu
    from services.projections.semis_projection import to_semis_dfs
    pre, det = to_semis_dfs(g)
    # přepiš 'vyrobeno' podle per-řádkových klíčů (datum, 300, rc)
    if not pre.empty:
        pre = pre.copy()
        pre["vyrobeno"] = pre.apply(
            lambda r: (_key_triplet(r.get("datum"), r.get("polotovar_sk"), r.get("polotovar_rc")) in _PRODUCED_SEMIS_KEYS),
            axis=1
        )
    if not det.empty:
        # detaily sloupec 'vyrobeno' nepotřebují; necháme bez úprav
        pass
    return pre, det


# ----------------------------- API: Inicializace / Reload -------------------------------
def init_on_startup():
    """
    Start:
      1) postav graf,
      2) spočítej projekce,
      3) načti staré True stavy z Excelů do _BOUGHT_KEYS / _PRODUCED_SEMIS_KEYS,
      4) sestav projekce (s doplněnými True) a ulož je do Excelů,
      5) nastav cache (lazy – držíme DF v paměti, ale víme je rychle přepočítat).
    """
    global _G, _DIRTY_ING, _DIRTY_SEMIS, _ING_DF, _SEMIS_PRE, _SEMIS_DET
    global _BOUGHT_KEYS, _PRODUCED_SEMIS_KEYS

    try:
        _G = _build_graph()
    except Exception as e:
        ERR.show_error(ERR.MSG.get("graph_init", "Chyba při sestavení grafu."), e)
        _G = Graph()

    # 3) načti staré True z Excelů do per-řádkových množin
    _BOUGHT_KEYS = set()
    try:
        ing_old = pd.read_excel(OUTPUT_EXCEL).fillna("")
        if not ing_old.empty and "koupeno" in ing_old.columns:
            from services.data_utils import to_date_col
            to_date_col(ing_old, "datum")
            for _, r in ing_old.iterrows():
                if str(r.get("koupeno", "")).strip().lower() in ("1","true","yes","ano","✓","x"):
                    k = _key_triplet(r.get("datum"), r.get("ingredience_sk"), r.get("ingredience_rc"))
                    _BOUGHT_KEYS.add(k)
    except Exception:
        pass

    _PRODUCED_SEMIS_KEYS = set()
    try:
        semi_old = None
        try:
            semi_old = pd.read_excel(OUTPUT_SEMI_EXCEL, sheet_name="Prehled").fillna("")
        except Exception:
            semi_old = pd.read_excel(OUTPUT_SEMI_EXCEL).fillna("")
        if semi_old is not None and not semi_old.empty and "vyrobeno" in semi_old.columns:
            from services.data_utils import to_date_col
            to_date_col(semi_old, "datum")
            for _, r in semi_old.iterrows():
                if str(r.get("vyrobeno", "")).strip().lower() in ("1","true","yes","ano","✓","x"):
                    k = _key_triplet(r.get("datum"), r.get("polotovar_sk"), r.get("polotovar_rc"))
                    _PRODUCED_SEMIS_KEYS.add(k)
    except Exception:
        pass

    # 4) spočítej projekce, doplň stavy a zapiš do Excelů
    try:
        _ING_DF = _recompute_ingredients_df(_G)
        ensure_output_excel(_ING_DF)
    except Exception as e:
        ERR.show_error(ERR.MSG.get("results_save", "Chyba při ukládání ingrediencí."), e)

    try:
        _SEMIS_PRE, _SEMIS_DET = _recompute_semis_dfs(_G)
        ensure_output_semis_excel(_SEMIS_PRE, _SEMIS_DET)
    except Exception as e:
        ERR.show_error(ERR.MSG.get("semis_save", "Chyba při ukládání polotovarů."), e)

    # 5) cache připravena
    _DIRTY_ING = False
    _DIRTY_SEMIS = False


def reload_all():
    """Znovu načti data, přepočítej projekce, proveď merge se starými stavy a obnov cache."""
    return init_on_startup()


# ----------------------------- API: Gettery (GUI je jen čte) ---------------------------
def get_graph() -> Graph:
    return _G if _G is not None else Graph()

def get_ingredients_df() -> pd.DataFrame:
    global _DIRTY_ING, _ING_DF
    if _ING_DF is None or _DIRTY_ING:
        _ING_DF = _recompute_ingredients_df(get_graph())
        _DIRTY_ING = False
    return _ING_DF.copy()

def get_semis_dfs() -> Tuple[pd.DataFrame, pd.DataFrame]:
    global _DIRTY_SEMIS, _SEMIS_PRE, _SEMIS_DET
    if _SEMIS_PRE is None or _SEMIS_DET is None or _DIRTY_SEMIS:
        _SEMIS_PRE, _SEMIS_DET = _recompute_semis_dfs(get_graph())
        _DIRTY_SEMIS = False
    return _SEMIS_PRE.copy(), _SEMIS_DET.copy()


# ----------------------------- API: Mutátory (GUI je volá při kliknutí) ----------------
def set_ingredient_bought(dt, sk, rc, *, bought: bool = True) -> None:
    """Označ/odznač danou ingredienci pro konkrétní datum jako koupenou + aktualizuj runtime graf."""
    global _DIRTY_ING, _BOUGHT_KEYS, _G
    k = _key_triplet(dt, sk, rc)

    if bought:
        _BOUGHT_KEYS.add(k)
    else:
        _BOUGHT_KEYS.discard(k)

    # --- důležité: přepiš stav v živém grafu, aby readiness fungovala hned ---
    try:
        i_sk = _to_int(sk)
        i_rc = _to_int(rc)
        nid = (i_sk if i_sk is not None else int(sk),
               i_rc if i_rc is not None else int(rc))
        g = get_graph()
        node = g.nodes.get(nid)
        if node is not None:
            node.bought = bool(bought)
    except Exception:
        # nechceme shodit GUI kvůli drobné nekonzistenci; persist i tak proběhne
        pass

    # invalidace projekce ingrediencí + persist do Excelu
    _DIRTY_ING = True
    df = get_ingredients_df()
    try:
        ensure_output_excel(df)  # merge udrží True i při drobných změnách
    except Exception as e:
        ERR.show_error(ERR.MSG.get("results_save", "Chyba při ukládání ingrediencí."), e)

def set_ingredient_bought(dt, sk, rc, *, bought: bool = True) -> None:
    """Označ/odznač danou ingredienci pro konkrétní datum jako koupenou + okamžitě uprav runtime graf."""
    global _DIRTY_ING, _BOUGHT_KEYS

    # 1) ulož klíč do množiny koupených (pro persist a tabulky)
    k = _key_triplet(dt, sk, rc)
    if bought:
        _BOUGHT_KEYS.add(k)
    else:
        _BOUGHT_KEYS.discard(k)

    # 2) okamžitě přepiš stav v běžícím grafu (readiness v polotovarech čte node.bought)
    try:
        g = get_graph()
        i_sk = _to_int(sk)
        i_rc = _to_int(rc)
        nid = (
            i_sk if i_sk is not None else int(sk),
            i_rc if i_rc is not None else int(rc),
        )
        node = g.nodes.get(nid)
        if node is not None:
            node.bought = bool(bought)
    except Exception:
        # nechceme kvůli nekonzistenci shodit GUI; persist proběhne i tak
        pass

    # 3) invalidace a persist ingrediencí do Excelu
    _DIRTY_ING = True
    df = get_ingredients_df()
    try:
        ensure_output_excel(df)
    except Exception as e:
        ERR.show_error(ERR.MSG.get("results_save", "Chyba při ukládání ingrediencí."), e)


def set_ingredients_bought_many(keys: Iterable[Tuple[object, int, int]], *, bought: bool = True) -> None:
    """Hromadně (např. více řádků): keys = (datum, sk, rc). Aktualizuje i runtime graf a persistne najednou."""
    global _DIRTY_ING, _BOUGHT_KEYS

    # 1) uprav množinu koupených + runtime graf
    g = get_graph()
    for dt, sk, rc in keys:
        k = _key_triplet(dt, sk, rc)
        if bought:
            _BOUGHT_KEYS.add(k)
        else:
            _BOUGHT_KEYS.discard(k)

        try:
            i_sk = _to_int(sk)
            i_rc = _to_int(rc)
            nid = (
                i_sk if i_sk is not None else int(sk),
                i_rc if i_rc is not None else int(rc),
            )
            node = g.nodes.get(nid)
            if node is not None:
                node.bought = bool(bought)
        except Exception:
            # pokračuj, ať hromadná operace doběhne
            pass

    # 2) invalidace + jeden persist pro výkon
    _DIRTY_ING = True
    df = get_ingredients_df()
    try:
        ensure_output_excel(df)
    except Exception as e:
        ERR.show_error(ERR.MSG.get("results_save", "Chyba při ukládání ingrediencí."), e)

def set_semi_produced(dt, sk, rc, *, produced: bool = True) -> None:
    """Označ/odznač daný polotovar pro konkrétní datum jako vyrobený (naplánováno)."""
    global _DIRTY_SEMIS
    k = _key_triplet(dt, sk, rc)
    if produced:
        _PRODUCED_SEMIS_KEYS.add(k)
    else:
        _PRODUCED_SEMIS_KEYS.discard(k)

    _DIRTY_SEMIS = True
    pre, det = get_semis_dfs()
    try:
        ensure_output_semis_excel(pre, det)
    except Exception as e:
        ERR.show_error(ERR.MSG.get("semis_save", "Chyba při ukládání polotovarů."), e)

def set_semis_produced_many(keys: Iterable[Tuple[object, int, int]], *, produced: bool = True) -> None:
    """Hromadně (agregace týdne) – keys = (datum, sk, rc)."""
    for dt, sk, rc in keys:
        set_semi_produced(dt, sk, rc, produced=produced)
