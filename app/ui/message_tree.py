"""Tree of message types -> fields, with checkable leaves to plot."""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from app.core.log_loader import LogData


class MessageTree(QTreeWidget):
    field_toggled = Signal(str, str, bool)  # msg_type, field_name, checked

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Message / Field"])
        self.itemChanged.connect(self._on_item_changed)
        self._loading = False

    def load(self, log_data: LogData):
        self._loading = True
        self.clear()
        for msg_type in log_data.message_types:
            fields = log_data.fields_for(msg_type)
            if not fields:
                continue
            parent_item = QTreeWidgetItem([msg_type])
            self.addTopLevelItem(parent_item)
            for fname in fields:
                child = QTreeWidgetItem([fname])
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked)
                child.setData(0, Qt.UserRole, (msg_type, fname))
                parent_item.addChild(child)
        self._loading = False

    def set_field_checked(self, msg_type: str, field_name: str, checked: bool):
        for i in range(self.topLevelItemCount()):
            parent_item = self.topLevelItem(i)
            if parent_item.text(0) != msg_type:
                continue
            for j in range(parent_item.childCount()):
                child = parent_item.child(j)
                if child.text(0) == field_name:
                    child.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
                    return

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._loading:
            return
        data = item.data(0, Qt.UserRole)
        if data is None:
            return
        msg_type, fname = data
        checked = item.checkState(0) == Qt.Checked
        self.field_toggled.emit(msg_type, fname, checked)
