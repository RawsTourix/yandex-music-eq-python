"""Minimal Windows GUI modeled after the Yandex Music equalizer controls."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QProcess, QThread
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget, QPlainTextEdit,
)

import apo
import installer
from equalizer import (
    SETTINGS_FILE, Settings, load_custom, load_library, load_settings,
    preset_settings, save_settings,
)

BG = QColor("#1a1a1a")
MUTED = QColor("#898989")
RAIL = QColor("#353535")
YELLOW = QColor("#ffff00")
FREQUENCY_LABELS = ("60", "170", "310", "600", "1k", "3k", "6k", "12k", "14k", "16k")


class BandSlider(QWidget):
    value_changed = Signal(float)

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
            self._from_y(event.position().y())
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
            self.settings = load_settings(self.library)
            self.custom = load_custom(self.library)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Do not overwrite an invalid file silently. The user must inspect it.
            QMessageBox.warning(self, "Некорректные настройки", f"{exc}\nЗакройте приложение и исправьте settings.json.")
            raise
        self.setWindowTitle("Yandex Music EQ — independent")
        self.setFixedSize(463, 480)
        self.setStyleSheet("""
            QMainWindow, QWidget#root { background: #1a1a1a; }
            QLabel { color: #dedede; font-family: 'Segoe UI'; }
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
            QPushButton { background: transparent; color: #9a9a9a;
                          border: none; font-size: 11px; text-align: right; }
            QPushButton:hover { color: #ffff00; }
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
        sliders.addWidget(self.preamp)
        sliders.addSpacing(7)
        sliders.addWidget(Scale())
        sliders.addStretch(1)
        self.bands = []
        for index, name in enumerate(FREQUENCY_LABELS):
            slider = BandSlider(name, -12, 12, self.settings.gains_db[index])
            slider.value_changed.connect(lambda value, i=index: self.edit_band(i, value))
            sliders.addWidget(slider)
            self.bands.append(slider)
        sliders.addStretch(1)
        layout.addLayout(sliders)
        self.preset = QComboBox()
        self.preset.setFixedHeight(52)
        self.preset.addItem("Своя настройка", "CUSTOM")
        self.preset.addItem("По умолчанию", "DEFAULT")
        for name in self.library["presets"]:
            if name not in ("CUSTOM", "DEFAULT"):
                self.preset.addItem(name.replace("_", " ").title(), name)
        self.preset.setCurrentIndex(self.preset.findData(self.settings.preset_id))
        self.preset.currentIndexChanged.connect(self.choose_preset)
        layout.addWidget(self.preset)
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
        self.setup_process = None
        self.install_worker = None
        self.connection_timer = QTimer(self)
        self.connection_timer.timeout.connect(self.check_connection)
        self.connection_timer.start(2000)
        self.check_connection()
        QTimer.singleShot(250, self.startup_check)

    def report(self, message: str):
        """Show diagnostics in the window rather than in a hidden console."""
        if message and (not self.messages.toPlainText().splitlines() or
                        self.messages.toPlainText().splitlines()[-1] != message):
            self.messages.appendPlainText(message)

    def check_connection(self):
        connected, reason = apo.connection_status()
        if connected != self.connected:
            self.connected = connected
            if connected:
                self.schedule_write()
        self.status.setText("APO: конфигурация OK" if connected else
                            "APO: не установлен" if apo.config_directory() is None else "APO: не подключён")
        busy = self.setup_process is not None or self.install_worker is not None
        self.setup_button.setVisible(os.name == "nt" and (not connected or busy))
        self.setup_button.setEnabled(not busy)
        if not busy:
            self.setup_button.setText("Установить APO" if apo.config_directory() is None else "Подключить APO")

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
        self.report("Конфигурация APO записана. Если звук не меняется, проверьте устройство в Configurator и перезагрузите Windows")

    def schedule_write(self):
        self.write_timer.start(160)

    def toggle(self, enabled: bool):
        self.settings = replace(self.settings, enabled=enabled)
        self.schedule_write()

    def edit_preamp(self, value: float):
        self.settings = replace(self.settings, preset_id="CUSTOM", preamp_linear=value)
        self.custom = replace(self.settings, enabled=False)
        self.mark_custom()
        self.schedule_write()

    def edit_band(self, index: int, value: float):
        gains = list(self.settings.gains_db)
        gains[index] = value
        self.settings = replace(self.settings, preset_id="CUSTOM", gains_db=tuple(gains))
        self.custom = replace(self.settings, enabled=False)
        self.mark_custom()
        self.schedule_write()

    def mark_custom(self):
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(self.preset.findData("CUSTOM"))
        self.preset.blockSignals(False)

    def choose_preset(self, index: int):
        name = self.preset.itemData(index)
        if not name:
            return
        if name == "CUSTOM":
            self.settings = replace(self.custom, enabled=self.settings.enabled)
        else:
            self.settings = preset_settings(self.library, name, enabled=self.settings.enabled)
        self.preamp.set_value(self.settings.preamp_linear)
        for widget, value in zip(self.bands, self.settings.gains_db):
            widget.set_value(value)
        self.schedule_write()

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
        else:
            self.setup_apo()

    def offer_install(self):
        if os.name != "nt" or self.install_worker is not None or self.setup_process is not None:
            return
        if not installer.supported_architecture():
            self.report("Автоустановка доступна только для Windows x64: " + installer.OFFICIAL_PAGE)
            return
        answer = QMessageBox.question(
            self, "Установить Equalizer APO?",
            "Для обработки системного звука требуется Equalizer APO.\n\n"
            "Скачать официальный установщик версии 1.4.2 с SourceForge (около 12 МБ), "
            "проверить SHA-256 и запустить мастер установки?\n\n"
            "Windows запросит права администратора. В мастере нужно выбрать "
            "аудиоустройство и затем перезагрузить Windows.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
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
            self.report("Файл фильтров обновлён. В Configurator должно быть включено нужное устройство вывода")
        elif success:
            self.report("Установщик сообщил об успехе, но Include не обнаружен. Проверьте config.txt")

    def closeEvent(self, event):
        if self.write_timer.isActive():
            self.write_timer.stop()
            self.commit_settings()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = Window()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()