# services/smoke_rules.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Protocol, Any

# --------- Typy ----------
CellKey = Tuple[int, int, int]   # (den_idx, udirna_idx [1..N], radek_idx [1..R])
Phase   = str                    # "prefill" | "move" | "interactive"

class HasItemAttrs(Protocol):
    rc: str
    sk: str
    name: str
    qty: Optional[float]
    unit: str
    # volitelné atributy:
    # raw_qty: Optional[float]
    # meat_type: Optional[str]
    # raw_children: Optional[List[Dict]]  # [{"meat_type":"hovezi","raw":12.3}, ...]

RawMassExtractor = Callable[[HasItemAttrs], Tuple[float, Optional[str]]]  # -> (raw_mass, meat_type)
ConfirmCallback  = Callable[[str], bool]

# --------- Porušení / výstupy ----------
@dataclass
class RuleViolation:
    rule_id: str
    title: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CheckOutcome:
    kind: str  # "OK" | "SPLIT" | "ASK" | "BLOCK"
    penalty: float = 0.0
    split_qty: Optional[float] = None
    remainder_qty: Optional[float] = None
    violation: Optional[RuleViolation] = None
    ask_message: Optional[str] = None

# --------- Kapacity ----------
class CapacityProvider(Protocol):
    def capacity_for(self, smoker_idx: int, meat_type: Optional[str]) -> float: ...

@dataclass
class TableCapacity(CapacityProvider):
    """
    base_per_smoker: [cap_smoker1, cap_smoker2, ...]
    per_type_overrides: {"hovezi":[...], "veprove":[...], ...} — kapacita pro dané maso
    """
    base_per_smoker: List[float]
    per_type_overrides: Dict[str, List[float]] = field(default_factory=dict)
    def capacity_for(self, smoker_idx: int, meat_type: Optional[str]) -> float:
        if meat_type:
            k = str(meat_type).strip().lower()
            if k in self.per_type_overrides:
                arr = self.per_type_overrides[k]
                if 0 <= smoker_idx-1 < len(arr): return float(arr[smoker_idx-1])
                if arr: return float(arr[-1])
        if 0 <= smoker_idx-1 < len(self.base_per_smoker):
            return float(self.base_per_smoker[smoker_idx-1])
        return float(self.base_per_smoker[-1]) if self.base_per_smoker else 0.0

# --------- Abstrakce pravidla ----------
class Constraint(Protocol):
    def check(self, item: HasItemAttrs, slot_items: List[HasItemAttrs], smoker_idx: int, phase: Phase) -> CheckOutcome: ...

# --------- Pravidla ----------
@dataclass
class SingleProductPerSlotRule:
    """R-SINGLE-PRODUCT: V jednom slotu (řádek udírny v daný den) může být jen jeden polotovar."""
    def _key(self, it) -> Tuple[str, str, str, str]:
        return (str(getattr(it,"rc","") or ""), str(getattr(it,"sk","") or ""),
                str(getattr(it,"name","") or ""), str(getattr(it,"unit","") or ""))
    def check(self, item, slot_items, smoker_idx: int, phase: Phase) -> CheckOutcome:
        if not slot_items:
            return CheckOutcome(kind="OK")

        incoming = self._key(item)
        present_keys = {self._key(it) for it in slot_items}

        # Slot už obsahuje mix → zamítni (ochrana proti starým datům)
        if len(present_keys) > 1:
            return CheckOutcome(
                kind="BLOCK",
                violation=RuleViolation(
                    "R-SINGLE-PRODUCT", "Jeden polotovar na slot",
                    "V cílovém slotu už je směs různých polotovarů.",
                    {"smoker": smoker_idx, "present_keys": list(present_keys)},
                ),
            )

        only_key = next(iter(present_keys))
        if incoming != only_key:
            return CheckOutcome(
                kind="BLOCK",
                violation=RuleViolation(
                    "R-SINGLE-PRODUCT", "Jeden polotovar na slot",
                    "V cíli je jiný polotovar.",
                    {"smoker": smoker_idx, "incoming": incoming, "present": only_key},
                ),
            )

        return CheckOutcome(kind="OK")

@dataclass
class BiltongRule:
    """
    R-SMOKER4-RESERVED + R-BILTONG-ONLY-4:
    - Udírna #4 je vyhrazena pro biltong (ne-biltong do #4 = ASK; v prefillu se #4 pro ne-biltong NEpoužije).
    - Biltong smí POUZE do #4 (vždy BLOCK mimo #4).
    - Biltong nemá kapacitní limit.
    """
    is_biltong: Callable[[str], bool]
    reserved_idx: int = 4
    non_biltong_on_reserved_ask: bool = True

    def check(self, item: HasItemAttrs, slot_items: List[HasItemAttrs], smoker_idx: int, phase: Phase) -> CheckOutcome:
        name = (item.name or "").lower()
        is_b = self.is_biltong(name)

        if is_b and smoker_idx != self.reserved_idx:
            return CheckOutcome(
                kind="BLOCK",
                violation=RuleViolation(
                    "R-BILTONG-ONLY-4", "Biltong jen do #4",
                    f"Cíl je #{smoker_idx}, ale biltong smí pouze do #{self.reserved_idx}.",
                    {"smoker": smoker_idx, "product": item.name},
                ),
            )

        if (not is_b) and smoker_idx == self.reserved_idx and self.non_biltong_on_reserved_ask:
            return CheckOutcome(
                kind="ASK",
                violation=RuleViolation(
                    "R-SMOKER4-RESERVED", f"Udírna #{self.reserved_idx} vyhrazena pro biltong",
                    "Vložit přesto?", {"smoker": smoker_idx, "product": item.name},
                ),
                ask_message=f"Udírna #{self.reserved_idx} je vyhrazena pro biltong. Vložit přesto?",
            )

        return CheckOutcome(kind="OK")

@dataclass
class CapacityByRawRule:
    """
    R-CAP-RAW: kapacita slotu dle SYROVÉ hmoty (kombinace udírna × typ masa).
    cap<=0 => neomezené (např. biltong). Když se nevejde, navrhne SPLIT (užitečné pro interaktivní přesun).
    """
    capacity: CapacityProvider
    raw_mass_of: RawMassExtractor
    is_biltong: Callable[[str], bool]
    split_penalty: float = 0.0
    def check(self, item: HasItemAttrs, slot_items: List[HasItemAttrs], smoker_idx: int, phase: Phase) -> CheckOutcome:
        if self.is_biltong(item.name or ""):  # biltong bez limitu
            return CheckOutcome(kind="OK")
        cap = float(self.capacity.capacity_for(smoker_idx, self.raw_mass_of(item)[1]))
        if cap <= 0:
            return CheckOutcome(kind="OK")
        cur_raw = 0.0
        for it in slot_items:
            r,_ = self.raw_mass_of(it)
            cur_raw += float(r or 0.0)
        item_raw,_ = self.raw_mass_of(item)
        if cur_raw + float(item_raw or 0.0) <= cap + 1e-9:
            return CheckOutcome(kind="OK")
        to_fit = max(cap - cur_raw, 0.0)
        if to_fit <= 1e-9:
            return CheckOutcome(kind="BLOCK",
                violation=RuleViolation("R-CAP-RAW","Kapacita slotu (syrové maso)",
                                        f"Nulová rezerva v udírně #{smoker_idx}.", {"smoker": smoker_idx}))
        if (item.qty or 0) <= 0:
            return CheckOutcome(kind="BLOCK",
                violation=RuleViolation("R-CAP-RAW","Kapacita slotu (syrové maso)",
                                        f"Položka bez 'qty' se nedá dělit.", {"smoker": smoker_idx}))
        ratio = to_fit / max(float(item_raw or 0.0), 1e-9)
        split_qty = float(item.qty) * ratio
        remainder_qty = float(item.qty) - split_qty
        return CheckOutcome(kind="SPLIT", penalty=self.split_penalty,
                            split_qty=split_qty, remainder_qty=remainder_qty,
                            violation=RuleViolation("R-CAP-RAW","Kapacita slotu (syrové maso)",
                                                    "Položka se celá nevejde – rozdělím.", {"smoker": smoker_idx}))

# --------- Auto-merge (stejný polotovar -> 1 řádek) ----------
@dataclass
class AutoMergePolicy:
    def apply(self, smoker_idx: int, items: List[HasItemAttrs]) -> None:
        if not items:
            return

        def key(it):
            return (str(getattr(it,"rc","") or ""), str(getattr(it,"sk","") or ""),
                    str(getattr(it,"name","") or ""), str(getattr(it,"unit","") or ""))

        groups: Dict[Tuple[str,str,str,str], List[HasItemAttrs]] = {}
        for it in items:
            groups.setdefault(key(it), []).append(it)

        merged: List[HasItemAttrs] = []
        for _, group in groups.items():
            base = group[0]
            sum_qty = 0.0
            sum_raw = 0.0
            has_raw = False
            for it in group:
                sum_qty += float(getattr(it, "qty", 0.0) or getattr(it, "mnozstvi", 0.0) or 0.0)
                if hasattr(it, "raw_qty"):
                    has_raw = True
                    sum_raw += float(getattr(it, "raw_qty", 0.0) or 0.0)

            # vytvoř NOVÝ objekt (žádné přepisování existujících referencí)
            cls = type(base)
            try:
                new_item = cls(
                    rc=getattr(base, "rc", ""),
                    sk=getattr(base, "sk", ""),
                    name=getattr(base, "name", ""),
                    qty=float(sum_qty),
                    unit=getattr(base, "unit", ""),
                    source_id=getattr(base, "source_id", ""),
                )
            except Exception:
                @dataclass
                class _Simple:
                    rc: str; sk: str; name: str; qty: float; unit: str; source_id: str
                new_item = _Simple(
                    getattr(base,"rc",""), getattr(base,"sk",""), getattr(base,"name",""),
                    float(sum_qty), getattr(base,"unit",""), getattr(base,"source_id",""),
                )

            # alias pro UI, kdyby používalo 'mnozstvi'
            try:
                setattr(new_item, "mnozstvi", float(sum_qty))
            except Exception:
                pass

            if has_raw:
                try:
                    setattr(new_item, "raw_qty", float(sum_raw))
                except Exception:
                    pass

            for attr in ("meat_type", "raw_children"):
                if hasattr(base, attr):
                    try:
                        setattr(new_item, attr, getattr(base, attr))
                    except Exception:
                        pass

            merged.append(new_item)

        items[:] = merged

# --------- Extraktory ----------
def default_raw_mass_extractor(it: HasItemAttrs) -> Tuple[float, Optional[str]]:
    """
    Syrová hmota = součet 'raw' všech dětí v it.raw_children (pokud existují),
    jinak použij 'raw_qty', jinak padni na 'qty'.
    meat_type: jednoznačný typ z dětí; jinak it.meat_type; jinak None.
    """
    ch = getattr(it, "raw_children", None)
    if isinstance(ch, list) and ch:
        total = 0.0
        types = {str((c.get("meat_type") or "")).lower() for c in ch if isinstance(c, dict)}
        for c in ch:
            try:
                total += float(c.get("raw") or c.get("qty") or 0.0)
            except Exception:
                pass
        meat = list(types)[0] if len(types) == 1 else getattr(it, "meat_type", None)
        return float(total), (str(meat).lower() if meat else None)

    rq = getattr(it, "raw_qty", None)
    if rq is not None:
        return float(rq or 0.0), (str(getattr(it, "meat_type", "")).lower() or None)

    return float(getattr(it, "qty", 0.0) or getattr(it, "mnozstvi", 0.0) or 0.0), (str(getattr(it, "meat_type", "")).lower() or None)

def is_biltong_name(name: str) -> bool:
    return "biltong" in (name or "").lower()
