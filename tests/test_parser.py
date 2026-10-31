"""parse_jkbms_55aa_frame against the captured dynamic frames."""
import struct

import pytest

from conftest import (
    EXPECTED_RESISTANCES, EXPECTED_AVG, EXPECTED_DELTA,
    EXPECTED_MAX_CELL, EXPECTED_MIN_CELL, EXPECTED_RUNTIME, EXPECTED_MOS,
)


def test_capture_shape(capture):
    """Twelve 300-byte frames, three dynamic and three setup per pack, no static frame."""
    frames = capture["frames"]
    assert len(frames) == 12
    assert all(f["frame_length"] == 300 for f in frames)
    assert capture["excluded_static_frames"] == 0
    kinds = {(f["kind"], f["pack_id"]) for f in frames}
    assert kinds == {("dynamic", 0), ("dynamic", 1), ("setup", 0), ("setup", 1)}
    assert sum(1 for f in frames if f["kind"] == "dynamic" and f["pack_id"] == 0) == 3
    assert sum(1 for f in frames if f["kind"] == "setup" and f["pack_id"] == 1) == 3


@pytest.mark.parametrize("pack_id", [0, 1])
def test_resistances_all_sixteen_cells(bms, dynamic_frames, pack_id):
    for frame in dynamic_frames[pack_id]:
        parsed = bms.parse_jkbms_55aa_frame(frame)
        assert len(parsed["cell_voltages"]) == 16
        assert parsed["cell_resistances"] == EXPECTED_RESISTANCES[pack_id]
        assert all(0 <= r <= 1000 for r in parsed["cell_resistances"])


@pytest.mark.parametrize("pack_id", [0, 1])
def test_bms_cell_statistics_zero_based(bms, dynamic_frames, pack_id):
    parsed = bms.parse_jkbms_55aa_frame(dynamic_frames[pack_id][-1])
    assert parsed["cell_voltage_avg"] == EXPECTED_AVG[pack_id]
    assert parsed["cell_voltage_diff"] == EXPECTED_DELTA[pack_id]
    # the frame carries 0-based cell numbers; get_analog_data adds one
    assert parsed["cell_voltage_max_index"] == EXPECTED_MAX_CELL[pack_id] - 1
    assert parsed["cell_voltage_min_index"] == EXPECTED_MIN_CELL[pack_id] - 1
    cells = parsed["cell_voltages"]
    assert cells[parsed["cell_voltage_max_index"]] == max(cells)
    assert cells[parsed["cell_voltage_min_index"]] == min(cells)


@pytest.mark.parametrize("pack_id", [0, 1])
def test_runtime_counts_seconds(bms, dynamic_frames, pack_id):
    runtimes = [bms.parse_jkbms_55aa_frame(f)["total_runtime_s"] for f in dynamic_frames[pack_id]]
    assert runtimes[-1] == EXPECTED_RUNTIME[pack_id]
    assert runtimes == sorted(runtimes)
    # ~7 s between consecutive frames of one pack in the capture
    assert all(0 < b - a < 30 for a, b in zip(runtimes, runtimes[1:]))


@pytest.mark.parametrize("pack_id", [0, 1])
def test_mos_states(bms, dynamic_frames, pack_id):
    for frame in dynamic_frames[pack_id]:
        parsed = bms.parse_jkbms_55aa_frame(frame)
        assert parsed["charge_mos"] is EXPECTED_MOS["charge"]
        assert parsed["discharge_mos"] is EXPECTED_MOS["discharge"]
        assert parsed["balance_mos"] is EXPECTED_MOS["balance"]


@pytest.mark.parametrize("pack_id", [0, 1])
def test_offset_254_mirrors_mos_temperature(bms, dynamic_frames, pack_id):
    """Finding, not a change: on this firmware "bat3" (offset 254) equals the MOS temperature (144)."""
    for frame in dynamic_frames[pack_id]:
        parsed = bms.parse_jkbms_55aa_frame(frame)
        assert parsed["temp_bat3"] == parsed["temp_mos"]
        assert struct.unpack_from("<h", frame, 254)[0] == struct.unpack_from("<h", frame, 144)[0]


def _with_resistance(frame, cell_index, raw):
    """Copy of the frame with cell ``cell_index`` (1-based) resistance set to ``raw``."""
    buf = bytearray(frame)
    struct.pack_into("<h", buf, 80 + (cell_index - 1) * 2, raw)
    return bytes(buf)


@pytest.mark.parametrize("raw", [1001, 32767, -1, -32768])
def test_out_of_range_resistance_keeps_slot_as_none(bms, dynamic_frames, raw):
    frame = _with_resistance(dynamic_frames[0][-1], 5, raw)
    parsed = bms.parse_jkbms_55aa_frame(frame)
    expected = list(EXPECTED_RESISTANCES[0])
    expected[4] = None
    assert parsed["cell_resistances"] == expected
    assert len(parsed["cell_resistances"]) == 16
    # the cells after the bad one are still there (the old parser dropped them)
    assert parsed["cell_resistances"][5:] == EXPECTED_RESISTANCES[0][5:]


def test_resistance_slots_follow_populated_cells(bms, dynamic_frames):
    """An 8S frame yields eight resistance slots, not sixteen."""
    buf = bytearray(dynamic_frames[0][-1])
    for i in range(8, 16):
        struct.pack_into("<H", buf, 6 + i * 2, 0)
    parsed = bms.parse_jkbms_55aa_frame(bytes(buf))
    assert len(parsed["cell_voltages"]) == 8
    assert parsed["cell_resistances"] == EXPECTED_RESISTANCES[0][:8]


def test_frame_too_short_for_resistances_has_no_key(bms, dynamic_frames):
    parsed = bms.parse_jkbms_55aa_frame(dynamic_frames[0][-1][:80])
    assert len(parsed["cell_voltages"]) == 16
    assert "cell_resistances" not in parsed
    assert "total_runtime_s" not in parsed
    assert "charge_mos" not in parsed


def test_setup_frames_have_no_serial(capture):
    """The fixture must stay free of identification data."""
    for f in capture["frames"]:
        assert f["register"].lower() in ("0x1620", "0x161e")
