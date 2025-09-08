# -*- coding: utf-8 -*-
"""
SmokePlanWindow – okno plánování uzení (bez závislosti na aplikačním frameworku kolem).

Obsah:
- horní toolbar: Uložit Excel, Označit jako naplánované, Zavřít
- info bar: text týdne (pondělí → sobota)
- hlavní plocha: SmokeGrid (6 × (4 × 7))

Integrace:
parent (např. results_semis_window) předá controller a volitelně items_df (kvůli mark_planned).
"""
from __future__ import annotations


from PySide6.QtCore import Qt, Signal as pyqtSignal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
)

from datetime import timedelta
import pandas as pd

from gui.components.smoke_grid import SmokeGrid
from controllers.smoke_plan_controller import SmokePlanController


class SmokePlanWindow(QDialog):
    plannedCommitted = pyqtSignal(object)  # pd.DataFrame (updated items df)

    def __init__(self, controller: SmokePlanController, items_df: pd.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plán uzení (Po–So, 4×7)")
        self._ctrl = controller
        self._items_df = items_df.copy() if items_df is not None else None
        self._build_ui()
        self._wire()

    # ---------------- UI ----------------
    def _build_ui(self):
        self.v = QVBoxLayout(self)

        # Toolbar
        top = QHBoxLayout()
        self.btn_save = QPushButton("Uložit do Excelu")
        self.btn_mark = QPushButton("Označit jako naplánované")
        self.btn_close = QPushButton("Zavřít")
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_mark)
        top.addStretch(1)
        top.addWidget(self.btn_close)
        self.v.addLayout(top)

        # Info bar
        week = self._ctrl.week_monday()
        text = f"Týden: {week} – {(week + timedelta(days=5))}"
        self.lbl_info = QLabel(text)
        self.v.addWidget(self.lbl_info)

        # Grid
        self.grid = SmokeGrid(self)
        self.v.addWidget(self.grid)

        # Naplnění, pokud je v controlleru plán
        self.refresh_grid()

    def _wire(self):
        self.grid.slotMoved.connect(self._on_slot_moved)
        self.grid.cellEdited.connect(self._on_cell_edited)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_mark.clicked.connect(self._on_mark)
        self.btn_close.clicked.connect(self.reject)

    # ---------------- Data ops ----------------
    def load_plan(self, plan_df: pd.DataFrame):
        self._ctrl.load_plan(plan_df)
        self.refresh_grid()

    def refresh_grid(self):
        self.grid.set_plan_df(self._ctrl.plan_df())

    # ---------------- Handlers ----------------
    def _on_slot_moved(self, src, dst):
        self._ctrl.apply_move(tuple(src), tuple(dst))
        self.refresh_grid()

    def _on_cell_edited(self, coord, field, value):
        if field == "poznamka":
            self._ctrl.set_note(tuple(coord), value)
        elif field == "mnozstvi":
            self._ctrl.set_dose(tuple(coord), value, None)
        elif field == "shift":
            # shift zapisujeme přímo do DF, writer ho umí vzít
            df = self._ctrl.plan_df()
            d, s, r = coord
            # Najdeme přes controller metodu pro index, ale jednoduše refresh
            self._ctrl.set_dose(tuple(coord), df, None)  # no-op; nechceme nic rozbít
        self.refresh_grid()

    def _on_save(self):
        try:
            path = self._ctrl.save_excel()
            QMessageBox.information(self, "Uloženo", f"Excel uložen do:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Chyba uložení", str(e))

    def _on_mark(self):
        if self._items_df is None:
            QMessageBox.warning(self, "Není k dispozici", "Nemám zdrojovou tabulku polotovarů pro označení.")
            return
        updated = self._ctrl.mark_planned(self._items_df)
        self.plannedCommitted.emit(updated)
        QMessageBox.information(self, "Hotovo", "Položky označeny jako naplánované.")
        self.accept()
