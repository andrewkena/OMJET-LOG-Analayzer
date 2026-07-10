"""Human-readable decoding of ArduPilot dataflash EV (event) and ERR
(subsystem error) messages, used to annotate the map and event list."""
from __future__ import annotations

# ArduPilot's common LogEvent enum (AP_Logger/LogStructure.h) - stable across
# Copter/Plane/Rover firmware versions.
EVENT_ID_NAMES: dict[int, str] = {
    # Pre-enum legacy events
    7: "Состояние автопилота",
    8: "Установлено системное время",
    9: "Инициализация курса (simple bearing)",
    # ArduPilot LogEvent enum (AP_Logger/LogStructure.h)
    10: "Взведение моторов (Armed)",            # ARMED
    11: "Разоружение моторов (Disarmed)",        # DISARMED
    15: "Автовзведение (Auto Armed)",            # AUTO_ARMED
    17: "Возможное завершение посадки",          # LAND_COMPLETE_MAYBE
    18: "Посадка завершена",                     # LAND_COMPLETE
    19: "Потеря GPS",                            # LOST_GPS
    21: "Начало флипа",                          # FLIP_START
    22: "Окончание флипа",                       # FLIP_END
    25: "Установлен Home",                       # SET_HOME
    26: "Simple mode включён",                   # SET_SIMPLE_ON
    27: "Simple mode выключен",                  # SET_SIMPLE_OFF
    28: "Посадка не подтверждена",               # NOT_LANDED
    29: "Super Simple mode включён",             # SET_SUPERSIMPLE_ON
    30: "Autotune: инициализация",               # AUTOTUNE_INITIALISED
    31: "Autotune: выключен",                    # AUTOTUNE_OFF
    32: "Autotune: перезапуск",                  # AUTOTUNE_RESTART
    33: "Autotune: успешно завершён",            # AUTOTUNE_SUCCESS
    34: "Autotune: ошибка",                      # AUTOTUNE_FAILED
    35: "Autotune: достигнут предел",            # AUTOTUNE_REACHED_LIMIT
    36: "Autotune: тест пилотом",                # AUTOTUNE_PILOT_TESTING
    37: "Autotune: коэффициенты сохранены",      # AUTOTUNE_SAVEDGAINS
    38: "Сохранение триммера",                   # SAVE_TRIM
    39: "Сохранение точки маршрута",             # SAVEWP_ADD_WP
    41: "Fence включён",                         # FENCE_ENABLE
    42: "Fence выключен",                        # FENCE_DISABLE
    43: "Acro trainer выключен",                 # ACRO_TRAINER_OFF
    44: "Acro trainer: выравнивание",            # ACRO_TRAINER_LEVELING
    45: "Acro trainer: ограничение угла",        # ACRO_TRAINER_LIMITED
    46: "Захват груза (gripper)",                # GRIPPER_GRAB
    47: "Отпускание груза (gripper)",            # GRIPPER_RELEASE
    49: "Парашют выключен",                      # PARACHUTE_DISABLED
    50: "Парашют включён",                       # PARACHUTE_ENABLED
    51: "Парашют выпущен",                       # PARACHUTE_RELEASED
    52: "Шасси выпущено",                        # LANDING_GEAR_DEPLOYED
    53: "Шасси убрано",                          # LANDING_GEAR_RETRACTED
    54: "Аварийная остановка моторов",           # MOTORS_EMERGENCY_STOPPED
    55: "Аварийная остановка моторов снята",     # MOTORS_EMERGENCY_STOP_CLEARED
    56: "Блокировка моторов (interlock) выкл.",  # MOTORS_INTERLOCK_DISABLED
    57: "Блокировка моторов (interlock) вкл.",   # MOTORS_INTERLOCK_ENABLED
    58: "Разгон ротора завершён",                # ROTOR_RUNUP_COMPLETE
    59: "Скорость ротора ниже критической",      # ROTOR_SPEED_BELOW_CRITICAL
    60: "Сброс высоты EKF",                      # EKF_ALT_RESET
    61: "Посадка отменена пилотом",              # LAND_CANCELLED_BY_PILOT
    62: "Сброс курса EKF (Yaw Reset)",           # EKF_YAW_RESET
    63: "ADSB: избегание включено",              # AVOIDANCE_ADSB_ENABLE
    64: "ADSB: избегание выключено",             # AVOIDANCE_ADSB_DISABLE
    65: "Избегание препятствий включено",        # AVOIDANCE_PROXIMITY_ENABLE
    66: "Избегание препятствий выключено",       # AVOIDANCE_PROXIMITY_DISABLE
    67: "Смена основного GPS",                   # GPS_PRIMARY_CHANGED
    # Extended events (newer firmware)
    68: "Zigzag: точка A сохранена",
    69: "Zigzag: точка B сохранена",
    70: "Zigzag: автоматический режим",
    71: "Wheelsteer: газ включён",
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
