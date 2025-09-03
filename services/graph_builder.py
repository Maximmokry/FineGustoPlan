# services/graph_builder.py
from __future__ import annotations
import pandas as pd
from typing import Dict, List
from services.graph_model import Graph, Node, Edge, NodeId, Demand
from services.compute_common import _prepare_recepty, _safe_int, _as_key_txt, find_col, clean_columns, to_date_col
from services.paths import OUTPUT_EXCEL, OUTPUT_SEMI_EXCEL

def build_nodes_from_recipes(recepty: pd.DataFrame) -> Dict[NodeId, Node]:
    r = _prepare_recepty(recepty)
    nodes: Dict[NodeId, Node] = {}

    def ensure_node(sk_raw, rc_raw, name: str = "", unit: str = "") -> Node:
        sk = _safe_int(sk_raw)
        rc = _safe_int(rc_raw)
        if sk is None or rc is None:
            raise KeyError("Nevalidní SK/RC v receptuře")
        nid = (sk, rc)

        # vytvoř, nebo chytrá aktualizace jména/jednotky
        if nid not in nodes:
            nodes[nid] = Node(id=nid, name=str(name or f"{sk}-{rc}"))
        else:
            # když je v grafu jen fallback, ale teď máme lepší jméno, doplň ho
            if name:
                fallback = f"{sk}-{rc}"
                if not nodes[nid].name or nodes[nid].name == fallback:
                    nodes[nid].name = str(name)

        # dosazení jednotky (jen když nebyla a nějaká je k dispozici)
        if unit and not nodes[nid].unit:
            nodes[nid].unit = str(unit)

        return nodes[nid]

    for _, row in r.iterrows():
        # RODIČ (finál 400 apod.) – teď s názvem z _P_NAME
        p = ensure_node(row["_P_SK"], row["_P_REG"], name=row.get("_P_NAME", ""))

        # DÍTĚ (polotovar/ingredience) – jméno už bylo, zachováno
        c = ensure_node(row["_C_SK"], row["_C_REG"], name=row.get("_C_NAME", ""), unit=row.get("_UNIT", ""))

        qty = float(row.get("_QTY", 0) or 0)
        p.edges.append(Edge(child=c.id, per_unit_qty=qty))
    return nodes


def expand_plan_to_demands(plan: pd.DataFrame, nodes: Dict[NodeId, Node]) -> List[Demand]:
    """Z plánu (400-rc, datum, množství) vytvoří demands na FINÁLy pro dané dny."""
    clean_columns(plan)
    COL_REG  = find_col(plan, ["reg.č", "regc", "reg", "reg c", "reg.c"]) or "reg.č"
    COL_QTY  = find_col(plan, ["mnozstvi", "množství", "qty"]) or "mnozstvi"
    COL_DATE = find_col(plan, ["datum", "date"]) or "datum"
    to_date_col(plan, COL_DATE)

    out: List[Demand] = []
    for _, row in plan.iterrows():
        rc = _safe_int(row.get(COL_REG))
        if rc is None:
            continue
        nid = (400, rc)
        if nid not in nodes:
            nodes[nid] = Node(id=nid, name=f"400-{rc}")  # fallback
        qty = float(row.get(COL_QTY, 0) or 0)
        dt  = row.get(COL_DATE, None)
        out.append(Demand(key=(dt, 400, rc), node=nid, qty=qty))
    return out

def attach_status_from_excels(g: Graph) -> None:
    """Stavy z Excelů → do uzlů: listy.bought, semis.produced (až bude i final.produced, doplníme)."""
    # koupeno z OUTPUT_EXCEL (ingredience.xlsx / vysledek.xlsx)
    try:
        df_ing = pd.read_excel(OUTPUT_EXCEL).fillna("")
        clean_columns(df_ing)
        to_date_col(df_ing, "datum")
        if "koupeno" in df_ing.columns:
            for _, r in df_ing.iterrows():
                sk = _safe_int(r.get("ingredience_sk"))
                rc = _safe_int(r.get("ingredience_rc"))
                if sk is None or rc is None:
                    continue
                nid = (sk, rc)
                if nid not in g.nodes:
                    g.nodes[nid] = Node(id=nid, name=f"{sk}-{rc}")  # allow loose list
                val = str(r.get("koupeno", "")).strip().lower()
                bought = (val in ("1","true","yes","ano"))
                if bought:
                    g.nodes[nid].bought = True
    except Exception:
        pass

    # vyrobeno z OUTPUT_SEMI_EXCEL (polotovary.xlsx, list Prehled)
    try:
        try:
            df_semi = pd.read_excel(OUTPUT_SEMI_EXCEL, sheet_name="Prehled").fillna("")
        except Exception:
            df_semi = pd.read_excel(OUTPUT_SEMI_EXCEL).fillna("")
        clean_columns(df_semi)
        to_date_col(df_semi, "datum")
        if "vyrobeno" in df_semi.columns:
            for _, r in df_semi.iterrows():
                sk = _safe_int(r.get("polotovar_sk"))
                rc = _safe_int(r.get("polotovar_rc"))
                if sk is None or rc is None:
                    continue
                nid = (sk, rc)
                if nid not in g.nodes:
                    g.nodes[nid] = Node(id=nid, name=f"{sk}-{rc}")
                val = str(r.get("vyrobeno", "")).strip().lower()
                produced = (val in ("1","true","yes","ano"))
                if produced:
                    g.nodes[nid].produced = True
    except Exception:
        pass
