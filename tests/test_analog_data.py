"""get_analog_data() / get_warning_data() on the captured frames (the native entity path)."""
import pytest

from conftest import (
    EXPECTED_RESISTANCES, EXPECTED_AVG, EXPECTED_DELTA,
    EXPECTED_MAX_CELL, EXPECTED_MIN_CELL, EXPECTED_RUNTIME, EXPECTED_MOS,
)
from custom_components.gobel_battery import pack_values


def _pack(packs, pack_id):
    return pack_values.find_pack(packs, pack_id)


def test_both_packs_present(loaded_bms):
    packs = loaded_bms.get_analog_data()
    assert sorted(p["pack_id"] for p in packs) == [0, 1]
    warnings = loaded_bms.get_warning_data()
    assert sorted(p["pack_id"] for p in warnings) == [0, 1]


@pytest.mark.parametrize("pack_id", [0, 1])
def test_resistances_in_pack_dict(loaded_bms, pack_id):
    pack = _pack(loaded_bms.get_analog_data(), pack_id)
    assert pack["cell_resistances"] == EXPECTED_RESISTANCES[pack_id]
    for n in range(1, 17):
        assert pack_values.cell_resistance(pack, n) == EXPECTED_RESISTANCES[pack_id][n - 1]
    assert pack_values.cell_resistance(pack, 17) is None
    assert pack_values.cell_resistance(pack, 0) is None


@pytest.mark.parametrize("pack_id", [0, 1])
def test_cell_statistics_one_based(loaded_bms, pack_id):
    pack = _pack(loaded_bms.get_analog_data(), pack_id)
    assert pack["cell_voltage_avg"] == EXPECTED_AVG[pack_id]
    assert pack["cell_voltage_diff"] == EXPECTED_DELTA[pack_id]
    assert pack["cell_voltage_max_index"] == EXPECTED_MAX_CELL[pack_id]
    assert pack["cell_voltage_min_index"] == EXPECTED_MIN_CELL[pack_id]
    assert pack["cell_voltage_max"] == max(pack["cell_voltages"])
    assert pack["cell_voltage_min"] == min(pack["cell_voltages"])
    # the per-pack values are the pack's own, never bank-wide
    assert pack_values.cell_voltage_stat(pack, "cell_voltage_avg") == EXPECTED_AVG[pack_id]
    assert pack_values.cell_voltage_stat(pack, "cell_voltage_diff") == EXPECTED_DELTA[pack_id]
    assert pack_values.cell_voltage_stat(pack, "cell_voltage_max_index") == EXPECTED_MAX_CELL[pack_id]
    assert pack_values.cell_voltage_stat(pack, "cell_voltage_min_index") == EXPECTED_MIN_CELL[pack_id]
    assert pack_values.cell_voltage_stat(pack, "cell_voltage_max") == max(pack["cell_voltages"])
    assert pack_values.cell_voltage_stat(pack, "cell_voltage_min") == min(pack["cell_voltages"])


def test_pack_1_extrema_match_capture_notes(loaded_bms):
    pack = _pack(loaded_bms.get_analog_data(), 1)
    assert pack["cell_voltage_max_index"] == 2
    assert pack["cell_voltage_min_index"] == 7
    assert pack["cell_voltages"][1] == 3197
    assert pack["cell_voltages"][6] == 3177


@pytest.mark.parametrize("pack_id", [0, 1])
def test_runtime_and_mos(loaded_bms, pack_id):
    pack = _pack(loaded_bms.get_analog_data(), pack_id)
    assert pack["view_run_time"] == EXPECTED_RUNTIME[pack_id]
    assert pack_values.runtime_seconds(pack) == EXPECTED_RUNTIME[pack_id]
    assert pack["charge_mos_state"] is EXPECTED_MOS["charge"]
    assert pack["discharge_mos_state"] is EXPECTED_MOS["discharge"]
    assert pack["balance_mos_state"] is EXPECTED_MOS["balance"]
    assert pack_values.mos_state(pack, "charge_mos") is True
    assert pack_values.mos_state(pack, "discharge_mos") is True
    assert pack_values.mos_state(pack, "balance_mos") is False


@pytest.mark.parametrize("pack_id", [0, 1])
def test_existing_pack_values_unchanged(loaded_bms, pack_id):
    """The keys the existing 57 per-pack entities read are still produced as before."""
    pack = _pack(loaded_bms.get_analog_data(), pack_id)
    assert len(pack["cell_voltages"]) == 16
    # bat1, bat2, bat3, bat4, bat5, MOS all parse on this firmware -> six temperatures
    assert len(pack["temperatures"]) == 6
    assert pack["temperatures"][2] == pack["temperatures"][5]   # temperature_03 duplicates _06 (MOS)
    for key in ("view_voltage", "view_current", "view_power", "view_SOC", "view_SOH",
                "view_remain_capacity", "view_full_capacity", "view_cycle_number",
                "view_balance_current"):
        assert key in pack
    assert pack["view_voltage"] > 40
    assert pack["view_current"] < 0          # both packs were discharging
    assert pack["view_cycle_number"] == {0: 97, 1: 429}[pack_id]
    assert pack["view_SOH"] == {0: 100.0, 1: 93.0}[pack_id]


def test_absent_fields_give_none():
    """A pack dict without the new keys maps to None everywhere, never 0 or False."""
    pack = {"pack_id": 3, "cell_voltages": [3300] * 4}
    assert pack_values.cell_resistance(pack, 1) is None
    assert pack_values.cell_voltage_stat(pack, "cell_voltage_avg") is None
    assert pack_values.cell_voltage_stat(pack, "cell_voltage_max_index") is None
    assert pack_values.runtime_seconds(pack) is None
    for key in ("charge_mos", "discharge_mos", "balance_mos"):
        assert pack_values.mos_state(pack, key) is None
    assert pack_values.mos_state({"pack_id": 3, "charge_mos_state": None}, "charge_mos") is None
    assert pack_values.find_pack([pack], 4) is None
    assert pack_values.find_pack([], 3) is None
    assert pack_values.cell_resistance(None, 1) is None
    assert pack_values.mos_state(None, "charge_mos") is None


def test_statistics_without_cells_are_unknown_not_zero():
    """get_analog_data writes zeros when a pack has no cells; the entity must not show them."""
    pack = {
        "pack_id": 0, "cell_voltages": [],
        "cell_voltage_max": 0, "cell_voltage_min": 0, "cell_voltage_diff": 0,
        "cell_voltage_max_index": 0, "cell_voltage_min_index": 0,
    }
    for key in pack_values.CELL_STAT_KEYS:
        assert pack_values.cell_voltage_stat(pack, key) is None


def test_none_slot_survives_into_pack_dict(bms, dynamic_frames):
    import struct
    buf = bytearray(dynamic_frames[1][-1])
    struct.pack_into("<h", buf, 80, 5000)        # cell 1 out of range
    bms._handle_valid_frame(bytes(buf), 0x1620, 1)
    pack = _pack(bms.get_analog_data(), 1)
    assert pack["cell_resistances"][0] is None
    assert pack["cell_resistances"][1:] == EXPECTED_RESISTANCES[1][1:]
    assert pack_values.cell_resistance(pack, 1) is None
    assert pack_values.cell_resistance(pack, 2) == 105
