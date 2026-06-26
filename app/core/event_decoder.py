"""Human-readable decoding of ArduPilot dataflash EV (event) and ERR
(subsystem error) messages, used to annotate the map and event list."""
from __future__ import annotations

# ArduPilot's common LogEvent enum (AP_Logger/LogStructure.h) - stable across
# Copter/Plane/Rover firmware versions.
EVENT_ID_NAMES: dict[int, str] = {
    7: "Состояние автопилота",
    8: "Установлено системное время",
    9: "Инициализация курса (simple bearing)",
    10: "Armed (моторы взведены)",
    11: "Disarmed (моторы разоружены)",
    15: "Auto-armed",
    16: "Начало взлёта",
    17: "Взлёт завершён",
    18: "Начало посадки",
    19: "Посадка завершена",
    20: "Потеря GPS",
    21: "Начало флипа",
    22: "Окончание флипа",
    23: "Установлен Home",
    24: "Simple mode включен",
    25: "Simple mode выключен",
    26: "Super Simple mode включен",
    27: "Super Simple mode выключен",
    28: "Возможное завершение посадки",
    29: "Посадка не подтверждена",
    30: "Autotune: инициализация",
    31: "Autotune: выключен",
    32: "Autotune: перезапуск",
    33: "Autotune: успешно завершен",
    34: "Autotune: ошибка",
    35: "Autotune: достигнут предел",
    36: "Autotune: тест пилотом",
    37: "Autotune: коэффициенты сохранены",
    38: "Сохранение триммера",
    39: "Сохранение точки маршрута",
    41: "Fence включен",
    42: "Fence выключен",
    43: "Acro trainer выключен",
    44: "Acro trainer: выравнивание",
    45: "Acro trainer: ограничение",
    46: "Захват грузом (gripper)",
    47: "Отпускание груза (gripper)",
    49: "Парашют выключен",
    50: "Парашют включен",
    51: "Парашют выпущен",
    52: "Шасси выпущено",
    53: "Шасси убрано",
    54: "Аварийная остановка моторов",
    55: "Аварийная остановка моторов снята",
    56: "Блокировка моторов (interlock) включена",
    57: "Блокировка моторов (interlock) выключена",
    58: "Разгон ротора завершен",
    59: "Скорость ротора ниже критической",
    60: "Сброс высоты EKF",
    61: "Посадка отменена пилотом",
    62: "Сброс курса EKF (yaw reset)",
    63: "ADSB избегание включено",
    64: "ADSB избегание выключено",
    65: "Избегание препятствий включено",
    66: "Избегание препятствий выключено",
    67: "Смена основного GPS",
    68: "Zigzag: точка A сохранена",
    69: "Zigzag: точка B сохранена",
    70: "Zigzag: автоматический режим",
    71: "Wheelsteer: газ включен",
    72: "Wheelsteer: газ выключен",
}

# ArduPilot's common error-subsystem enum (AP_Logger/LogStructure.h).
ERROR_SUBSYS_NAMES: dict[int, str] = {
    1: "Основная система",
    2: "Радиосвязь",
    3: "Компас",
    4: "Optical Flow",
    5: "Failsafe радио",
    6: "Failsafe батареи",
    7: "Failsafe GPS",
    8: "Failsafe GCS (наземная станция)",
    9: "Failsafe ограждения (fence)",
    10: "Режим полёта",
    11: "GPS",
    12: "Проверка крэша",
    13: "Флип",
    14: "Autotune",
    15: "Парашют",
    16: "Проверка EKF",
    17: "Failsafe EKF/InertialNav",
    18: "Барометр",
    19: "Загрузка CPU",
    20: "Failsafe ADSB",
    21: "Рельеф местности",
    22: "Навигация",
    23: "Failsafe рельефа",
    24: "Основной EKF",
    25: "Проверка потери тяги",
    26: "Failsafe датчиков",
    27: "Failsafe утечки",
    28: "Управление пилотом",
    29: "Failsafe вибрации",
    30: "Внутренняя ошибка",
    31: "Failsafe dead reckoning",
}

# Generic error codes shared across most subsystems; subsystem-specific codes
# vary by firmware version, so unknown codes fall back to a raw number.
_GENERIC_ERROR_CODES: dict[int, str] = {
    0: "устранена",
    1: "не удалось инициализировать",
    2: "сбой/потеря данных",
    3: "недоступно",
    4: "нестабильна (unhealthy)",
}


def decode_event(event_id: int) -> str:
    name = EVENT_ID_NAMES.get(int(event_id))
    return name if name else f"Событие #{int(event_id)}"


def decode_error(subsys: int, ecode: int) -> str:
    subsys_i, ecode_i = int(subsys), int(ecode)
    subsys_name = ERROR_SUBSYS_NAMES.get(subsys_i, f"Подсистема #{subsys_i}")
    code_name = _GENERIC_ERROR_CODES.get(ecode_i)
    if code_name:
        return f"{subsys_name}: {code_name}"
    return f"{subsys_name}: код ошибки {ecode_i}"
