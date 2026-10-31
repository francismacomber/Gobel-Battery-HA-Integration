"""Pure value mapping for per-pack JK telemetry entities.

These helpers turn the pack dict produced by ``JKBMS485.get_analog_data()``
into entity values. They import nothing from Home Assistant so they can be
unit-tested on their own. A missing or unparsed value is always ``None``
(Home Assistant shows "unknown"), never 0 or False.
"""

# Per-pack cell statistics exposed as sensors: entity key -> pack dict key.
# The values are the BMS-reported fields where the protocol has them
# (average and delta at offsets 74 and 76, the extreme cell numbers at 78
# and 79, converted to 1-based in get_analog_data); min and max are taken
# from the cell list because the frame carries no such field.
CELL_STAT_KEYS = {
    "cell_voltage_avg": "cell_voltage_avg",
    "cell_voltage_min": "cell_voltage_min",
    "cell_voltage_max": "cell_voltage_max",
    "cell_voltage_diff": "cell_voltage_diff",
    "cell_voltage_max_index": "cell_voltage_max_index",
    "cell_voltage_min_index": "cell_voltage_min_index",
}

# MOS state binary sensors: entity key -> pack dict key.
MOS_STATE_KEYS = {
    "charge_mos": "charge_mos_state",
    "discharge_mos": "discharge_mos_state",
    "balance_mos": "balance_mos_state",
}


def find_pack(packs, pack_id):
    """Return the pack dict with ``pack_id`` from a list, or None."""
    if not packs:
        return None
    return next((p for p in packs if p.get("pack_id") == pack_id), None)


def cell_resistance(pack_data, cell_index):
    """Wire resistance of 1-based ``cell_index`` in mΩ, or None.

    None when the pack has no resistance list, the slot is beyond the
    populated cells, or the parser marked the slot as out of range.
    """
    if not pack_data:
        return None
    resistances = pack_data.get("cell_resistances") or []
    idx = cell_index - 1
    if idx < 0 or idx >= len(resistances):
        return None
    return resistances[idx]


def cell_voltage_stat(pack_data, key):
    """One of the CELL_STAT_KEYS values for the pack, or None.

    The statistics only mean something when the pack reported cell
    voltages; get_analog_data writes zeros otherwise, which must not be
    shown as a measurement.
    """
    if not pack_data or not pack_data.get("cell_voltages"):
        return None
    source = CELL_STAT_KEYS.get(key)
    if source is None:
        return None
    value = pack_data.get(source)
    if value is None:
        return None
    if key.endswith("_index") and value < 1:
        return None
    return value


def runtime_seconds(pack_data):
    """Total BMS runtime in seconds (``view_run_time``), or None."""
    if not pack_data:
        return None
    return pack_data.get("view_run_time")


def mos_state(pack_data, key):
    """Boolean state of one MOS (``charge_mos`` etc.), or None when absent."""
    if not pack_data:
        return None
    source = MOS_STATE_KEYS.get(key)
    if source is None or source not in pack_data:
        return None
    value = pack_data[source]
    if value is None:
        return None
    return bool(value)
