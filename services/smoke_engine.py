# services/smoke_engine.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Any

CellKey = Tuple[int, int, int]
Phase   = str
ConfirmCallback  = Callable[[str], bool]

from services.smoke_rules import (
    HasItemAttrs, RawMassExtractor,
    RuleViolation, CheckOutcome,
    CapacityProvider, TableCapacity,
    Constraint,
    BiltongRule, SingleProductPerSlotRule, CapacityByRawRule,
    AutoMergePolicy,
    default_raw_mass_extractor, is_biltong_name,
)

# ---------- Výsledek validace (pro interaktivní přesuny) ----------
@dataclass
class ValidationResult:
    ok: bool
    split_qty: Optional[float] = None
    remainder_qty: Optional[float] = None
    violation: Optional[RuleViolation] = None
    ask_message: Optional[str] = None

# ---------- Engine ----------
@dataclass
class RuleEngine:
    constraints: List[Constraint]
    capacity: CapacityProvider
    raw_mass_of: RawMassExtractor = default_raw_mass_extractor
    merge_policy: Optional[AutoMergePolicy] = field(default_factory=AutoMergePolicy)
    reserved_smoker_index: int = 4

    def _evaluate_slot(self, item: HasItemAttrs, smoker_idx: int, slot_items: List[HasItemAttrs], phase: Phase) -> ValidationResult:
        for c in self.constraints:
            out = c.check(item, slot_items, smoker_idx, phase)
            if out.kind == "BLOCK":
                return ValidationResult(ok=False, violation=out.violation)
            if out.kind == "ASK":
                if phase == "prefill":
                    return ValidationResult(ok=False, violation=out.violation, ask_message=out.ask_message)
            if out.kind == "SPLIT":
                return ValidationResult(ok=False, split_qty=out.split_qty, remainder_qty=out.remainder_qty, violation=out.violation)
        return ValidationResult(ok=True)

    def validate_slot(self, item: HasItemAttrs, smoker_idx: int, slot_items: List[HasItemAttrs],
                      *, confirm_cb: Optional[ConfirmCallback], phase: Phase) -> ValidationResult:
        res = self._evaluate_slot(item, smoker_idx, slot_items, phase)
        if res.ok:
            return res
        if res.ask_message and confirm_cb and confirm_cb(res.ask_message):
            return ValidationResult(ok=True)
        return res

    # ---------- utils ----------
    def _make_item(self, base: HasItemAttrs, *, qty: float, raw_qty: Optional[float]=None) -> HasItemAttrs:
        """Vytvoří NOVOU instanci položky (žádné sdílení s base) a nastaví i alias 'mnozstvi'."""
        cls = type(base)
        try:
            new = cls(
                rc=getattr(base, "rc", ""),
                sk=getattr(base, "sk", ""),
                name=getattr(base, "name", ""),
                qty=float(qty),
                unit=getattr(base, "unit", ""),
                source_id=getattr(base, "source_id", ""),
            )
        except Exception:
            @dataclass
            class _Simple:
                rc: str; sk: str; name: str; qty: float; unit: str; source_id: str
            new = _Simple(
                getattr(base,"rc",""), getattr(base,"sk",""), getattr(base,"name",""),
                float(qty), getattr(base,"unit",""), getattr(base,"source_id","")
            )

        # alias pro UI (pokud používá 'mnozstvi')
        try:
            setattr(new, "mnozstvi", float(qty))
        except Exception:
            pass

        if raw_qty is not None:
            try:
                setattr(new, "raw_qty", float(raw_qty))
            except Exception:
                pass

        for attr in ("meat_type","raw_children"):
            if hasattr(base, attr):
                try:
                    setattr(new, attr, getattr(base, attr))
                except Exception:
                    pass
        return new

    def _first_empty_row(self, grid: Dict[CellKey, List[HasItemAttrs]], d: int, s: int, rows: int) -> Optional[int]:
        for r in range(1, rows+1):
            if not grid[(d,s,r)]:
                return r
        return None

    # ---------- PREFILL ----------
    def prefill(self, items: List[HasItemAttrs], days: int, smokers: int, rows: int,
                *, confirm_cb: Optional[ConfirmCallback]=None) -> Dict[CellKey, List[HasItemAttrs]]:

        grid: Dict[CellKey, List[HasItemAttrs]] = {(d,s,r): [] for d in range(days) for s in range(1,smokers+1) for r in range(1,rows+1)}

        # 1) Agregace: sečti stejné polotovary (RC/SK/Name/Unit)
        def pkey(it): return (getattr(it,"rc",""), getattr(it,"sk",""), getattr(it,"name",""), getattr(it,"unit",""))
        groups: Dict[Tuple[str,str,str,str], Dict[str, Any]] = {}
        for it in items:
            k = pkey(it)
            raw, meat = self.raw_mass_of(it)  # i když teď „syrové“ neřešíš, fallback bere qty => funguje
            g = groups.setdefault(k, {"template": it, "raw_total": 0.0, "qty_total": 0.0, "meat": meat})
            g["raw_total"] += float(raw or 0.0)
            g["qty_total"] += float(getattr(it,"qty",0.0) or 0.0)
            if not g["meat"] and meat: g["meat"] = meat

        # 2) Rovnoměrné rozložení produktů po dnech (globálně)
        day_load_raw = [0.0 for _ in range(days)]
        ordered_groups = sorted(groups.items(), key=lambda kv: kv[1]["raw_total"], reverse=True)

        for _, g in ordered_groups:
            base = g["template"]
            total_raw = float(g["raw_total"])
            total_qty = float(g["qty_total"]) if g["qty_total"] > 0 else total_raw
            meat = (g["meat"] or "").lower() if g["meat"] else None
            name_lc = (getattr(base,"name","") or "").lower()
            is_bilt = is_biltong_name(name_lc)

            # poměr pro dopočet hotového množství z dávky (když by qty_total bylo 0, padni na 1:1)
            ratio_qty_per_raw = (total_qty / total_raw) if total_raw > 0 else 1.0
            remaining_raw = total_raw if total_raw > 0 else total_qty  # když nemáme raw, použij qty

            while remaining_raw > 1e-9:
                # den s nejnižší aktuální zátěží
                day_order = sorted(range(days), key=lambda d: day_load_raw[d])
                placed_this_round = False

                for d in day_order:
                    # uvnitř dne: preferuj jednu udírnu; když nestačí, další řádky POD SEBOU ve STEJNÉ udírně;
                    # až když dojdou řádky nebo kapacita je nulová, použij další udírnu
                    if is_bilt:
                        smoker_order = [self.reserved_smoker_index]  # biltong jen #4
                    else:
                        smoker_order = [s for s in range(1, smokers+1) if s != self.reserved_smoker_index]
                        # silnější udírny dřív
                        smoker_order.sort(key=lambda s: float(self.capacity.capacity_for(s, meat)), reverse=True)

                    for s in smoker_order:
                        cap_per_slot = float(self.capacity.capacity_for(s, meat))
                        if is_bilt:
                            # biltong bez limitu (per slot)
                            cap_per_slot = remaining_raw if remaining_raw > 0 else 0.0
                        if cap_per_slot <= 1e-9 and not is_bilt:
                            continue

                        # PRO TUTO UDÍRNU POKLÁDEJ POD SEBE (r = 1..rows), KAŽDÝ ŘÁDEK = NOVÝ BLOK
                        for r in range(1, rows+1):
                            if remaining_raw <= 1e-9:
                                break
                            if grid[(d,s,r)]:
                                continue  # slot obsazen

                            take_raw = min(cap_per_slot, remaining_raw)
                            # dopočet hotového množství; když by vyšla 0, použij raw jako fallback, ať není "bez váhy"
                            take_qty = take_raw * ratio_qty_per_raw
                            if take_qty <= 1e-12 and take_raw > 0:
                                take_qty = take_raw

                            item = self._make_item(base, qty=take_qty, raw_qty=take_raw if take_raw > 0 else None)

                            # tvrdá pravidla (ASK prefill neakceptuje – #4 pro ne-biltong sem ani nejde)
                            res = self._evaluate_slot(item, s, grid[(d,s,r)], phase="prefill")
                            if not res.ok:
                                continue

                            grid[(d,s,r)].append(item)
                            if self.merge_policy:
                                self.merge_policy.apply(s, grid[(d,s,r)])

                            remaining_raw -= take_raw
                            day_load_raw[d] += take_raw
                            placed_this_round = True

                        if remaining_raw <= 1e-9:
                            break  # hotovo
                    if remaining_raw <= 1e-9:
                        break  # hotovo v tomhle dnu

                if not placed_this_round:
                    # žádné další volné sloty / dny → konec plánování zbytku
                    break

        return grid

    # ---------- MOVE (interaktivní prohození slotů) ----------
    def try_move(self, grid: Dict[CellKey, List[HasItemAttrs]], src: CellKey, dst: CellKey,
                 *, confirm_cb: Optional[ConfirmCallback], allow_split_on_move: bool=True) -> Tuple[bool, Optional[RuleViolation]]:
        if src == dst or src not in grid or dst not in grid:
            return False, RuleViolation("R-ENGINE", "Neplatná operace", "Neplatný zdroj/cíl slotu.", {})
        src_items = list(grid[src]); dst_items = list(grid[dst])

        new_dst: List[HasItemAttrs] = list(dst_items)
        for it in src_items:
            res = self.validate_slot(it, dst[1], new_dst, confirm_cb=confirm_cb, phase="move")
            if res.ok:
                new_dst.append(it); continue
            if res.split_qty is not None and allow_split_on_move:
                part = self._make_item(it, qty=float(res.split_qty))
                rem  = self._make_item(it, qty=float(res.remainder_qty))
                new_dst.append(part)
                continue
            return False, (res.violation or RuleViolation("R-UNKNOWN","Pravidlo zamítlo přesun","Přesun nelze provést.",{}))

        new_src: List[HasItemAttrs] = list(src_items)
        for it in dst_items:
            res = self.validate_slot(it, src[1], new_src, confirm_cb=confirm_cb, phase="move")
            if res.ok:
                new_src.append(it); continue
            if res.split_qty is not None and allow_split_on_move:
                part = self._make_item(it, qty=float(res.split_qty))
                rem  = self._make_item(it, qty=float(res.remainder_qty))
                new_src.append(part)
                continue
            return False, (res.violation or RuleViolation("R-UNKNOWN","Pravidlo zamítlo přesun","Přesun nelze provést.",{}))

        grid[src] = new_src
        grid[dst] = new_dst
        if self.merge_policy:
            self.merge_policy.apply(src[1], grid[src])
            self.merge_policy.apply(dst[1], grid[dst])
        return True, None

# ---------- Factory ----------
def build_default_engine(
    *,
    base_per_smoker: List[float],
    per_type_overrides: Optional[Dict[str, List[float]]] = None,
    raw_mass_extractor: Optional[RawMassExtractor] = None,
    is_biltong: Optional[Callable[[str], bool]] = None,
    reserved_smoker_index: int = 4,
) -> RuleEngine:
    per_type_overrides = per_type_overrides or {}
    _is_bilt = is_biltong or is_biltong_name
    _raw_ex  = raw_mass_extractor or default_raw_mass_extractor
    cap = TableCapacity(base_per_smoker=base_per_smoker, per_type_overrides=per_type_overrides)

    constraints: List[Constraint] = [
        BiltongRule(is_biltong=_is_bilt, reserved_idx=reserved_smoker_index),
        SingleProductPerSlotRule(),
        CapacityByRawRule(capacity=cap, raw_mass_of=_raw_ex, is_biltong=_is_bilt),
    ]
    merge = AutoMergePolicy()
    return RuleEngine(constraints=constraints, capacity=cap, raw_mass_of=_raw_ex,
                      merge_policy=merge, reserved_smoker_index=reserved_smoker_index)
