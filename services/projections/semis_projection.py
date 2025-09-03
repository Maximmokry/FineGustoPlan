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


def _fallback_name(name: str, sk, rc) -> str:
    n = (name or "").strip()
    return n if n else f"{sk}-{rc}"


def _collect_semis_300(g: Graph) -> List[dict]:
    """
    Projde všechny požadavky (FINÁLy 400) a nasbírá polotovary (SK 300).
    K polotovaru doplní i PŮVODNÍ VÝROBEK (400): vyrobek_sk/rc/nazev,
    aby je mělo UI v detailu k dispozici.
    """
    rows: List[dict] = []

    for d in g.demands:
        datum = d.key[0] if isinstance(d.key, (tuple, list)) and len(d.key) > 0 else None

        # identita a jméno kořenového výrobku (400)
        root_final_nid = d.node
        root_final = g.nodes.get(root_final_nid)
        if not root_final:
            continue
        try:
            vf_sk, vf_rc = root_final_nid  # (400, rc)
        except Exception:
            continue
        vf_name = _fallback_name(getattr(root_final, "name", ""), vf_sk, vf_rc)

        # rozpad
        stack: List[Tuple[NodeId, float]] = [(d.node, d.qty)]
        while stack:
            nid, qty = stack.pop()
            node = g.nodes.get(nid)
            if not node:
                continue

            cat = _cat_from_node_or_nid(node, nid)

            if cat == 300:
                sk, rc = nid
                rows.append({
                    "datum": datum,
                    "polotovar_sk": sk,
                    "polotovar_rc": rc,
                    "polotovar_nazev": _fallback_name(getattr(node, "name", ""), sk, rc),
                    "potreba": qty,
                    "jednotka": getattr(node, "unit", "") or "",
                    "vyrobeno": bool(getattr(node, "produced", False)),
                    # >>> pro detail hotového výrobku:
                    "vyrobek_sk": vf_sk,
                    "vyrobek_rc": vf_rc,
                    "vyrobek_nazev": vf_name,
                })
                continue

            # Leaf (nákup) – nepatří do polotovarů
            if not getattr(node, "edges", None):
                continue

            # jinak pokračuj v rozpadu
            for e in getattr(node, "edges", []) or []:
                per_unit = float(e.per_unit_qty or 0.0)
                if per_unit == 0.0:
                    continue
                stack.append((e.child, qty * per_unit))

    return rows


def to_semis_dfs(g: Graph) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Vrací:
      - df_pre (přehled SK 300 po datu):
        datum | polotovar_sk | polotovar_rc | polotovar_nazev | potreba | jednotka | vyrobeno
      - df_det (detaily s vazbou na VÝROBEK 400):
        datum | polotovar_sk | polotovar_rc | vyrobek_sk | vyrobek_rc | vyrobek_nazev | mnozstvi | jednotka
    """
    rows = _collect_semis_300(g)

    pre_cols = ["datum", "polotovar_sk", "polotovar_rc", "polotovar_nazev", "potreba", "jednotka", "vyrobeno"]
    det_cols = ["datum", "polotovar_sk", "polotovar_rc",
                "vyrobek_sk", "vyrobek_rc", "vyrobek_nazev",
                "mnozstvi", "jednotka"]

    if not rows:
        return pd.DataFrame(columns=pre_cols), pd.DataFrame(columns=det_cols)

    df = pd.DataFrame(rows)

    # ---------- Přehled ----------
    df["_pot"] = pd.to_numeric(df["potreba"], errors="coerce").fillna(0.0)
    df_pre = (
        df.groupby(
            ["datum", "polotovar_sk", "polotovar_rc", "polotovar_nazev", "jednotka"],
            as_index=False
        )["_pot"].sum().rename(columns={"_pot": "potreba"})
    )
    df_vyr = df.groupby(["datum", "polotovar_sk", "polotovar_rc"], as_index=False)["vyrobeno"].max()
    df_pre = df_pre.merge(df_vyr, on=["datum", "polotovar_sk", "polotovar_rc"], how="left")
    df_pre["vyrobeno"] = df_pre["vyrobeno"].fillna(False).astype(bool)
    df_pre = df_pre[pre_cols]

    # ---------- Detaily (pro UI podřádky – výrobek 400) ----------
    df_det = df.copy()
    df_det["mnozstvi"] = df_det["potreba"]
    for c in det_cols:
        if c not in df_det.columns:
            df_det[c] = ""
    df_det = df_det[det_cols]

    return df_pre, df_det
