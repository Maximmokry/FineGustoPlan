# -*- coding: utf-8 -*-
"""
Kapacitní pravidla pro plnění slotů v udírnách.

Podporuje:
- Základní kapacitu na slot pro každou udírnu (index 0..3 → Udírna 1..4)
- Volitelné upřesnění podle druhu masa (meat_type), které může kapacity
  pro konkrétní typ přepsat.

Pozn.: "kapacita" je interpretována jako maximální množství (např. kg) na JEDNO políčko.

Použití:
    rules = CapacityRules(
        base_per_smoker=[400, 300, 400, 400],
        per_type_overrides={
            # příklad – pokud nechcete, ponechte prázdné
            # "veprove": [400, 300, 400, 400],
            # "hovezi":  [300, 250, 300, 300],
        }
    )
    cap = rules.capacity_for(meat_type="veprove", smoker_idx=1)  # vrátí číslo (např. 300)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CapacityRules:
    base_per_smoker: List[float] = field(default_factory=lambda: [400.0, 300.0, 400.0, 400.0])
    per_type_overrides: Dict[str, List[float]] = field(default_factory=dict)

    def capacity_for(self, meat_type: Optional[str], smoker_idx: int) -> float:
        """
        - Když existuje override pro `meat_type` a index je mimo rozsah,
        vrací poslední hodnotu override pole.
        - Jinak vrací kapacitu ze základu (mimo rozsah → poslední hodnota základu).
        """
        if meat_type:
            key = str(meat_type).strip().lower()
            if key in self.per_type_overrides:
                arr = self.per_type_overrides[key]
                if 0 <= smoker_idx < len(arr):
                    return float(arr[smoker_idx])
                return float(arr[-1]) if arr else 0.0

        if 0 <= smoker_idx < len(self.base_per_smoker):
            return float(self.base_per_smoker[smoker_idx])
        return float(self.base_per_smoker[-1]) if self.base_per_smoker else 0.0
