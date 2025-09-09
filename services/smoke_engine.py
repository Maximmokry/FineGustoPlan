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
    RuleViolation,
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

    # --- pravidla nad slotem ---
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
    def _get_qty(self, it: HasItemAttrs) -> float:
        """Hotové množství (qty) s fallbackem na 'mnozstvi'."""
        v = getattr(it, "qty", None)
        if v is None:
            v = getattr(it, "mnozstvi", None)
        try:
            return float(v or 0.0)
        except Exception:
            return 0.0

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
        try: setattr(new, "mnozstvi", float(qty))
        except Exception: pass

        if raw_qty is not None:
            try: setattr(new, "raw_qty", float(raw_qty))
            except Exception: pass

        for attr in ("meat_type","raw_children"):
            if hasattr(base, attr):
                try: setattr(new, attr, getattr(base, attr))
                except Exception: pass
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

        # 1) Agregace: sečti stejné polotovary (RC/SK/Name/Unit) podle HOTOVÉHO množství
        def pkey(it): return (getattr(it,"rc",""), getattr(it,"sk",""), getattr(it,"name",""), getattr(it,"unit",""))
        groups: Dict[Tuple[str,str,str,str], Dict[str, Any]] = {}
        for it in items:
            k = pkey(it)
            qty_val = self._get_qty(it)  # hotové množství
            meat = getattr(it, "meat_type", None)
            g = groups.setdefault(k, {"template": it, "qty_total": 0.0, "meat": (str(meat).lower() if meat else None)})
            g["qty_total"] += float(qty_val or 0.0)
            if not g["meat"] and meat:
                g["meat"] = str(meat).lower()

        # 2) … a rozkládej produkty napříč dny rovnoměrně
        day_load_qty = [0.0 for _ in range(days)]                       # zátěž (hotové množství) na den
        smoker_load_qty: Dict[int, List[float]] = {d: [0.0]*(smokers+1) for d in range(days)}  # zátěž na (den, udírna)

        ordered_groups = sorted(groups.items(), key=lambda kv: kv[1]["qty_total"], reverse=True)

        for _, g in ordered_groups:
            base = g["template"]
            total_qty = float(g["qty_total"])
            if total_qty <= 1e-12:
                continue  # nic k plánování
            meat = g["meat"]
            name_lc = (getattr(base,"name","") or "").lower()
            is_bilt = is_biltong_name(name_lc)

            remaining_qty = total_qty

            while remaining_qty > 1e-9:
                # den s nejnižší aktuální zátěží
                day_order = sorted(range(days), key=lambda d: day_load_qty[d])
                placed_this_round = False

                for d in day_order:
                    # --- V TOMTO DNI: vyber udírnu s NEJMENŠÍ zátěží (a při shodě s největší kapacitou) ---
                    if is_bilt:
                        allowed = [self.reserved_smoker_index]  # biltong jen #4
                    else:
                        allowed = [s for s in range(1, smokers+1) if s != self.reserved_smoker_index]

                    def cap(s: int) -> float:
                        c = float(self.capacity.capacity_for(s, meat))
                        return c if c > 0 else float('inf')  # cap<=0 = neomezené -> ber to jako "velmi velkou" kapacitu

                    # pořadí: nejnižší aktuální zátěž -> největší kapacita
                    smoker_order = sorted(allowed, key=lambda s: (smoker_load_qty[d][s], -cap(s)))

                    for s in smoker_order:
                        cap_per_slot = float(self.capacity.capacity_for(s, meat))
                        if cap_per_slot <= 0:
                            cap_per_slot = remaining_qty  # neomezené

                        # PRO TUTO UDÍRNU: stackuj POD SEBE (r = 1..rows). Pokud polotovar potřebuje víc bloků,
                        # zaplníme řádky této udírny, teprve pak jdeme do další udírny.
                        for r in range(1, rows+1):
                            if remaining_qty <= 1e-9:
                                break
                            if grid[(d,s,r)]:
                                continue  # slot obsazen (jiný polotovar)

                            take_qty = min(cap_per_slot, remaining_qty)
                            if take_qty <= 1e-12:
                                continue

                            item = self._make_item(base, qty=take_qty)

                            # tvrdá pravidla (ASK prefill neakceptuje – #4 pro ne-biltong sem ani nejde)
                            res = self._evaluate_slot(item, s, grid[(d,s,r)], phase="prefill")
                            if not res.ok:
                                continue

                            grid[(d,s,r)].append(item)
                            if self.merge_policy:
                                self.merge_policy.apply(s, grid[(d,s,r)])

                            remaining_qty       -= take_qty
                            day_load_qty[d]     += take_qty
                            smoker_load_qty[d][s] += take_qty
                            placed_this_round = True

                        if remaining_qty <= 1e-9:
                            break  # hotovo v této udírně
                    if remaining_qty <= 1e-9:
                        break  # hotovo v tomto dni

                if not placed_this_round:
                    # žádné volné sloty v žádném dni → konec plánování zbytku
                    break

        return grid

        # ---------- MOVE (interaktivní přesun nebo swap) ----------
    def try_move(self, grid: Dict[CellKey, List[HasItemAttrs]], src: CellKey, dst: CellKey,
                 *, confirm_cb: Optional[ConfirmCallback], allow_split_on_move: bool = False
                 ) -> Tuple[bool, Optional[RuleViolation]]:
        """
        Přesun:  když je cílový slot prázdný, přesune obsah src -> dst (src se vyprázdní).
        Swap:    když je cílový slot neprázdný, VYMĚNÍ obsah src <-> dst.
        Pozn.:   defaultně nedovolujeme dělení (allow_split_on_move=False), aby se swap nechoval překvapivě.
        """
        if src == dst or src not in grid or dst not in grid:
            return False, RuleViolation("R-ENGINE", "Neplatná operace", "Neplatný zdroj/cíl slotu.", {})

        src_items = list(grid[src])
        dst_items = list(grid[dst])

        # 1) Validuj položky ze src, jako kdyby v cíli nic nebylo (swap = nahradíme obsah)
        cand_dst: List[HasItemAttrs] = []
        for it in src_items:
            res = self.validate_slot(it, dst[1], cand_dst, confirm_cb=confirm_cb, phase="move")
            if res.ok:
                cand_dst.append(it)
            elif res.split_qty is not None and allow_split_on_move:
                part = self._make_item(it, qty=float(res.split_qty))
                cand_dst.append(part)
                # zbytek necháme v původním slotu (u swapu nedává velký smysl dělit obě strany)
            else:
                return False, (res.violation or RuleViolation("R-UNKNOWN", "Pravidlo zamítlo přesun", "Přesun nelze provést.", {}))

        # 2) Validuj položky z dst, jako kdyby ve zdroji nic nebylo
        cand_src: List[HasItemAttrs] = []
        for it in dst_items:
            res = self.validate_slot(it, src[1], cand_src, confirm_cb=confirm_cb, phase="move")
            if res.ok:
                cand_src.append(it)
            elif res.split_qty is not None and allow_split_on_move:
                part = self._make_item(it, qty=float(res.split_qty))
                cand_src.append(part)
            else:
                return False, (res.violation or RuleViolation("R-UNKNOWN", "Pravidlo zamítlo přesun", "Přesun nelze provést.", {}))

        # 3) Přiřaď – žádné duplikace, žádné přidávání k původním seznamům
        grid[dst] = cand_dst
        grid[src] = cand_src

        # 4) Volitelný merge (bez vedlejších efektů – tvoří nové instance)
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
        # Kapacitní kontrola (slot-level); v přefillu dáváme na slot max kapacitu,
        # pravidlo je užitečné hlavně při interaktivních přesunech.
        CapacityByRawRule(capacity=cap, raw_mass_of=_raw_ex, is_biltong=_is_bilt),
    ]
    merge = AutoMergePolicy()
    return RuleEngine(constraints=constraints, capacity=cap, raw_mass_of=_raw_ex,
                      merge_policy=merge, reserved_smoker_index=reserved_smoker_index)
