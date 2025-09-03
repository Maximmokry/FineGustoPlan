# services/graph_model.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

NodeId  = Tuple[int, int]         # (SK, RC)
WorkKey = Tuple[object, int, int] # (datum, SK, RC) – klíč řádku v GUI (datum může být Timestamp)

@dataclass
class Edge:
    child: NodeId
    per_unit_qty: float

@dataclass
class Node:
    id: NodeId                    # (SK, RC)
    name: str
    unit: Optional[str] = None
    edges: List[Edge] = field(default_factory=list)
    # Stavy:
    bought: bool = False          # pro listové uzly (nakupují se)
    produced: bool = False        # pro nelistové (vyrábí se)

@dataclass
class Demand:
    key: WorkKey
    node: NodeId
    qty: float

@dataclass
class Graph:
    nodes: Dict[NodeId, Node] = field(default_factory=dict)
    demands: List[Demand] = field(default_factory=list)
