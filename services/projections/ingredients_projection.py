# services/projections/ingredients_projection.py
from __future__ import annotations
import pandas as pd
from services.graph_model import Graph, NodeId


def _first3_int(x) -> int | None:
    """
    Vrátí první tři číslice jako int (např. '400...' -> 400),
    nebo None, pokud nelze převést.
    """
    try:
        s = str(x).strip()
        if len(s) < 3:
            return int(s)
        return int(s[:3])
    except Exception:
        return None


def _is_purchase_leaf(node, nid: NodeId) -> bool:
    """
    Listový uzel = nákupní položka (ingredience/obaly).
    Polotovary/finály (SK300/400) vyloučíme — SK bereme z node.sk,
    a když chybí, z nid[0].
    """
    # Není list → není nákup (má děti = vyrábí se)
    try:
        if node.edges and len(node.edges) > 0:
            return False
    except Exception:
        # Bezpečná default logika — když nevíme, raději NEpovažovat za nákupní
        return False

    # Leaf – zkontroluj kategorii SK
    sk_attr = getattr(node, "sk", None)
    sk_val = sk_attr if sk_attr not in (None, "") else (nid[0] if isinstance(nid, (list, tuple)) and len(nid) > 0 else None)
    cat = _first3_int(sk_val)
    if cat in (300, 400):
        return False

    return True


def to_ingredients_df(g: Graph) -> pd.DataFrame:
    """
    Z grafu udělej DF pro vysledek.xlsx:
    sloupce: datum, ingredience_sk, ingredience_rc, nazev, potreba, jednotka, koupeno

    - zahrnuje POUZE nákupní položky (listy grafu),
    - explicitně vylučuje SK300/400 (polotovary a hotové výrobky),
    - 'koupeno' nenutíme z grafu; nastavíme výchozí False a Excel merge případně zachová True.
    """
    rows = []

    # Projdi všechny finální požadavky a rozpadni je do listových (nákupních) uzlů
    for d in g.demands:  # demands na finálech
        stack: list[tuple[NodeId, float]] = [(d.node, d.qty)]
        while stack:
            nid, qty = stack.pop()
            node = g.nodes.get(nid)
            if not node:
                continue

            # Pokud má hrany, pokračujeme rozpadem
            if getattr(node, "edges", None):
                for e in node.edges:
                    per_unit = float(e.per_unit_qty or 0.0)
                    if per_unit == 0.0:
                        continue
                    stack.append((e.child, qty * per_unit))
                continue

            # Leaf – zvaž, zda je to skutečně nákupní položka (vyloučit 300/400)
            if not _is_purchase_leaf(node, nid):
                continue

            sk, rc = nid
            rows.append({
                "datum": d.key[0],  # datum z požadavku
                "ingredience_sk": sk,
                "ingredience_rc": rc,
                "nazev": getattr(node, "name", "") or "",
                "potreba": qty,
                "jednotka": getattr(node, "unit", "") or "",
                # 'koupeno' doplníme až po agregaci (default False)
            })

    # Když nic nevzniklo, vrať prázdnou tabulku se správnými sloupci
    if not rows:
        return pd.DataFrame(columns=[
            "datum", "ingredience_sk", "ingredience_rc", "nazev", "potreba", "jednotka", "koupeno"
        ])

    df = pd.DataFrame(rows)

    # Agregace přes klíče bez 'koupeno' (flag se udržuje přes merge v excel_service)
    df["_pot"] = pd.to_numeric(df["potreba"], errors="coerce").fillna(0.0)
    df = (
        df.groupby(
            ["datum", "ingredience_sk", "ingredience_rc", "nazev", "jednotka"],
            as_index=False
        )["_pot"].sum().rename(columns={"_pot": "potreba"})
    )

    # Výchozí hodnota koupeno=False (Excel merge případně zachová True z dřívějška)
    df["koupeno"] = False

    return df[["datum", "ingredience_sk", "ingredience_rc", "nazev", "potreba", "jednotka", "koupeno"]]
