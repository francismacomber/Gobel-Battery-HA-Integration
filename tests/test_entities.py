"""The sensor / binary sensor entity classes: names, units, unique ids and values.

Runs against the real entity classes; when Home Assistant is not installed,
conftest provides minimal stand-ins for the base classes and enums.
"""
import asyncio

import pytest

from conftest import (
    EXPECTED_RESISTANCES, EXPECTED_AVG, EXPECTED_DELTA,
    EXPECTED_MAX_CELL, EXPECTED_MIN_CELL, EXPECTED_RUNTIME,
)
from custom_components.gobel_battery import sensor as sensor_platform
from custom_components.gobel_battery import binary_sensor as binary_platform
from custom_components.gobel_battery.const import DOMAIN

ENTRY_ID = "01TESTENTRY0000000000GOBEL"


class FakeEntry:
    def __init__(self):
        self.entry_id = ENTRY_ID
        self.unloaders = []

    def async_on_unload(self, func):
        self.unloaders.append(func)


class FakeCoordinator:
    def __init__(self, data, bms_type="JK_PB", index_start="00"):
        self.entry = FakeEntry()
        self.device_name = "Gobel Battery"
        self.bms_type = bms_type
        self.jk_display_index_start = index_start
        self.data = data
        self.last_update_success = True
        self.listeners = []

    def async_add_listener(self, func):
        self.listeners.append(func)
        return lambda: None


@pytest.fixture
def coordinator(loaded_bms):
    data = {"analog": loaded_bms.get_analog_data(), "warning": loaded_bms.get_warning_data()}
    return FakeCoordinator(data)


def _setup(platform, coordinator):
    """Run the platform's async_setup_entry and return every entity it added."""
    added = []

    def add_entities(entities, update_before_add=False):
        added.extend(entities)

    hass = type("Hass", (), {"data": {DOMAIN: {ENTRY_ID: coordinator}}})()
    asyncio.run(platform.async_setup_entry(hass, coordinator.entry, add_entities))
    return added


def _by_uid(entities):
    return {e.unique_id: e for e in entities}


# ---------------------------------------------------------------------------
# Registration counts
# ---------------------------------------------------------------------------

def test_sensor_platform_adds_26_new_entities_per_pack(coordinator):
    entities = _setup(sensor_platform, coordinator)
    uids = _by_uid(entities)
    assert len(uids) == len(entities), "unique ids must be unique"
    overall = [u for u in uids if u.startswith(f"{ENTRY_ID}_total_")]
    assert len(overall) == 10
    for pid in (0, 1):
        pack = [u for u in uids if u.startswith(f"{ENTRY_ID}_pack_{pid}_")]
        # 9 metrics + 16 cell voltages + 6 temperatures (as before) + 16 resistances + 7 new
        assert len(pack) == 9 + 16 + 6 + 16 + 7


def test_binary_platform_adds_3_new_entities_per_pack(coordinator):
    entities = _setup(binary_platform, coordinator)
    uids = _by_uid(entities)
    assert len(uids) == len(entities)
    for pid in (0, 1):
        pack = [u for u in uids if u.startswith(f"{ENTRY_ID}_pack_{pid}_")]
        assert len(pack) == 26 + 3


def test_total_entity_count_124_to_176(coordinator):
    total = len(_setup(sensor_platform, coordinator)) + len(_setup(binary_platform, coordinator))
    assert total == 176
    assert total - 124 == 2 * 26


def test_non_jk_bms_gets_no_new_entities(coordinator):
    coordinator.bms_type = "PACE_LV"
    sensors = _by_uid(_setup(sensor_platform, coordinator))
    binaries = _by_uid(_setup(binary_platform, coordinator))
    assert not any("_resistance" in u or u.endswith("_run_time") or "cell_voltage_" in u.split("_pack_")[-1]
                   for u in sensors if "_pack_" in u)
    assert not any(u.endswith("_mos") for u in binaries)


# ---------------------------------------------------------------------------
# Unique ids, names, units
# ---------------------------------------------------------------------------

def test_existing_unique_ids_unchanged(coordinator):
    sensors = _by_uid(_setup(sensor_platform, coordinator))
    binaries = _by_uid(_setup(binary_platform, coordinator))
    for pid in (0, 1):
        for metric in ("voltage", "current", "power", "soc", "soh", "remain_capacity",
                       "full_capacity", "cycle_number", "balance_current"):
            assert f"{ENTRY_ID}_pack_{pid}_{metric}" in sensors
        for n in range(1, 17):
            assert f"{ENTRY_ID}_pack_{pid}_cell_{n}_voltage" in sensors
        for n in range(1, 7):
            assert f"{ENTRY_ID}_pack_{pid}_temp_{n}" in sensors
        assert f"{ENTRY_ID}_pack_{pid}_protect_state_1_protect_short_circuit" in binaries
        assert f"{ENTRY_ID}_pack_{pid}_instruction_state_status_current_limit_enabled" in binaries
    for key in ("packs_count", "total_voltage", "total_cell_voltage_diff"):  # uid is _total_total_...: existing quirk, kept
        assert f"{ENTRY_ID}_total_{key}" in sensors
    # existing names are untouched
    assert sensors[f"{ENTRY_ID}_pack_0_cell_1_voltage"].name == "Gobel Battery Pack 00 Cell 01 Voltage"
    assert sensors[f"{ENTRY_ID}_pack_1_temp_6"].name == "Gobel Battery Pack 01 Temperature 06"


@pytest.mark.parametrize("pack_id", [0, 1])
def test_resistance_sensors(coordinator, pack_id):
    sensors = _by_uid(_setup(sensor_platform, coordinator))
    for n in range(1, 17):
        ent = sensors[f"{ENTRY_ID}_pack_{pack_id}_cell_{n}_resistance"]
        assert ent.name == f"Gobel Battery Pack {pack_id:02d} Cell {n:02d} Resistance"
        assert ent.native_unit_of_measurement == "mΩ"
        assert ent.device_class is None
        assert str(ent.state_class) == "measurement"
        assert ent.available is True
        assert ent.native_value == EXPECTED_RESISTANCES[pack_id][n - 1]
        assert ent.device_info["identifiers"] == {(DOMAIN, f"{ENTRY_ID}_pack_{pack_id}")}
    assert f"{ENTRY_ID}_pack_{pack_id}_cell_17_resistance" not in sensors


@pytest.mark.parametrize("pack_id", [0, 1])
def test_cell_statistic_sensors(coordinator, pack_id):
    sensors = _by_uid(_setup(sensor_platform, coordinator))
    expect = {
        "cell_voltage_avg": ("Cell Voltage Average", "mV", "voltage", "measurement", EXPECTED_AVG[pack_id]),
        "cell_voltage_diff": ("Cell Voltage Delta", "mV", "voltage", "measurement", EXPECTED_DELTA[pack_id]),
        "cell_voltage_max_index": ("Highest Cell", None, None, None, EXPECTED_MAX_CELL[pack_id]),
        "cell_voltage_min_index": ("Lowest Cell", None, None, None, EXPECTED_MIN_CELL[pack_id]),
        "run_time": ("Runtime", "s", "duration", "total_increasing", EXPECTED_RUNTIME[pack_id]),
    }
    pack = next(p for p in coordinator.data["analog"] if p["pack_id"] == pack_id)
    expect["cell_voltage_min"] = ("Cell Voltage Min", "mV", "voltage", "measurement", min(pack["cell_voltages"]))
    expect["cell_voltage_max"] = ("Cell Voltage Max", "mV", "voltage", "measurement", max(pack["cell_voltages"]))
    for key, (name, unit, dev_class, state_class, value) in expect.items():
        ent = sensors[f"{ENTRY_ID}_pack_{pack_id}_{key}"]
        assert ent.name == f"Gobel Battery Pack {pack_id:02d} {name}"
        assert ent.native_unit_of_measurement == unit
        assert (None if ent.device_class is None else str(ent.device_class)) == dev_class
        assert (None if ent.state_class is None else str(ent.state_class)) == state_class
        assert ent.native_value == value


def test_per_pack_statistics_are_not_bank_wide(coordinator):
    sensors = _by_uid(_setup(sensor_platform, coordinator))
    bank_max = sensors[f"{ENTRY_ID}_total_total_cell_voltage_max"].native_value
    bank_min = sensors[f"{ENTRY_ID}_total_total_cell_voltage_min"].native_value
    p0_max = sensors[f"{ENTRY_ID}_pack_0_cell_voltage_max"].native_value
    p1_min = sensors[f"{ENTRY_ID}_pack_1_cell_voltage_min"].native_value
    assert bank_max == 3197 and bank_min == 3163
    assert p0_max == 3183 and p1_min == 3177
    assert sensors[f"{ENTRY_ID}_pack_0_cell_voltage_diff"].native_value != bank_max - bank_min


@pytest.mark.parametrize("pack_id", [0, 1])
def test_mos_binary_sensors(coordinator, pack_id):
    binaries = _by_uid(_setup(binary_platform, coordinator))
    expect = {"charge_mos": ("Charge MOS", True), "discharge_mos": ("Discharge MOS", True),
              "balance_mos": ("Balance MOS", False)}
    for key, (name, state) in expect.items():
        ent = binaries[f"{ENTRY_ID}_pack_{pack_id}_{key}"]
        assert ent.name == f"Gobel Battery Pack {pack_id:02d} {name}"
        assert str(ent.device_class) == "running"
        assert ent.available is True
        assert ent.is_on is state
        assert ent.device_info["identifiers"] == {(DOMAIN, f"{ENTRY_ID}_pack_{pack_id}")}


def test_display_index_start_01_shifts_names_not_unique_ids(loaded_bms):
    data = {"analog": loaded_bms.get_analog_data(), "warning": loaded_bms.get_warning_data()}
    coord = FakeCoordinator(data, index_start="01")
    sensors = _by_uid(_setup(sensor_platform, coord))
    ent = sensors[f"{ENTRY_ID}_pack_0_cell_1_resistance"]
    assert ent.name == "Gobel Battery Pack 01 Cell 01 Resistance"
    assert ent.unique_id == f"{ENTRY_ID}_pack_0_cell_1_resistance"


# ---------------------------------------------------------------------------
# Missing values
# ---------------------------------------------------------------------------

def test_missing_values_are_unknown(coordinator):
    sensors = _by_uid(_setup(sensor_platform, coordinator))
    binaries = _by_uid(_setup(binary_platform, coordinator))
    pack0 = next(p for p in coordinator.data["analog"] if p["pack_id"] == 0)
    for key in ("cell_resistances", "view_run_time", "cell_voltage_avg",
                "charge_mos_state", "discharge_mos_state", "balance_mos_state"):
        pack0.pop(key, None)
    assert sensors[f"{ENTRY_ID}_pack_0_cell_1_resistance"].native_value is None
    assert sensors[f"{ENTRY_ID}_pack_0_run_time"].native_value is None
    assert sensors[f"{ENTRY_ID}_pack_0_cell_voltage_avg"].native_value is None
    for key in ("charge_mos", "discharge_mos", "balance_mos"):
        assert binaries[f"{ENTRY_ID}_pack_0_{key}"].is_on is None
    # the other pack is untouched
    assert sensors[f"{ENTRY_ID}_pack_1_cell_1_resistance"].native_value == 122
    assert binaries[f"{ENTRY_ID}_pack_1_charge_mos"].is_on is True


def test_none_resistance_slot_is_unknown_for_that_cell_only(coordinator):
    sensors = _by_uid(_setup(sensor_platform, coordinator))
    pack1 = next(p for p in coordinator.data["analog"] if p["pack_id"] == 1)
    pack1["cell_resistances"] = [None] + EXPECTED_RESISTANCES[1][1:]
    assert sensors[f"{ENTRY_ID}_pack_1_cell_1_resistance"].native_value is None
    assert sensors[f"{ENTRY_ID}_pack_1_cell_2_resistance"].native_value == 105
    assert sensors[f"{ENTRY_ID}_pack_1_cell_16_resistance"].native_value == 86


def test_pack_gone_makes_new_entities_unavailable(coordinator):
    sensors = _by_uid(_setup(sensor_platform, coordinator))
    binaries = _by_uid(_setup(binary_platform, coordinator))
    coordinator.data = {"analog": [p for p in coordinator.data["analog"] if p["pack_id"] == 0],
                        "warning": [p for p in coordinator.data["warning"] if p["pack_id"] == 0]}
    assert sensors[f"{ENTRY_ID}_pack_1_cell_1_resistance"].available is False
    assert sensors[f"{ENTRY_ID}_pack_1_run_time"].available is False
    assert binaries[f"{ENTRY_ID}_pack_1_charge_mos"].available is False
    assert sensors[f"{ENTRY_ID}_pack_0_run_time"].available is True
    coordinator.data = None
    assert sensors[f"{ENTRY_ID}_pack_0_run_time"].native_value is None
    assert binaries[f"{ENTRY_ID}_pack_0_charge_mos"].is_on is None
