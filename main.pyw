"""Minimal Windows GUI modeled after the Yandex Music equalizer controls."""

from __future__ import annotations

import ctypes
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QProcess, QThread
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget, QPlainTextEdit,
    QToolButton, QMenu, QInputDialog, QFileDialog, QSystemTrayIcon,
)

import apo
import installer
import device_status
import user_presets as profiles
import lifecycle
from single_instance import ActivationEvent, InstanceError, WindowsInstanceMutex, notify_running_instance
from tray_ui import TrayController
from history import AudioState, EditHistory
from equalizer import (
    INTENSITIES, SETTINGS_FILE, Settings, load_custom, load_library,
    load_settings, preset_settings, save_settings,
)

BG = QColor("#1a1a1a")
MUTED = QColor("#898989")
RAIL = QColor("#353535")
YELLOW = QColor("#ffff00")
FREQUENCY_LABELS = ("60", "170", "310", "600", "1k", "3k", "6k", "12k", "14k", "16k")
INTENSITY_LABELS = {0.25: "×¼", 0.5: "×½", 1.0: "×1", 2.0: "×2", 4.0: "×4"}


DIALOG_STYLE = """
    QMessageBox { background-color: #1a1a1a; }
    QMessageBox QLabel {
        color: #ededed; background-color: transparent;
        font-family: 'Segoe UI'; font-size: 13px;
    }
    QMessageBox QPushButton {
        color: #ededed; background-color: #303030;
        border: 1px solid #606060; border-radius: 6px;
        min-width: 72px; padding: 7px 14px;
        font-family: 'Segoe UI'; font-size: 12px; text-align: center;
    }
    QMessageBox QPushButton:hover, QMessageBox QPushButton:focus {
        border-color: #ffff00;
    }
    QMessageBox QPushButton:default { border-color: #ffff00; }
"""


def make_dialog(parent: QWidget, title: str, message: str, icon: QMessageBox.Icon) -> QMessageBox:
    """Use an explicit dialog palette; main-window label styles must not leak in."""
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(title)
    dialog.setTextFormat(Qt.TextFormat.PlainText)
    dialog.setText(message)
    dialog.setIcon(icon)
    dialog.setStyleSheet(DIALOG_STYLE)
    return dialog


class BandSlider(QWidget):
    value_changed = Signal(float)
    edit_started = Signal()
    edit_finished = Signal()

    def __init__(self, label: str, minimum: float, maximum: float, value: float, width: int = 31):
        super().__init__()
        self.label = label
        self.minimum, self.maximum = minimum, maximum
        self.value = value
        self.setFixedSize(width, 206)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{label}: {value:.1f}")

    def y_for(self, value: float) -> float:
        return 12 + (self.maximum - value) / (self.maximum - self.minimum) * 157

    def set_value(self, value: float, emit: bool = False):
        value = round(max(self.minimum, min(self.maximum, value)), 1)
        if value != self.value:
            self.value = value
            self.setToolTip(f"{self.label}: {value:.1f}")
            self.update()
            if emit:
                self.value_changed.emit(value)

    def _from_y(self, y: float):
        value = self.maximum - (max(12, min(169, y)) - 12) / 157 * (self.maximum - self.minimum)
        self.set_value(value, emit=True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.edit_started.emit()
            self._from_y(event.position().y())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.edit_finished.emit()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._from_y(event.position().y())
            event.accept()

    def wheelEvent(self, event):
        direction = 1 if event.angleDelta().y() > 0 else -1
        self.set_value(self.value + .1 * direction, emit=True)
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = self.width() / 2
        painter.setPen(QPen(RAIL, 1.25))
        painter.drawLine(round(x), 12, round(x), 169)
        painter.drawLine(round(x - 5), round(self.y_for((self.minimum + self.maximum) / 2)),
                         round(x + 5), round(self.y_for((self.minimum + self.maximum) / 2)))
        painter.setPen(QPen(YELLOW, 1.0))
        painter.setBrush(BG)
        painter.drawEllipse(round(x - 8), round(self.y_for(self.value) - 8), 16, 16)
        painter.setPen(MUTED)
        font = QFont("Segoe UI", 9)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(0, 179, self.width(), 22, Qt.AlignmentFlag.AlignCenter, self.label)


class Scale(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(48, 206)

    def paintEvent(self, event):
        painter = QPainter(self)
        font = QFont("Segoe UI", 9)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(MUTED)
        for text, y in (("12dB", 9), ("0dB", 87), ("-12dB", 165)):
            painter.drawText(0, y, 48, 20, Qt.AlignmentFlag.AlignLeft, text)


class Switch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked: bool):
        super().__init__()
        self.checked = checked
        self.setFixedSize(36, 25)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Включить или выключить эквалайзер")

    def set_checked(self, checked: bool):
        self.checked = checked
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.checked = not self.checked
            self.toggled.emit(self.checked)
            self.update()
            event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(YELLOW if self.checked else QColor("#555555"))
        p.drawRoundedRect(0, 2, 36, 22, 11, 11)
        p.setBrush(QColor("#090909"))
        p.drawEllipse(19 if self.checked else 3, 5, 16, 16)


class InstallerDownloadWorker(QThread):
    progress_changed = Signal(int)
    download_ready = Signal(str)
    download_error = Signal(str)

    def run(self):
        try:
            path = installer.download_official_installer(self.progress_changed.emit)
            self.download_ready.emit(str(path))
        except (installer.InstallerError, OSError) as exc:
            self.download_error.emit(str(exc))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.library = load_library()
        try:
            self.user_presets = profiles.load_user_presets(
                frequencies=self.library["frequenciesHz"]
            )
            self.settings = load_settings(
                self.library, user_preset_ids=self.user_presets
            )
            self.custom = load_custom(self.library)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Do not overwrite an invalid file silently. The user must inspect it.
            make_dialog(
                self, "Некорректные настройки",
                f"{exc}\nЗакройте приложение и исправьте settings.json.",
                QMessageBox.Icon.Warning,
            ).exec()
            raise
        self.setWindowTitle("Yandex Music EQ — independent")
        self.setFixedSize(463, 516)
        self.setStyleSheet("""
            QMainWindow, QWidget#root { background: #1a1a1a; }
            QWidget#root QLabel { color: #dedede; font-family: 'Segoe UI'; }
            QComboBox {
                color: #e3e3e3; background: #1a1a1a; border: 1px solid #4b4b4b;
                border-radius: 24px; padding: 11px 17px; font-size: 13px; font-weight: 600;
            }
            QComboBox:hover { border-color: #777777; }
            QComboBox::drop-down { border: none; width: 28px; }
            QComboBox QAbstractItemView {
                background: #272727; color: #eeeeee; border: 1px solid #4b4b4b;
                selection-background-color: #3a3a3a; outline: 0;
            }
            QWidget#root QPushButton { background: transparent; color: #9a9a9a;
                          border: none; font-size: 11px; text-align: right; }
            QWidget#root QPushButton:hover { color: #ffff00; }
        """)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 17, 16, 12)
        layout.setSpacing(11)
        header = QHBoxLayout()
        caption = QLabel("Эквалайзер")
        caption.setStyleSheet("font-size: 16px; font-weight: 700;")
        header.addWidget(caption)
        header.addStretch(1)
        self.switch = Switch(self.settings.enabled)
        self.switch.toggled.connect(self.toggle)
        header.addWidget(self.switch)
        layout.addLayout(header)
        sliders = QHBoxLayout()
        sliders.setSpacing(0)
        self.preamp = BandSlider("уровень", .5, 1.5, self.settings.preamp_linear, width=51)
        self.preamp.value_changed.connect(self.edit_preamp)
        self.preamp.edit_started.connect(self.begin_slider_edit)
        self.preamp.edit_finished.connect(self.end_slider_edit)
        self.preamp_intensity_button = self.make_intensity_button(
            None, "предусиление", self.settings.preamp_intensity, 51,
        )
        sliders.addLayout(self.slider_column(self.preamp, self.preamp_intensity_button))
        sliders.addSpacing(7)
        sliders.addWidget(Scale(), alignment=Qt.AlignmentFlag.AlignTop)
        sliders.addStretch(1)
        self.bands = []
        self.band_intensity_buttons = []
        for index, name in enumerate(FREQUENCY_LABELS):
            slider = BandSlider(name, -12, 12, self.settings.gains_db[index])
            slider.value_changed.connect(lambda value, i=index: self.edit_band(i, value))
            slider.edit_started.connect(self.begin_slider_edit)
            slider.edit_finished.connect(self.end_slider_edit)
            button = self.make_intensity_button(
                index, f"{name} Гц", self.settings.band_intensities[index], 31,
            )
            sliders.addLayout(self.slider_column(slider, button))
            self.bands.append(slider)
            self.band_intensity_buttons.append(button)
        sliders.addStretch(1)
        layout.addLayout(sliders)
        self.preset_dirty = (
            self.settings.preset_id in self.user_presets and
            profiles.snapshot(
                self.settings, self.user_presets[self.settings.preset_id]["name"]
            ) != self.user_presets[self.settings.preset_id]
        )
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        self.preset = QComboBox()
        self.preset.setFixedHeight(52)
        self.refresh_preset_items(self.settings.preset_id)
        self.preset.currentIndexChanged.connect(self.choose_preset)
        preset_row.addWidget(self.preset, stretch=1)
        self.preset_actions = QToolButton(self)
        self.preset_actions.setText("⋯")
        self.preset_actions.setFixedSize(31, 36)
        self.preset_actions.setToolTip("Управление пользовательскими пресетами")
        self.preset_actions.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.preset_actions.setStyleSheet("""
            QToolButton { color: #dedede; background: #303030;
                border: 1px solid #5b5b5b; border-radius: 9px; font: 18px 'Segoe UI'; }
            QToolButton:hover { border-color: #ffff00; }
            QToolButton::menu-indicator { image: none; width: 0; }
        """)
        self.preset_menu = QMenu(self.preset_actions)
        self.preset_menu.setStyleSheet("""
            QMenu { color: #ededed; background: #272727; border: 1px solid #555; }
            QMenu::item { padding: 7px 16px; }
            QMenu::item:selected { background: #3d3d3d; color: #ffff00; }
            QMenu::item:disabled { color: #777777; }
        """)
        self.action_undo = self.preset_menu.addAction("Отменить\tCtrl+Z")
        self.action_undo.triggered.connect(self.undo_edit)
        self.action_redo = self.preset_menu.addAction("Повторить\tCtrl+Y")
        self.action_redo.triggered.connect(self.redo_edit)
        self.preset_menu.addSeparator()
        self.action_save = self.preset_menu.addAction("Сохранить пресет\tCtrl+S")
        self.action_save.triggered.connect(self.save_current_preset)
        self.action_save_as = self.preset_menu.addAction("Сохранить как…\tCtrl+Shift+S")
        self.action_save_as.triggered.connect(self.save_preset_as)
        self.action_rename = self.preset_menu.addAction("Переименовать…")
        self.action_rename.triggered.connect(self.rename_user_preset)
        self.action_delete = self.preset_menu.addAction("Удалить…")
        self.action_delete.triggered.connect(self.delete_user_preset)
        self.preset_menu.addSeparator()
        self.action_export = self.preset_menu.addAction("Экспортировать…\tCtrl+E")
        self.action_export.triggered.connect(self.export_current_preset)
        self.action_import = self.preset_menu.addAction("Импортировать…\tCtrl+O")
        self.action_import.triggered.connect(self.import_user_preset)
        self.preset_menu.aboutToShow.connect(self.update_preset_actions)
        self.preset_actions.setMenu(self.preset_menu)
        preset_row.addWidget(self.preset_actions)
        layout.addLayout(preset_row)
        self.history = EditHistory(capacity=100)
        self._slider_drag_before: AudioState | None = None
        self._restoring_history = False
        self.shortcuts = []
        for combination, handler in (
            ("Ctrl+Z", self.undo_edit),
            ("Ctrl+Y", self.redo_edit),
            ("Ctrl+Shift+Z", self.redo_edit),
            ("Ctrl+S", self.save_current_preset),
            ("Ctrl+Shift+S", self.save_preset_as),
            ("Ctrl+E", self.export_current_preset),
            ("Ctrl+O", self.import_user_preset),
        ):
            shortcut = QShortcut(QKeySequence(combination), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(handler)
            self.shortcuts.append(shortcut)
        self.set_preset_dirty(self.preset_dirty)
        self.update_history_actions()
        bottom = QHBoxLayout()
        self.status = QLabel()
        self.status.setStyleSheet("color: #848484; font-size: 11px;")
        bottom.addWidget(self.status)
        bottom.addStretch(1)
        self.setup_button = QPushButton("Подключить APO")
        self.setup_button.clicked.connect(self.handle_setup_button)
        bottom.addWidget(self.setup_button)
        layout.addLayout(bottom)
        self.messages = QPlainTextEdit()
        self.messages.setReadOnly(True)
        self.messages.setFixedHeight(75)
        self.messages.setPlaceholderText("Сообщения подключения и ошибки аудиодвижка")
        self.messages.setMaximumBlockCount(100)
        self.messages.setStyleSheet("""
            QPlainTextEdit { color: #c8c8c8; background: #252525;
                             border: 1px solid #3c3c3c; border-radius: 7px;
                             padding: 6px; font-size: 11px; }
        """)
        layout.addWidget(self.messages)
        layout.addStretch(1)
        self.write_timer = QTimer(self)
        self.write_timer.setSingleShot(True)
        self.write_timer.timeout.connect(self.commit_settings)
        self.connected = False
        self.device_check = None
        self.last_device_key = None
        self.setup_process = None
        self.install_worker = None
        self.connection_timer = QTimer(self)
        self.connection_timer.timeout.connect(self.check_connection)
        self.connection_timer.start(2000)
        self.check_connection()
        self._exit_completed = False
        self._tray_tip_shown = False
        self.tray_controller = None
        app = QApplication.instance()
        if app.platformName().lower() != "offscreen" and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_controller = TrayController(self)
            app.setQuitOnLastWindowClosed(False)
        QTimer.singleShot(250, self.startup_check)

    def show_window(self):
        """Show the one existing window instead of creating another process."""
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def refresh_tray(self):
        if self.tray_controller is not None:
            self.tray_controller.refresh()

    def request_exit(self):
        """Quit deliberately only after Equalizer APO has been disabled."""
        if self._exit_completed:
            return True
        if self.install_worker is not None or self.setup_process is not None:
            self.show_window()
            make_dialog(
                self, "Завершение ещё недоступно",
                "Сначала дождитесь завершения установки или настройки Equalizer APO.",
                QMessageBox.Icon.Warning,
            ).exec()
            return False
        self.write_timer.stop()
        self.connection_timer.stop()
        try:
            disabled = lifecycle.disable_and_persist(
                self.settings, self.custom, self.library,
            )
        except (lifecycle.ShutdownError, OSError, ValueError) as exc:
            self.connection_timer.start(2000)
            self.report(str(exc))
            self.show_window()
            make_dialog(
                self, "Эквалайзер не выключен",
                str(exc) + "\n\nПрограмма останется запущенной. "
                "Исправьте доступ к Equalizer APO и повторите выход.",
                QMessageBox.Icon.Warning,
            ).exec()
            return False
        self.settings = disabled
        self.switch.set_checked(False)
        self._exit_completed = True
        self.refresh_tray()
        if self.tray_controller is not None:
            self.tray_controller.hide()
        QTimer.singleShot(0, QApplication.instance().quit)
        return True

    def best_effort_stop_on_quit(self):
        """Handles unexpected normal Qt quit; hard kills cannot be intercepted."""
        if self._exit_completed:
            return
        try:
            self.settings = lifecycle.disable_and_persist(
                self.settings, self.custom, self.library,
            )
            self._exit_completed = True
        except (lifecycle.ShutdownError, OSError, ValueError) as exc:
            self.report("Не удалось отключить APO перед выходом: " + str(exc))

    def refresh_preset_items(self, select_id: str):
        """Rebuild the list without changing the active audio settings."""
        was_blocked = self.preset.blockSignals(True)
        try:
            self.preset.clear()
            self.preset.addItem("Своя настройка", "CUSTOM")
            self.preset.addItem("По умолчанию", "DEFAULT")
            for preset_id in self.library["presets"]:
                if preset_id not in ("CUSTOM", "DEFAULT"):
                    self.preset.addItem(preset_id.replace("_", " ").title(), preset_id)
            if self.user_presets:
                self.preset.insertSeparator(self.preset.count())
                for preset_id, record in self.user_presets.items():
                    self.preset.addItem("★ " + record["name"], preset_id)
            index = self.preset.findData(select_id)
            self.preset.setCurrentIndex(index if index >= 0 else self.preset.findData("CUSTOM"))
        finally:
            self.preset.blockSignals(was_blocked)

    def _current_user_id(self) -> str | None:
        selected = self.settings.preset_id
        return selected if selected in self.user_presets else None

    def set_preset_dirty(self, dirty: bool):
        """Show unsaved edits unobtrusively without a separate Save button."""
        self.preset_dirty = dirty
        selected = self._current_user_id()
        self.action_save.setText(
            ("Сохранить изменения" if selected else "Сохранить пресет")
            + "\tCtrl+S"
        )
        self.preset_actions.setToolTip(
            "Есть несохранённые изменения профиля" if dirty
            else "Управление пользовательскими пресетами"
        )
        if selected:
            index = self.preset.findData(selected)
            if index >= 0:
                name = self.user_presets[selected]["name"]
                self.preset.setItemText(index, "★ " + name + (" *" if dirty else ""))

    def sync_preset_dirty(self):
        selected = self._current_user_id()
        dirty = bool(
            selected and profiles.snapshot(
                self.settings, self.user_presets[selected]["name"]
            ) != self.user_presets[selected]
        )
        self.set_preset_dirty(dirty)

    def update_preset_actions(self):
        available = self._current_user_id() is not None
        for action in (self.action_rename, self.action_delete):
            action.setEnabled(available)
        self.update_history_actions()

    def audio_state(self) -> AudioState:
        return AudioState(self.settings, self.custom)

    def update_history_actions(self):
        self.action_undo.setEnabled(self.history.can_undo)
        self.action_redo.setEnabled(self.history.can_redo)

    def record_audio_edit(self, before: AudioState):
        if self._restoring_history or self._slider_drag_before is not None:
            return
        self.history.record(before, self.audio_state())
        self.update_history_actions()

    def begin_slider_edit(self):
        if self._slider_drag_before is None:
            self._slider_drag_before = self.audio_state()

    def end_slider_edit(self):
        if self._slider_drag_before is None:
            return
        before = self._slider_drag_before
        self._slider_drag_before = None
        self.history.record(before, self.audio_state())
        self.update_history_actions()

    def restore_audio_state(self, state: AudioState):
        """Restore the entire live sound without creating another history entry."""
        self._restoring_history = True
        try:
            self.settings, self.custom = state.settings, state.custom
            self.switch.set_checked(self.settings.enabled)
            self.preamp.set_value(self.settings.preamp_linear)
            for slider, gain in zip(self.bands, self.settings.gains_db):
                slider.set_value(gain)
            self.reflect_intensity_widgets()
            self.refresh_preset_items(self.settings.preset_id)
            self.sync_preset_dirty()
        finally:
            self._restoring_history = False
        self.schedule_write()
        self.refresh_tray()

    def undo_edit(self):
        if self._slider_drag_before is not None:
            self.end_slider_edit()
        state = self.history.undo(self.audio_state())
        if state is not None:
            self.restore_audio_state(state)
        self.update_history_actions()

    def redo_edit(self):
        if self._slider_drag_before is not None:
            self.end_slider_edit()
        state = self.history.redo(self.audio_state())
        if state is not None:
            self.restore_audio_state(state)
        self.update_history_actions()

    def _preset_error(self, title: str, exception: Exception):
        message = str(exception)
        self.report(f"{title}: {message}")
        make_dialog(self, title, message, QMessageBox.Icon.Warning).exec()

    def _ask_preset_name(self, title: str, initial: str) -> str | None:
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText("Название пресета:")
        dialog.setTextValue(initial)
        dialog.setOkButtonText("Сохранить")
        dialog.setCancelButtonText("Отмена")
        dialog.setStyleSheet("""
            QInputDialog { background: #1a1a1a; }
            QInputDialog QLabel { color: #eeeeee; font: 12px 'Segoe UI'; }
            QInputDialog QLineEdit {
                color: #eeeeee; background: #292929;
                border: 1px solid #666666; padding: 6px;
            }
            QInputDialog QPushButton {
                color: #eeeeee; background: #323232; border: 1px solid #666666;
                border-radius: 5px; padding: 5px 12px;
            }
        """)
        if dialog.exec() != QInputDialog.DialogCode.Accepted:
            return None
        return dialog.textValue()

    def _write_profiles(self, updated: dict[str, dict]) -> bool:
        try:
            profiles.save_user_presets(
                updated, frequencies=self.library["frequenciesHz"]
            )
        except (OSError, ValueError) as exc:
            self._preset_error("Не удалось сохранить пресеты", exc)
            return False
        self.user_presets = updated
        return True

    def save_current_preset(self):
        if self._current_user_id():
            self.update_user_preset()
        else:
            self.save_preset_as()

    def save_preset_as(self):
        selected = self._current_user_id()
        default = self.user_presets[selected]["name"] + " (копия)" if selected else "Мой пресет"
        name = self._ask_preset_name("Сохранить новый пресет", default)
        if name is None:
            return False
        try:
            name = profiles.ensure_unique_name(self.user_presets, name)
            record = profiles.snapshot(self.settings, name)
            new_id = profiles.new_preset_id()
            updated = dict(self.user_presets)
            if len(updated) >= profiles.MAX_PRESETS:
                raise profiles.UserPresetError("Достигнут предел в 200 пользовательских пресетов")
            updated[new_id] = record
        except (ValueError, TypeError) as exc:
            self._preset_error("Некорректный пресет", exc)
            return False
        if not self._write_profiles(updated):
            return False
        before = self.audio_state()
        self.settings = replace(self.settings, preset_id=new_id)
        self.refresh_preset_items(new_id)
        self.set_preset_dirty(False)
        self.record_audio_edit(before)
        self.commit_settings()
        self.report(f"Сохранён пользовательский пресет «{name}» со всеми 11 множителями.")
        return True

    def update_user_preset(self):
        preset_id = self._current_user_id()
        if preset_id is None:
            self.report("Выберите пользовательский пресет или используйте «Сохранить как…».")
            return False
        name = self.user_presets[preset_id]["name"]
        try:
            record = profiles.snapshot(self.settings, name)
        except (ValueError, TypeError) as exc:
            self._preset_error("Некорректные параметры пресета", exc)
            return False
        updated = dict(self.user_presets)
        updated[preset_id] = record
        if not self._write_profiles(updated):
            return False
        self.set_preset_dirty(False)
        self.commit_settings()
        self.report(f"Пресет «{name}» обновлён.")
        return True

    def rename_user_preset(self):
        preset_id = self._current_user_id()
        if preset_id is None:
            return
        current = self.user_presets[preset_id]
        name = self._ask_preset_name("Переименовать пресет", current["name"])
        if name is None:
            return
        try:
            name = profiles.ensure_unique_name(self.user_presets, name, ignore_id=preset_id)
        except ValueError as exc:
            self._preset_error("Не удалось переименовать пресет", exc)
            return
        updated = dict(self.user_presets)
        updated[preset_id] = {**current, "name": name}
        if self._write_profiles(updated):
            self.refresh_preset_items(preset_id)
            self.report(f"Пресет переименован в «{name}».")

    def delete_user_preset(self):
        preset_id = self._current_user_id()
        if preset_id is None:
            return
        name = self.user_presets[preset_id]["name"]
        dialog = make_dialog(
            self, "Удалить пресет?",
            f"Удалить пользовательский пресет «{name}»?\n"
            "Текущие настройки звука останутся в режиме «Своя настройка».",
            QMessageBox.Icon.Warning,
        )
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Удалить")
        dialog.button(QMessageBox.StandardButton.No).setText("Отмена")
        if dialog.exec() != QMessageBox.StandardButton.Yes:
            return
        updated = dict(self.user_presets)
        del updated[preset_id]
        if not self._write_profiles(updated):
            return
        self.settings = replace(self.settings, preset_id="CUSTOM")
        self.custom = replace(self.settings, enabled=False)
        self.refresh_preset_items("CUSTOM")
        self.set_preset_dirty(False)
        # A deleted profile may be referenced by older snapshots. Treat file
        # deletion as an undo-history boundary, not an undoable DSP edit.
        self.history.clear()
        self.update_history_actions()
        self.commit_settings()
        self.report(f"Пресет «{name}» удалён. Текущий звук сохранён.")

    def export_current_preset(self):
        preset_id = self._current_user_id()
        if preset_id:
            name = self.user_presets[preset_id]["name"]
        else:
            name = self.preset.currentText() or "Мой пресет"
        safe_name = "".join(
            char for char in name if char not in '\\/:*?"<>|' and ord(char) >= 32
        )[:48].strip(" .") or "preset"
        filename, _ = QFileDialog.getSaveFileName(
            self, "Экспортировать настройку эквалайзера",
            str(Path(__file__).resolve().parent / f"{safe_name}.yeq.json"),
            "Пресет эквалайзера (*.yeq.json);;JSON (*.json)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".json":
            path = path.with_name(path.name + ".yeq.json")
        try:
            profiles.export_preset(profiles.snapshot(self.settings, name), path)
        except (OSError, ValueError, TypeError) as exc:
            self._preset_error("Ошибка экспорта", exc)
            return
        self.report(f"Пресет экспортирован: {path}")

    def import_user_preset(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Импортировать пресет эквалайзера",
            str(Path(__file__).resolve().parent),
            "Пресет эквалайзера (*.yeq.json *.json)",
        )
        if not filename:
            return
        try:
            record = profiles.import_preset(Path(filename))
            name = record["name"]
            try:
                profiles.ensure_unique_name(self.user_presets, name)
            except profiles.UserPresetError:
                requested = self._ask_preset_name(
                    "Такое название уже есть — укажите новое", name + " (импорт)"
                )
                if requested is None:
                    return
                name = profiles.ensure_unique_name(self.user_presets, requested)
                record = {**record, "name": name}
            updated = dict(self.user_presets)
            if len(updated) >= profiles.MAX_PRESETS:
                raise profiles.UserPresetError("Достигнут предел в 200 пользовательских пресетов")
            new_id = profiles.new_preset_id()
            updated[new_id] = record
        except (OSError, ValueError, TypeError) as exc:
            self._preset_error("Ошибка импорта", exc)
            return
        if not self._write_profiles(updated):
            return
        # Import only registers a preset. Do not unexpectedly replace live audio.
        self.refresh_preset_items(self.settings.preset_id)
        self.report(f"Пресет «{name}» импортирован. Выберите его в списке для применения.")

    def reflect_intensity_widgets(self):
        pairs = [(self.preamp_intensity_button, self.settings.preamp_intensity, "предусиление")]
        pairs.extend(
            (button, value, f"{FREQUENCY_LABELS[index]} Гц")
            for index, (button, value) in enumerate(
                zip(self.band_intensity_buttons, self.settings.band_intensities)
            )
        )
        for button, value, label in pairs:
            button.setText(INTENSITY_LABELS[value])
            button.setToolTip(f"Интенсивность {label}: ×{value:g}. Нажмите для выбора.")
            for action in button.menu().actions():
                action.setChecked(action.data() == value)

    def report(self, message: str):
        """Show diagnostics in the window rather than in a hidden console."""
        if message and (not self.messages.toPlainText().splitlines() or
                        self.messages.toPlainText().splitlines()[-1] != message):
            self.messages.appendPlainText(message)

    def check_connection(self):
        # A working Include does NOT mean APO was installed on the playback
        # endpoint. Keep these two independent states visible.
        connected, reason = apo.connection_status()
        if connected != self.connected:
            self.connected = connected
            if connected:
                self.schedule_write()
        self.device_check = device_status.inspect_default_output() if connected else None
        installed = apo.config_directory() is not None
        if not installed:
            label = "APO: не установлен"
        elif not connected:
            label = "APO: файл не подключён"
        elif self.device_check.state == "missing":
            label = "APO: выберите устройство"
        elif self.device_check.state == "registered":
            label = "APO: регистрация найдена"
        else:
            label = "APO: устройство не проверено"
        self.status.setText(label)
        self.status.setToolTip(self.device_check.reason if self.device_check else reason)
        if self.device_check:
            key = (self.device_check.state, self.device_check.device_name,
                   self.device_check.reason)
            if key != self.last_device_key:
                self.last_device_key = key
                self.report(self.device_check.reason)
        else:
            self.last_device_key = None
        busy = self.setup_process is not None or self.install_worker is not None
        # Never hide the action after connecting config.txt: the user may
        # have dismissed Device Selector without selecting an endpoint.
        self.setup_button.setVisible(os.name == "nt")
        self.setup_button.setEnabled(not busy)
        if not busy:
            self.setup_button.setText(
                "Установить APO" if not installed else
                "Подключить APO" if not connected else "Настроить устройство"
            )

    def startup_check(self):
        if os.name != "nt":
            self.report("Системная обработка доступна только в Windows")
            return
        if apo.config_directory() is None:
            self.report("Equalizer APO не обнаружен. Можно загрузить официальный установщик после подтверждения.")
            self.offer_install()
            return
        if not self.connected:
            self.report(apo.connection_status()[1])
            self.report("Для подключения Equalizer APO требуется однократное подтверждение UAC")
            self.setup_apo()
            return
        # The include being present does not imply permission to update it.
        # Test the actual write without claiming that audio is already processed.
        try:
            if not apo.apply(self.settings, self.library):
                raise OSError("Подключение Include не найдено")
        except OSError as exc:
            self.report(f"Нет доступа к конфигурации APO: {exc}")
            self.setup_apo()
            return
        self.check_connection()
        self.report("Файл фильтров обновлён; проверка регистрации устройства выполняется отдельно.")
        if self.device_check and self.device_check.state != "registered":
            self.report("Нажмите «Настроить устройство», выберите текущий выход и подтвердите OK в Device Selector.")

    def schedule_write(self):
        self.write_timer.start(160)

    def toggle(self, enabled: bool):
        before = self.audio_state()
        self.settings = replace(self.settings, enabled=enabled)
        self.record_audio_edit(before)
        self.schedule_write()
        self.refresh_tray()

    @staticmethod
    def slider_column(slider: BandSlider, control: QToolButton) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(slider)
        column.addWidget(control, alignment=Qt.AlignmentFlag.AlignHCenter)
        return column

    def make_intensity_button(self, band: int | None, name: str,
                              factor: float, width: int) -> QToolButton:
        """Compact multiplier directly beneath its own gain/band slider."""
        button = QToolButton(self)
        button.setFixedSize(width, 25)
        button.setText(INTENSITY_LABELS[factor])
        button.setAccessibleName(f"Интенсивность: {name}")
        button.setToolTip(f"Интенсивность {name}: ×{factor:g}. Нажмите для выбора.")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setStyleSheet("""
            QToolButton {
                color: #dedede; background: #292929; font: 9px 'Segoe UI';
                border: 1px solid #494949; border-radius: 5px; padding: 1px;
            }
            QToolButton:hover { border-color: #ffff00; }
            QToolButton::menu-indicator { image: none; width: 0px; }
        """)
        menu = QMenu(button)
        menu.setMinimumWidth(102)
        menu.setStyleSheet("""
            QMenu { color: #eeeeee; background: #282828; border: 1px solid #555; }
            QMenu::item { padding: 6px 16px; }
            QMenu::item:selected { color: #ffff00; background: #3a3a3a; }
        """)
        for mode in INTENSITIES:
            action = menu.addAction(f"×{mode:g}")
            action.setData(mode)
            action.setCheckable(True)
            action.setChecked(mode == factor)
            action.triggered.connect(
                lambda checked=False, value=mode, target=band, widget=button:
                self.change_intensity(target, value, widget)
            )
        button.setMenu(menu)
        return button

    def change_intensity(self, band: int | None, value: float,
                         button: QToolButton):
        before = self.audio_state()
        if band is None:
            self.settings = replace(self.settings, preamp_intensity=value)
            name = "предусиления"
        else:
            multipliers = list(self.settings.band_intensities)
            multipliers[band] = value
            self.settings = replace(self.settings, band_intensities=tuple(multipliers))
            name = f"полосы {FREQUENCY_LABELS[band]}"
        button.setText(INTENSITY_LABELS[value])
        button.setToolTip(f"Интенсивность {name}: ×{value:g}. Нажмите для выбора.")
        for action in button.menu().actions():
            action.setChecked(action.data() == value)
        if value >= 2:
            self.report(f"×{value:g} для {name}: последовательное усиление. Возможен клиппинг.")
        elif value < 1:
            self.report(f"×{value:g} для {name}: приближённое ослабление эффекта.")
        # An edited user preset must be explicitly saved before replacing it.
        self.sync_preset_dirty()
        self.record_audio_edit(before)
        self.schedule_write()

    def mark_edited(self):
        if not self._current_user_id():
            self.settings = replace(self.settings, preset_id="CUSTOM")
            self.custom = replace(self.settings, enabled=False)
            self.mark_custom()
        self.sync_preset_dirty()
        self.schedule_write()

    def edit_preamp(self, value: float):
        before = self.audio_state()
        self.settings = replace(self.settings, preamp_linear=value)
        self.mark_edited()
        self.record_audio_edit(before)

    def edit_band(self, index: int, value: float):
        before = self.audio_state()
        gains = list(self.settings.gains_db)
        gains[index] = value
        self.settings = replace(self.settings, gains_db=tuple(gains))
        self.mark_edited()
        self.record_audio_edit(before)

    def mark_custom(self):
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(self.preset.findData("CUSTOM"))
        self.preset.blockSignals(False)

    def choose_preset(self, index: int):
        name = self.preset.itemData(index)
        if not name or name == self.settings.preset_id:
            return
        before = self.audio_state()
        if self.preset_dirty and self._current_user_id():
            current = self.user_presets[self.settings.preset_id]["name"]
            dialog = make_dialog(
                self, "Несохранённые изменения",
                f"Пресет «{current}» изменён. Сохранить изменения перед переключением?",
                QMessageBox.Icon.Question,
            )
            dialog.setStandardButtons(
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel
            )
            dialog.setDefaultButton(QMessageBox.StandardButton.Save)
            dialog.button(QMessageBox.StandardButton.Save).setText("Сохранить")
            dialog.button(QMessageBox.StandardButton.Discard).setText("Не сохранять")
            dialog.button(QMessageBox.StandardButton.Cancel).setText("Отмена")
            answer = dialog.exec()
            if answer == QMessageBox.StandardButton.Save:
                if not self.update_user_preset():
                    self.refresh_preset_items(self.settings.preset_id)
                    return
            elif answer != QMessageBox.StandardButton.Discard:
                self.refresh_preset_items(self.settings.preset_id)
                return
        if name == "CUSTOM":
            self.settings = replace(
                self.custom, enabled=self.settings.enabled,
                preamp_intensity=self.settings.preamp_intensity,
                band_intensities=self.settings.band_intensities,
            )
        elif name in self.user_presets:
            # Restore the whole saved sound, including all 11 multipliers.
            self.settings = profiles.preset_settings(
                self.user_presets[name], name, self.settings.enabled,
            )
        else:
            # Built-in presets keep the user's current multiplier choices.
            self.settings = replace(
                preset_settings(self.library, name, enabled=self.settings.enabled),
                preamp_intensity=self.settings.preamp_intensity,
                band_intensities=self.settings.band_intensities,
            )
        self.preamp.set_value(self.settings.preamp_linear)
        for widget, value in zip(self.bands, self.settings.gains_db):
            widget.set_value(value)
        self.reflect_intensity_widgets()
        self.sync_preset_dirty()
        self.record_audio_edit(before)
        self.schedule_write()
        self.refresh_tray()

    def commit_settings(self):
        try:
            save_settings(self.settings, SETTINGS_FILE, self.custom)
        except (OSError, ValueError) as exc:
            self.report(f"Ошибка сохранения settings.json: {exc}")
            return
        if not self.connected:
            return
        try:
            if not apo.apply(self.settings, self.library):
                self.connected = False
                self.report("APO перестал быть подключён: проверьте config.txt и кнопку «Подключить APO»")
        except (OSError, ValueError) as exc:
            self.report(f"Эквализация не применяется: ошибка записи в APO: {exc}")

    def handle_setup_button(self):
        if apo.config_directory() is None:
            self.offer_install()
        elif not self.connected:
            self.setup_apo()
        else:
            self.open_device_selector()

    def open_device_selector(self):
        """Launch the vendor GUI, never edit endpoint registry values ourselves."""
        folder = apo.config_directory()
        if os.name != "nt" or folder is None:
            self.report("Equalizer APO не установлен")
            return
        selector = next((
            path for path in (
                folder.parent / "DeviceSelector.exe",
                folder.parent / "Configurator.exe",
            ) if path.is_file()
        ), None)
        if selector is None:
            self.report("Не найден DeviceSelector.exe или Configurator.exe в папке Equalizer APO.")
            return
        try:
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            shell32.ShellExecuteW.argtypes = [
                ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int,
            ]
            shell32.ShellExecuteW.restype = ctypes.c_void_p
            result = shell32.ShellExecuteW(
                None, "runas", str(selector), None, str(selector.parent), 1
            )
            if not result or result <= 32:
                if ctypes.get_last_error() == 1223:
                    self.report("Запуск Device Selector отменён в UAC")
                else:
                    self.report(f"Не удалось открыть Device Selector (код {result})")
                return
            name = self.device_check.device_name if self.device_check else "устройство вывода"
            self.report(f"В Device Selector отметьте «{name}», нажмите OK и перезагрузите Windows при запросе.")
        except (OSError, ValueError) as exc:
            self.report(f"Ошибка запуска Device Selector: {exc}")

    def offer_install(self):
        if os.name != "nt" or self.install_worker is not None or self.setup_process is not None:
            return
        if not installer.supported_architecture():
            self.report("Автоустановка доступна только для Windows x64: " + installer.OFFICIAL_PAGE)
            return
        dialog = make_dialog(
            self, "Установить Equalizer APO?",
            "Для обработки системного звука требуется Equalizer APO.\n\n"
            "Скачать официальный установщик версии 1.4.2 с SourceForge (около 12 МБ), "
            "проверить SHA-256 и запустить мастер установки?\n\n"
            "Windows запросит права администратора. В мастере нужно выбрать "
            "аудиоустройство и затем перезагрузить Windows.",
            QMessageBox.Icon.Question,
        )
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.Yes)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Установить")
        dialog.button(QMessageBox.StandardButton.No).setText("Отмена")
        answer = dialog.exec()
        if answer != QMessageBox.StandardButton.Yes:
            self.report("Установка отменена. Нажмите «Установить APO», чтобы повторить.")
            return
        self.install_worker = InstallerDownloadWorker(self)
        self.install_worker.progress_changed.connect(self.install_progress)
        self.install_worker.download_ready.connect(self.install_downloaded)
        self.install_worker.download_error.connect(self.install_failed)
        self.install_worker.finished.connect(self.install_thread_finished)
        self.report("Загрузка Equalizer APO 1.4.2 с SourceForge с обязательной проверкой SHA-256...")
        self.check_connection()
        self.setup_button.setText("Загрузка...")
        self.install_worker.start()

    def install_progress(self, percent: int):
        self.setup_button.setText(f"Загрузка {percent}%")

    def install_downloaded(self, path: str):
        self.report("Проверка SHA-256 пройдена. Запускаю официальный мастер установки...")
        try:
            installer.launch_verified_installer(Path(path))
        except installer.InstallerError as exc:
            self.report(f"Установка не запущена: {exc}")
            return
        self.report("Мастер Equalizer APO запущен. Выберите нужное устройство вывода в Device Selector.")
        self.report("После установки и перезагрузки Windows снова откройте main.pyw: подключение конфигурации выполнится автоматически.")

    def install_failed(self, message: str):
        self.report("Загрузка не удалась: " + message)
        self.report("Официальная страница для ручной установки: " + installer.OFFICIAL_PAGE)

    def install_thread_finished(self):
        worker = self.install_worker
        self.install_worker = None
        if worker is not None:
            worker.deleteLater()
        self.check_connection()

    def setup_apo(self):
        if os.name != "nt":
            self.report("Equalizer APO работает только в Windows")
            return
        if self.setup_process is not None:
            return
        if apo.config_directory() is None:
            self.report("Не найдена установка Equalizer APO. Установите его и проверьте Configurator")
            return
        interpreter = Path(sys.executable)
        if interpreter.name.lower() == "pythonw.exe":
            candidate = interpreter.with_name("python.exe")
            if candidate.exists():
                interpreter = candidate
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.setProgram(str(interpreter))
        process.setArguments([str(Path(__file__).with_name("setup_apo.py"))])
        process.finished.connect(self.setup_finished)
        process.errorOccurred.connect(self.setup_process_error)
        self.setup_process = process
        self.setup_button.setEnabled(False)
        self.setup_button.setText("Подключение...")
        self.report("Настройка Equalizer APO: подтвердите запрос прав администратора Windows...")
        process.start()

    def setup_process_error(self, error):
        if self.setup_process is not None:
            self.report(f"Не удалось запустить установщик APO: {self.setup_process.errorString()}")

    def setup_finished(self, exit_code, exit_status):
        process = self.setup_process
        if process is None:
            return
        output = bytes(process.readAllStandardOutput()).decode("utf-8", "replace").strip()
        message = output or f"Установщик APO завершился без отчёта (код {exit_code})"
        success = False
        for line in reversed(output.splitlines()):
            try:
                result = json.loads(line)
                message = result.get("message", message)
                success = bool(result.get("ok")) and exit_code == 0
                break
            except (ValueError, TypeError, AttributeError):
                continue
        self.setup_process = None
        process.deleteLater()
        self.setup_button.setEnabled(True)
        self.setup_button.setText("Подключить APO")
        self.check_connection()
        self.report(message)
        if success and self.connected:
            self.commit_settings()
            self.report("Конфигурация подключена; это не подтверждает регистрацию APO на текущем устройстве.")
            if self.device_check and self.device_check.state != "registered":
                self.report("Нажмите «Настроить устройство» и завершите выбор устройства в Device Selector.")
        elif success:
            self.report("Установщик сообщил об успехе, но Include не обнаружен. Проверьте config.txt")

    def closeEvent(self, event):
        if self._exit_completed:
            event.accept()
            return
        if self.tray_controller is not None and self.tray_controller.icon.isVisible():
            # The APO keeps processing while the GUI is hidden.
            if self.write_timer.isActive():
                self.write_timer.stop()
                self.commit_settings()
            event.ignore()
            self.hide()
            if not self._tray_tip_shown:
                self._tray_tip_shown = True
                self.tray_controller.notify_hidden()
            return
        # When no system tray is available, closing the sole window must
        # perform a proper shutdown rather than strand filters in the APO.
        # Headless smoke tests do not run an application event loop.
        if QApplication.instance().platformName().lower() == "offscreen":
            super().closeEvent(event)
            return
        if self.request_exit():
            event.accept()
        else:
            event.ignore()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    mutex = WindowsInstanceMutex()
    try:
        first = mutex.acquire()
    except InstanceError as exc:
        QMessageBox.critical(None, "Ошибка запуска эквалайзера", str(exc))
        return 1
    if not first:
        if not notify_running_instance():
            QMessageBox.information(
                None, "Эквалайзер уже запущен",
                "Программа уже работает. Откройте её через значок в области "
                "уведомлений Windows (в том числе «Отображать скрытые значки»).",
            )
        return 0

    activation = ActivationEvent()
    try:
        activation.create()
    except InstanceError as exc:
        mutex.release()
        QMessageBox.critical(None, "Ошибка запуска эквалайзера", str(exc))
        return 1
    try:
        window = Window()
        activation_timer = QTimer(window)
        def poll_activation():
            try:
                if activation.consume():
                    window.show_window()
            except InstanceError as exc:
                activation_timer.stop()
                window.report(str(exc))
        activation_timer.timeout.connect(poll_activation)
        activation_timer.start(200)
        app.aboutToQuit.connect(window.best_effort_stop_on_quit)
        window.show()
        return app.exec()
    finally:
        activation.close()
        mutex.release()


if __name__ == "__main__":
    sys.exit(main())