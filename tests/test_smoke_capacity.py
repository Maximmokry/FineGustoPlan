# -*- coding: utf-8 -*-
import pandas as pd

from services.smoke_capacity import CapacityRules


def test_capacity_rules_base_and_override():
    rules = CapacityRules(
        base_per_smoker=[400, 300, 400, 400],
        per_type_overrides={
            "hovezi": [300, 250, 300, 300],
        }
    )

    # base
    assert rules.capacity_for(None, 0) == 400
    assert rules.capacity_for("", 1) == 300

    # overrides by meat type
    assert rules.capacity_for("hovezi", 0) == 300
    assert rules.capacity_for("HoVeZi", 1) == 250
    # if index out of range, fall back to last in list
    assert rules.capacity_for("hovezi", 99) == 300
