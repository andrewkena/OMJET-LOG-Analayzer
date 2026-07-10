"""Two-language (RU/EN) translation module.

All canonical strings are in Russian. tr(ru_str) returns the English
equivalent when language is 'en', otherwise returns the string unchanged.
Selected language is persisted to user_settings.json next to main.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.core.paths import get_user_data_dir
_SETTINGS_FILE = get_user_data_dir() / "user_settings.json"

_lang = "ru"
_callbacks: list = []

_EN: dict[str, str] = {
    # ── main window ─────────────────────────────────────────────────────────
    "Открыть лог-файл": "Open Log File",
    "Поддерживаемые файлы: ArduPilot dataflash (*.bin, *.log), телеметрия (*.tlog)":
        "Supported files: ArduPilot dataflash (*.bin, *.log), telemetry (*.tlog)",
    "Скорость:": "Speed:",
    "Тип:": "Type:",
    # tab titles
    "Карта": "Map",
    "Графики": "Graphs",
    "Анализ миссии": "Mission Analysis",
    "События": "Events",
    "Параметры полетного контроллера": "Flight Controller Parameters",
    "Полетное задание": "Flight Plan",
    "Геотегирование фотографий": "Photo Geotagging",
    "Настройки": "Settings",
    # graph tab
    "График": "Graph",
    "Добавить параметр в поле графика (до {n} параметров на один график):":
        "Add parameter to graph (up to {n} parameters per graph):",
    # ── map widget ───────────────────────────────────────────────────────────
    "Подложка": "Basemap",
    "Спутник": "Satellite",
    "Гибрид": "Hybrid",
    "Карта ГШ": "Road Map",
    "Рельеф": "Terrain",
    "Центрировать": "Center",
    "Фотографии": "Photos",
    "Количество фото: нет": "Photos: none",
    "Количество фото: ": "Photos: ",
    "Иконка:": "Icon:",
    "Ошибки": "Errors",
    "Ветер": "Wind",
    "Ошибки и сбои": "Errors & Failures",
    "Фэйлсейф": "Failsafe",
    "Ассистент": "Assist",
    "Ошибка": "Error",
    "Допустимый ветер": "Max Wind",
    "количество отправленных фотоимпульсов в камеру":
        "shutter triggers sent to camera",
    "количество полученных фотоимпульсов от камеры":
        "shutter triggers received from camera",
    # ── events widget ────────────────────────────────────────────────────────
    "Время полёта": "Flight time",
    "Время GPS": "GPS time",
    "Сообщение": "Message",
    "Расшифровка": "Decoded",
    # ── params widget ────────────────────────────────────────────────────────
    "Фильтр параметров...": "Filter parameters...",
    "Скачать параметры (.param)": "Download Parameters (.param)",
    "Параметр": "Parameter",
    "Значение": "Value",
    "Нет параметров": "No parameters",
    "Параметры не загружены.": "No parameters loaded.",
    "Сохранить параметры": "Save Parameters",
    "Файлы параметров ArduPilot (*.param *.parm);;Все файлы (*)":
        "ArduPilot parameter files (*.param *.parm);;All Files (*)",
    # ── mission widget ───────────────────────────────────────────────────────
    "Скачать миссию (.waypoints)": "Download Mission (.waypoints)",
    "Нет миссии": "No mission",
    "Точки миссии не загружены.": "No mission waypoints loaded.",
    "Сохранить миссию": "Save Mission",
    "Файлы точек маршрута (*.waypoints);;Все файлы (*)":
        "Waypoint files (*.waypoints);;All Files (*)",
    "Показать весь трек": "Fit All",
    # mission table columns
    "Команда": "Command",
    "Широта": "Lat",
    "Долгота": "Lng",
    "Высота м": "Alt",
    "Рамка": "Frame",
    "Параметры кmd": "Params",
    "Сиквенс": "Seq",
    "ID команды": "Cmd ID",
    "Описание": "Description",
    # ── mission analysis ─────────────────────────────────────────────────────
    "Время": "Time",
    "Время начала миссии:": "Mission start:",
    "Время окончания:": "End time:",
    "Продолжительность:": "Duration:",
    "Полет": "Flight",
    "Пройденное расстояние:": "Distance covered:",
    "Время работы вертикальных моторов:": "Vertical motors run time:",
    "Время работы ходового мотора:": "Forward motor run time:",
    "Время планирования (без моторов):": "Glide time (no motors):",
    "Средний ветер:": "Average wind:",
    "Максимальный ветер:": "Max wind:",
    "Преобладающее направление ветра:": "Prevailing wind direction:",
    "Углы": "Attitude",
    "Максимальный крен:": "Max roll:",
    "Максимальный тангаж:": "Max pitch:",
    "Фотосъемка": "Photography",
    "Количество фотоимпульсов отправленных в камеры:": "Shutter triggers sent to cameras:",
    "Количество фотоимпульсов полученных от камеры:": "Shutter triggers received from camera:",
    "Среднее время между фотоснимками:": "Avg time between photos:",
    "Среднее расстояние между фотоснимками:": "Avg distance between photos:",
    "Эффективность": "Efficiency",
    "Общий расход на километр:": "Total consumption per km:",
    "Общий расход на минуту:": "Total consumption per min:",
    "Горизонтальный расход на километр:": "Forward consumption per km:",
    "Горизонтальный расход на минуту:": "Forward consumption per min:",
    "Сформировать отчёт": "Generate Report",
    # ── battery widget ───────────────────────────────────────────────────────
    "Батарея 1": "Battery 1",
    "Батарея 2": "Battery 2",
    "Потрачено мА·ч:": "Consumed (mAh):",
    "Максимальный ток:": "Max current:",
    "Средний ток:": "Avg current:",
    # ── photo geotag widget ──────────────────────────────────────────────────
    "Выбрать папку с фотографиями...": "Select Photo Folder...",
    "Геометки GNSS": "GNSS Geotags",
    "Геометки с лога": "Log Geotags",
    "Геотегировать изображения": "Geotag Images",
    "Удалить все геопривязки": "Remove All Geotags",
    "Папка не выбрана": "No folder selected",
    "Список": "List",
    "Миниатюры": "Thumbnails",
    # ── settings widget ──────────────────────────────────────────────────────
    "Тема приложения": "App Theme",
    "Тема:": "Theme:",
    "Светлая": "Light",
    "Темная": "Dark",
    "Системная": "System",
    "Часовой пояс:": "Timezone:",
    "Язык:": "Language:",
    "Русский": "Russian",
    "Уведомления": "Notifications",
    "Звуковые оповещения": "Sound Alerts",
    "Кэш картографических данных": "Map Tile Cache",
    "Объём картографических данных: ": "Cached map data: ",
    "Максимальный объём:": "Max Size:",
    "Очистить кэш картографических данных": "Clear Map Cache",
    "Настройка аккумулятора": "Battery Configuration",
    "Количество ячеек:": "Cell Count:",
    "LiHV (повышенное напряжение)": "LiHV (High Voltage)",
    "Включить для LiHV аккумуляторов\n"
    "Стандартный LiPo: 4.20В/ячейку (заряжен) / 3.60В/ячейку (разряжен)\n"
    "LiHV: 4.35В/ячейку (заряжен) / 3.60В/ячейку (разряжен)":
        "Enable for LiHV batteries\n"
        "Standard LiPo: 4.20V/cell (full) / 3.60V/cell (empty)\n"
        "LiHV: 4.35V/cell (full) / 3.60V/cell (empty)",
    "Тип аккумулятора:": "Battery Type:",
    "Диапазон напряжения:": "Voltage Range:",
    "на ячейку": "per cell",
    "Информация о напряжении": "Battery Voltage Info",
    "LiPo / Li-ion:": "LiPo / Li-ion:",
    "  • Полный заряд: 4.20В/ячейку": "  • Full charge: 4.20V/cell",
    "  • Минимум: 3.60В/ячейку": "  • Safe minimum: 3.60V/cell",
    "LiHV (повышенное напряжение):": "LiHV (High Voltage):",
    "  • Полный заряд: 4.35В/ячейку": "  • Full charge: 4.35V/cell",
    "Цветовая настройка": "Color Settings",
    "Сила тока:": "Current:",
    "Зеленый:": "Green:",
    "Красный:": "Red:",
    "Минимальная:": "Min:",
    "Целевая:": "Target:",
    "Максимальная:": "Max:",
    "Максимальный ветер:": "Max Wind:",
    "Пороги эффективности": "Efficiency Thresholds",
    "Расход (мА·ч):": "Consumption (mAh):",
    # ── message tree ─────────────────────────────────────────────────────────
    "Параметры": "Parameters",
    "Избранное": "Favorites",
    "Пресеты": "Presets",
    # context menu
    "Переименовать параметр": "Rename parameter",
    "Вернуть оригинальное имя параметра": "Restore original name",
    "Очистить избранное": "Clear favorites",
    # ── map tile cache dialog ─────────────────────────────────────────────────
    "Кэш карты": "Map Cache",
    "Кэш картографических данных очищен.": "Map tile cache cleared.",
    "Объём картографических данных превышен": "Map tile cache limit exceeded",
    "Удалить данные": "Delete Data",
    "Закрыть": "Close",
    # ── playback controls ─────────────────────────────────────────────────────
    "◀ Назад": "◀ Backplay",
    "▶ Воспроизвести": "▶ Play",
    "⏸ Пауза": "⏸ Pause",
    "⏹ Стоп": "⏹ Stop",
    # ── photo geotag widget ──────────────────────────────────────────────────
    "Фотографии не найдены": "No photos found",
    "Фотографии не найдены (нет сообщений CAM/TRIG в логе)": "No photos found (no CAM/TRIG messages in log)",
    "Открыть файл геометок GNSS...": "Open GNSS Geotag File...",
    "Экспорт в CSV": "Export to CSV",
    "Геометки GNSS не загружены": "GNSS geotags not loaded",
    "Найдено фотографий": "Photos found",
    "из": "of",
    "исключено": "excluded",
    "геопривязанных": "geotagged",
    "Фотографий": "Photos",
    "Геометок с лога": "Log geotags",
    "Предпросмотр геотегирования": "Geotag Preview",
    "Будет геотегировано фотографий": "Photos to geotag",
    "Проверьте соответствие:": "Verify the match:",
    "Файл": "File",
    "Включить фотографию": "Include photo",
    "Исключить фотографию": "Exclude photo",
    "Включить точку": "Include point",
    "Исключить точку": "Exclude point",
    "Выберите папку с фотографиями": "Select Photo Folder",
    "Загрузка фотографий...": "Loading photos...",
    "Отмена": "Cancel",
    "Чтение: ": "Reading: ",
    "Обработка: ": "Processing: ",
    "Удаление геопривязок": "Remove Geotags",
    "Сначала выберите папку с фотографиями.": "Please select a photo folder first.",
    "Удаление геопривязок...": "Removing geotags...",
    "Удаление завершено с ошибками": "Removal completed with errors",
    "Удаление завершено": "Removal completed",
    "Геопривязка удалена из всех фотографий.": "GPS tags removed from all photos.",
    "Время полета": "Flight time",
    "Высота AMSL (м)": "Alt AMSL (m)",
    "Высота AGL (м)": "Alt AGL (m)",
    "Крен (°)": "Roll (°)",
    "Тангаж (°)": "Pitch (°)",
    "Курс (°)": "Yaw (°)",
    "Путевая скорость (м/с)": "Gnd Speed (m/s)",
    "Интервал (с)": "Interval (s)",
    "Расстояние (м)": "Distance (m)",
    "Файл/имя": "File/Name",
    "Высота (м)": "Alt (m)",
    "Геотегирование": "Geotagging",
    "Нет точек привязки: откройте файл геометок GNSS или лог с фотографиями (CAM/TRIG).":
        "No reference points: open a GNSS geotag file or log with photos (CAM/TRIG).",
    "Количество не совпадает": "Count mismatch",
    "Геотегирование завершено с ошибками": "Geotagging completed with errors",
    "Геотегирование завершено": "Geotagging completed",
    "Ошибка чтения файла": "File read error",
    "Не удалось распознать файл": "Could not parse file",
    "Экспорт геотегов фотографий": "Export Photo Geotags",
    "Файлы геометок (*.csv *.pos *.txt);;All files (*.*)":
        "Geotag files (*.csv *.pos *.txt);;All files (*.*)",
    "CSV files (*.csv)": "CSV files (*.csv)",
}


def tr(ru_str: str) -> str:
    """Return translated string for current language, or the original string."""
    if _lang == "en":
        return _EN.get(ru_str, ru_str)
    return ru_str


def get_language() -> str:
    return _lang


def set_language(lang: str) -> None:
    global _lang
    _lang = lang
    _save()
    for cb in list(_callbacks):
        cb()


def register(callback) -> None:
    """Register a callable to be invoked on every language change."""
    _callbacks.append(callback)


def load() -> None:
    """Load saved language preference from disk; call once at startup."""
    global _lang
    try:
        data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        _lang = data.get("language", "ru")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _lang = "ru"


def _save() -> None:
    try:
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}
        data["language"] = _lang
        _SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
