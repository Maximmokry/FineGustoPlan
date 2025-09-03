# services/semis_projection.py
from __future__ import annotations
import pandas as pd
from typing import List, Tuple
from services.graph_model import Graph, NodeId


def _first3_int(x) -> int | None:
    try:
        s = str(x).strip()
        if len(s) < 3:
            return int(s)
        return int(s[:3])
    except Exception:
        return None


def _cat_from_node_or_nid(node, nid: NodeId) -> int | None:
    sk_attr = getattr(node, "sk", None)
    sk_val = sk_attr if sk_attr not in (None, "") else (nid[0] if isinstance(nid, (tuple, list)) and len(nid) > 0 else None)
    return _first3_int(sk_val)


def _collect_semis_300(g: Graph) -> List[dict]:
    """
    Projdi všechny požadavky (demands) na finálech a nasbírej
    požadovaná množství pro polotovary (SK 300).
    Do polotovarů NEzapočítáváme hotové výrobky (400) ani listy (nákup).
    """
    rows: List[dict] = []

    for d in g.demands:
        datum = d.key[0] if isinstance(d.key, (tuple, list)) and len(d.key) > 0 else None
        stack: List[Tuple[NodeId, float]] = [(d.node, d.qty)]

        while stack:
            nid, qty = stack.pop()
            node = g.nodes.get(nid)
            if not node:
                continue

            cat = _cat_from_node_or_nid(node, nid)

            # Polotovar (300) – EVIDUJ a NEJDI dál (cílová úroveň plánování)
            if cat == 300:
                sk, rc = nid
                rows.append({
                    "datum": datum,
                    "polotovar_sk": sk,  # <<< DOPLNĚNO: testy/Excel očekávají SK
                    "polotovar_rc": rc,
                    "polotovar_nazev": getattr(node, "name", "") or f"{sk}-{rc}",
                    "potreba": qty,
                    "jednotka": getattr(node, "unit", "") or "",
                    "vyrobeno": bool(getattr(node, "produced", False)),
                })
                continue

            # Leaf (nákup) do polotovarů nepatří
            has_edges = bool(getattr(node, "edges", None))
            if not has_edges:
                continue

            # Jinak rozpad dále (typicky 400 → 300/leaf)
            for e in getattr(node, "edges", []) or []:
                per_unit = float(e.per_unit_qty or 0.0)
                if per_unit == 0.0:
                    continue
                stack.append((e.child, qty * per_unit))

    return rows


def to_semis_dfs(g: Graph) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Vrací dva DataFrame:
      - df_pre: přehled polotovarů (SK 300) po datu
      - df_det: detaily (stejná granularita jako řádky přehledu)

    Sloupce (přehled):
      datum | polotovar_sk | polotovar_rc | polotovar_nazev | potreba | jednotka | vyrobeno
    Detaily v této projekci nezachycují původ (vyrobek_*), to dodají jiné části – tady držíme stejný základ.
    """
    rows = _collect_semis_300(g)

    base_cols = ["datum", "polotovar_sk", "polotovar_rc", "polotovar_nazev", "potreba", "jednotka", "vyrobeno"]

    if not rows:
        return pd.DataFrame(columns=base_cols), pd.DataFrame(columns=base_cols)

    df = pd.DataFrame(rows)

    # agregace přehledu – čistě potřeba, ostatní klíčová pole v groupby
    df["_pot"] = pd.to_numeric(df["potreba"], errors="coerce").fillna(0.0)
    df_pre = (
        df.groupby(
            ["datum", "polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka"],
            as_index=False
        )["_pot"].sum().rename(columns={"_pot": "potreba"})
    )
    # 'vyrobeno' není agregovatelné → vezmeme OR přes skupinu (někde může být True)
    df_vyr = (
        df.groupby(["datum", "polotovar_sk", "polotovar_rc"], as_index=False)["vyrobeno"]
          .max()
    )
    df_pre = df_pre.merge(df_vyr, on=["datum", "polotovar_sk", "polotovar_rc"], how="left")
    df_pre["vyrobeno"] = df_pre["vyrobeno"].fillna(False).astype(bool)

    # detaily – v této projekci stejné pole (bez vyrobek_*); necháváme řádek per (datum, rc)
    df_det = df[base_cols].copy()

    return df_pre[base_cols], df_det[base_cols]
