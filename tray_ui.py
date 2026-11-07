"""Small Windows system-tray interface for an otherwise unchanged EQ window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

ICON_YELLOW = QColor("#ffff00")
ICON_GREY = QColor("#888888")


def build_tray_icon(enabled: bool) -> QIcon:
    """Render an icon in memory, without shipping or downloading font assets."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#252525"), 5))
    for x in (13, 32, 51):
        painter.drawLine(x, 7, x, 57)
    painter.setPen(QPen(ICON_YELLOW if enabled else ICON_GREY, 5))
    painter.setBrush(QColor("#252525"))
    for x, y in ((13, 43), (32, 20), (51, 34)):
        painter.drawEllipse(x - 7, y - 7, 14, 14)
    painter.end()
    return QIcon(pixmap)


class TrayController:
    """The OS owns the notification area; Qt supplies the icon and its menu."""

    def __init__(self, window):
        self.window = window
        self.menu = QMenu(window)
        self.menu.setStyleSheet("""
            QMenu { background: #272727; color: #eeeeee; border: 1px solid #555; }
            QMenu::item { padding: 6px 18px; }
            QMenu::item:selected { background: #3b3b3b; color: #ffff00; }
            QMenu::item:disabled { color: #777; }
        """)
        self.open_action = self.menu.addAction("Показать эквалайзер")
        self.open_action.triggered.connect(window.show_window)
        self.menu.addSeparator()
        self.power_action = self.menu.addAction("Эквалайзер включён")
        self.power_action.setCheckable(True)
        self.power_action.toggled.connect(self._toggle)
        self.presets_menu = self.menu.addMenu("Выбрать пресет")
        self.presets_menu.aboutToShow.connect(self._populate_presets)
        self.menu.addSeparator()
        self.undo_action = self.menu.addAction("Отменить  Ctrl+Z")
        self.undo_action.triggered.connect(window.undo_edit)
        self.redo_action = self.menu.addAction("Повторить  Ctrl+Y")
        self.redo_action.triggered.connect(window.redo_edit)
        self.menu.addSeparator()
        self.configure_action = self.menu.addAction("Настроить аудиоустройство…")
        self.configure_action.triggered.connect(self._configure)
        self.menu.addSeparator()
        self.exit_action = self.menu.addAction("Выход (отключить эквалайзер)")
        self.exit_action.triggered.connect(window.request_exit)

        self.icon = QSystemTrayIcon(window)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        self.menu.aboutToShow.connect(self.refresh)
        self.refresh()
        self.icon.show()

    def _on_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self.window.show_window()

    def _toggle(self, checked):
        self.window.switch.set_checked(checked)
        self.window.toggle(checked)

    def _configure(self):
        self.window.show_window()
        self.window.handle_setup_button()

    def _populate_presets(self):
        menu = self.presets_menu
        menu.clear()
        for index in range(self.window.preset.count()):
            identifier = self.window.preset.itemData(index)
            if identifier is None:  # separator
                continue
            label = self.window.preset.itemText(index)
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(identifier == self.window.settings.preset_id)
            action.triggered.connect(
                lambda checked=False, key=identifier: self.select_preset(key)
            )

    def select_preset(self, identifier: str):
        if self.window.preset_dirty:
            # The Save / Discard / Cancel prompt needs to be visible.
            self.window.show_window()
        index = self.window.preset.findData(identifier)
        if index >= 0:
            self.window.preset.setCurrentIndex(index)
        self.refresh()

    def refresh(self):
        enabled = self.window.settings.enabled
        self.power_action.blockSignals(True)
        self.power_action.setChecked(enabled)
        self.power_action.setText("Эквалайзер включён" if enabled else "Эквалайзер выключен")
        self.power_action.blockSignals(False)
        self.undo_action.setEnabled(self.window.history.can_undo)
        self.redo_action.setEnabled(self.window.history.can_redo)
        self.icon.setIcon(build_tray_icon(enabled))
        self.icon.setToolTip("Yandex Music EQ — " + ("включён" if enabled else "выключен"))

    def notify_hidden(self):
        self.icon.showMessage(
            "Yandex Music EQ",
            "Окно скрыто. Эквалайзер продолжает работать. "
            "Для полного выхода используйте «Выход» в меню значка.",
            QSystemTrayIcon.MessageIcon.Information,
            3500,
        )

    def hide(self):
        self.icon.hide()
