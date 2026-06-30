"""Tree of message types -> fields, with checkable leaves to plot.

Each field row has a star toggle button; starring a field duplicates it
into a separate "Избранное" panel above the main tree (split by a
draggable divider), so frequently used fields don't need to be hunted
down in their original message group.
"""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QToolButton, QHeaderView, QMenu, QInputDialog,
)

from app.core import favorites_store
from app.core.log_loader import LogData

_STAR_ACTIVE_STYLE = "QToolButton { border: none; color: #ffd700; font-size: 14px; }"
_STAR_INACTIVE_STYLE = "QToolButton { border: none; color: #888; font-size: 14px; }"


_PRESETS = [
    ("airspeed_ground_speed", "AirSpeed - Ground Speed"),
    ("battery1_vs_battery2", "Battery 1 - Battery 2"),
    ("baro_vs_gps_altitude", "Baro - GPS Altitude"),
]


class MessageTree(QWidget):
    field_toggled = Signal(str, str, bool)  # msg_type, field_name, checked
    preset_activated = Signal(str)  # preset id

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.favorites_tree = self._make_tree("Избранное")
        self.favorites_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.favorites_tree.customContextMenuRequested.connect(self._on_favorites_context_menu)
        self.tree = self._make_tree("Параметры")
        self.presets_tree = self._make_presets_tree("Пресеты")

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.favorites_tree)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.presets_tree)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        layout.addWidget(splitter)

        self._loading = False
        self._syncing = False
        self._favorites: set[tuple[str, str]] = favorites_store.load_favorites()
        self._renames: dict[tuple[str, str], str] = favorites_store.load_renames()
        self._leaf_items: dict[tuple[str, str], list[QTreeWidgetItem]] = {}
        self._star_buttons: dict[tuple[str, str], list[QToolButton]] = {}

    def _make_tree(self, header: str) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels([header, ""])
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tree.header().setSectionResizeMode(1, QHeaderView.Fixed)
        tree.setColumnWidth(1, 26)
        tree.itemChanged.connect(self._on_item_changed)
        tree.itemExpanded.connect(lambda _item: tree.resizeColumnToContents(0))
        tree.itemCollapsed.connect(lambda _item: tree.resizeColumnToContents(0))
        return tree

    def _make_presets_tree(self, header: str) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(1)
        tree.setHeaderLabels([header])
        for preset_id, label in _PRESETS:
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.UserRole, preset_id)
            tree.addTopLevelItem(item)
        tree.itemClicked.connect(self._on_preset_clicked)
        return tree

    def _on_preset_clicked(self, item: QTreeWidgetItem, column: int):
        preset_id = item.data(0, Qt.UserRole)
        if preset_id:
            self.preset_activated.emit(preset_id)

    def load(self, log_data: LogData):
        self._loading = True
        self.tree.clear()
        self.favorites_tree.clear()
        self._leaf_items.clear()
        self._star_buttons.clear()

        for msg_type in log_data.message_types:
            fields = log_data.fields_for(msg_type)
            if not fields:
                continue
            parent_item = QTreeWidgetItem([msg_type])
            self.tree.addTopLevelItem(parent_item)
            for fname in fields:
                key = (msg_type, fname)
                self._build_leaf(self.tree, parent_item.addChild, key)

        for key in sorted(self._favorites):
            if key in self._leaf_items:
                self._build_leaf(self.favorites_tree, self.favorites_tree.addTopLevelItem, key)

        self._loading = False

    def _build_leaf(self, tree_widget: QTreeWidget, attach, key: tuple[str, str]) -> QTreeWidgetItem:
        msg_type, fname = key
        display_name = self._renames.get(key, fname) if tree_widget is self.favorites_tree else fname
        item = QTreeWidgetItem([display_name])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Unchecked)
        item.setData(0, Qt.UserRole, key)
        attach(item)
        self._leaf_items.setdefault(key, []).append(item)

        is_favorite = key in self._favorites
        star = QToolButton()
        star.setCheckable(True)
        star.setChecked(is_favorite)
        star.setText("★")
        star.setStyleSheet(_STAR_ACTIVE_STYLE if is_favorite else _STAR_INACTIVE_STYLE)
        star.setAutoRaise(True)
        star.toggled.connect(lambda checked, k=key: self._on_star_toggled(checked, k))
        tree_widget.setItemWidget(item, 1, star)
        self._star_buttons.setdefault(key, []).append(star)
        return item

    def set_field_checked(self, msg_type: str, field_name: str, checked: bool):
        key = (msg_type, field_name)
        for item in self._leaf_items.get(key, []):
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._loading or self._syncing or column != 0:
            return
        data = item.data(0, Qt.UserRole)
        if data is None:
            return
        msg_type, fname = data
        checked = item.checkState(0) == Qt.Checked

        self._syncing = True
        for other in self._leaf_items.get((msg_type, fname), []):
            if other is not item:
                other.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        self._syncing = False

        self.field_toggled.emit(msg_type, fname, checked)

    def _on_star_toggled(self, checked: bool, key: tuple[str, str]):
        if self._loading:
            return
        msg_type, fname = key

        for btn in self._star_buttons.get(key, []):
            btn.blockSignals(True)
            btn.setChecked(checked)
            btn.setStyleSheet(_STAR_ACTIVE_STYLE if checked else _STAR_INACTIVE_STYLE)
            btn.blockSignals(False)

        if checked:
            if key not in self._favorites:
                self._favorites.add(key)
                existing = self._leaf_items.get(key, [])
                check_state = existing[0].checkState(0) if existing else Qt.Unchecked
                self._loading = True
                self._build_leaf(self.favorites_tree, self.favorites_tree.addTopLevelItem, key)
                self._loading = False
                for item in self._leaf_items[key]:
                    item.setCheckState(0, check_state)
        else:
            if key in self._favorites:
                self._favorites.discard(key)
                items = self._leaf_items.get(key, [])
                for item in list(items):
                    if item.treeWidget() is self.favorites_tree:
                        idx = self.favorites_tree.indexOfTopLevelItem(item)
                        btn = self.favorites_tree.itemWidget(item, 1)
                        if idx >= 0:
                            self.favorites_tree.takeTopLevelItem(idx)
                        if btn:
                            btn.deleteLater()
                        items.remove(item)
                        self._star_buttons[key] = [b for b in self._star_buttons[key] if b is not btn]

        favorites_store.save_favorites(self._favorites)

    def _on_favorites_context_menu(self, pos):
        item = self.favorites_tree.itemAt(pos)
        if item is not None:
            key = item.data(0, Qt.UserRole)
            if key is None:
                return
            menu = QMenu(self)
            rename_action = menu.addAction("Переименовать параметр")
            rename_action.triggered.connect(lambda: self._rename_favorite(key))
            if key in self._renames:
                restore_action = menu.addAction("Вернуть оригинальное имя параметра")
                restore_action.triggered.connect(lambda: self._restore_favorite_name(key))
            menu.exec(self.favorites_tree.viewport().mapToGlobal(pos))
            return

        if not self._favorites:
            return
        menu = QMenu(self)
        clear_action = menu.addAction("Очистить избранное")
        clear_action.triggered.connect(self._clear_favorites)
        menu.exec(self.favorites_tree.viewport().mapToGlobal(pos))

    def _rename_favorite(self, key: tuple[str, str]):
        msg_type, fname = key
        current = self._renames.get(key, fname)
        new_name, ok = QInputDialog.getText(
            self, "Переименовать параметр", "Новое имя:", text=current
        )
        if ok and new_name.strip():
            self._renames[key] = new_name.strip()
            favorites_store.save_renames(self._renames)
            self._refresh_favorite_label(key)

    def _restore_favorite_name(self, key: tuple[str, str]):
        if key in self._renames:
            del self._renames[key]
            favorites_store.save_renames(self._renames)
            self._refresh_favorite_label(key)

    def _refresh_favorite_label(self, key: tuple[str, str]):
        msg_type, fname = key
        display_name = self._renames.get(key, fname)
        for item in self._leaf_items.get(key, []):
            if item.treeWidget() is self.favorites_tree:
                item.setText(0, display_name)

    def _clear_favorites(self):
        for key in list(self._favorites):
            self._on_star_toggled(False, key)
