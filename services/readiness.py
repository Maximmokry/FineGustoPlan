# services/readiness.py
from __future__ import annotations
from typing import Set, List
from services.graph_model import Graph, WorkKey, NodeId

def _all_descendant_leaves_bought(g: Graph, root: NodeId) -> bool:
    st: List[NodeId] = [root]
    seen = set()
    while st:
        nid = st.pop()
        if nid in seen:
            continue
        seen.add(nid)
        node = g.nodes.get(nid)
        if not node:
            continue
        if not node.edges:               # list
            if not node.bought:
                return False
        else:
            for e in node.edges:
                st.append(e.child)
    return True

def compute_ready_semis_under_finals(g: Graph) -> Set[WorkKey]:
    """
    (datum, 300, rc) je ready, pokud je daný 300 přímo dítětem FINÁLU 400
    v požadovaném dni a všechny listy v jeho podstromu jsou koupené.
    """
    ready: Set[WorkKey] = set()
    for d in g.demands:                 # demands máme jen pro FINAL 400
        if d.node[0] != 400:
            continue
        final = g.nodes.get(d.node)
        if not final:
            continue
        dt = d.key[0]
        for e in final.edges:
            child = g.nodes.get(e.child)
            if not child:
                continue
            if child.id[0] == 300:      # přímý potomek SK300
                if _all_descendant_leaves_bought(g, child.id):
                    ready.add((dt, 300, child.id[1]))
    return ready

def compute_ready_pack(g: Graph) -> Set[WorkKey]:
    """
    (datum, 400, rc) je ready-to-pack, pokud FINÁL je vyrobený a všechny jeho
    přímé listové děti (obaly/ingredience přímo pod 400) mají bought=True.
    """
    ready: Set[WorkKey] = set()
    for d in g.demands:
        if d.node[0] != 400:
            continue
        final = g.nodes.get(d.node)
        if not final or not final.produced:
            continue
        ok = True
        for e in final.edges:
            child = g.nodes.get(e.child)
            if child and not child.edges:     # přímý list pod 400
                if not child.bought:
                    ok = False; break
        if ok:
            ready.add(d.key)
    return ready
