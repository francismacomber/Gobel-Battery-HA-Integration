"""Test setup: load the integration modules without a Home Assistant install.

The package ``custom_components.gobel_battery`` is registered as a bare
package (its ``__init__`` imports the coordinator, pyserial and Home
Assistant), so submodules import on their own. When ``homeassistant`` is not
installed, minimal stand-ins for the handful of names the sensor and binary
sensor platforms import are provided, so the real entity classes can be
constructed and inspected.
"""
import enum
import json
import logging
import sys
import threading
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = REPO_ROOT / "custom_components" / "gobel_battery"
FIXTURE = Path(__file__).parent / "fixtures" / "waveshare-jk-raw-frames-2026-10-30_22-12-04.json"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _register_bare_package():
    if "custom_components.gobel_battery" in sys.modules:
        return
    parent = sys.modules.get("custom_components")
    if parent is None:
        parent = types.ModuleType("custom_components")
        parent.__path__ = [str(REPO_ROOT / "custom_components")]
        sys.modules["custom_components"] = parent
    pkg = types.ModuleType("custom_components.gobel_battery")
    pkg.__path__ = [str(COMPONENT_DIR)]
    pkg.__package__ = "custom_components.gobel_battery"
    sys.modules["custom_components.gobel_battery"] = pkg
    parent.gobel_battery = pkg


def _install_ha_stubs():
    try:
        import homeassistant.components.sensor  # noqa: F401
        return False
    except ImportError:
        pass

    class _StrEnum(str, enum.Enum):
        def __str__(self):
            return str(self.value)

    class SensorDeviceClass(_StrEnum):
        VOLTAGE = "voltage"
        CURRENT = "current"
        POWER = "power"
        BATTERY = "battery"
        TEMPERATURE = "temperature"
        DURATION = "duration"

    class SensorStateClass(_StrEnum):
        MEASUREMENT = "measurement"
        TOTAL = "total"
        TOTAL_INCREASING = "total_increasing"

    class BinarySensorDeviceClass(_StrEnum):
        PROBLEM = "problem"
        HEAT = "heat"
        PLUG = "plug"
        POWER = "power"
        RUNNING = "running"

    class Entity:
        _attr_name = None
        _attr_unique_id = None
        _attr_native_unit_of_measurement = None
        _attr_device_class = None
        _attr_state_class = None
        _attr_icon = None

        @property
        def name(self):
            return self._attr_name

        @property
        def unique_id(self):
            return self._attr_unique_id

        @property
        def native_unit_of_measurement(self):
            return self._attr_native_unit_of_measurement

        @property
        def device_class(self):
            return self._attr_device_class

        @property
        def state_class(self):
            return self._attr_state_class

        @property
        def icon(self):
            return self._attr_icon

    class SensorEntity(Entity):
        pass

    class BinarySensorEntity(Entity):
        pass

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

        @property
        def available(self):
            return getattr(self.coordinator, "last_update_success", True)

    def callback(func):
        return func

    def module(name, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod
        return mod

    ha = module("homeassistant")
    ha.components = module("homeassistant.components")
    ha.components.sensor = module(
        "homeassistant.components.sensor",
        SensorEntity=SensorEntity,
        SensorStateClass=SensorStateClass,
        SensorDeviceClass=SensorDeviceClass,
    )
    ha.components.binary_sensor = module(
        "homeassistant.components.binary_sensor",
        BinarySensorEntity=BinarySensorEntity,
        BinarySensorDeviceClass=BinarySensorDeviceClass,
    )
    ha.helpers = module("homeassistant.helpers")
    ha.helpers.update_coordinator = module(
        "homeassistant.helpers.update_coordinator", CoordinatorEntity=CoordinatorEntity
    )
    ha.helpers.entity_platform = module(
        "homeassistant.helpers.entity_platform", AddEntitiesCallback=object
    )
    ha.config_entries = module("homeassistant.config_entries", ConfigEntry=object)
    ha.core = module("homeassistant.core", HomeAssistant=object, callback=callback)
    return True


_register_bare_package()
HA_STUBBED = _install_ha_stubs()


# ---------------------------------------------------------------------------
# Capture fixture helpers
# ---------------------------------------------------------------------------

def load_capture():
    with FIXTURE.open() as fh:
        return json.load(fh)


def frames_of(capture, kind, pack_id):
    """All frames of one kind for one pack, in capture order, as bytes."""
    return [
        bytes.fromhex(f["frame_hex"])
        for f in capture["frames"]
        if f["kind"] == kind and f["pack_id"] == pack_id
    ]


@pytest.fixture(scope="session")
def capture():
    return load_capture()


@pytest.fixture(scope="session")
def dynamic_frames(capture):
    """pack_id -> list of dynamic (0x1620) frames."""
    return {pid: frames_of(capture, "dynamic", pid) for pid in (0, 1)}


@pytest.fixture(scope="session")
def setup_frames(capture):
    """pack_id -> list of setup (0x161E) frames."""
    return {pid: frames_of(capture, "setup", pid) for pid in (0, 1)}


def make_bms():
    """A JKBMS485 with its caches but without the listener thread or a port."""
    from custom_components.gobel_battery.jkbms_rs485 import JKBMS485

    bms = JKBMS485.__new__(JKBMS485)
    bms.bms_comm = None
    bms.ha_comm = None
    bms.ha_comm_jk = None
    bms.bms_type = "JK_PB"
    bms.data_refresh_interval = 5
    bms.debug = 0
    bms.if_random = 0
    bms.pack_index_start = 0
    bms.logger = logging.getLogger("tests.jkbms")
    bms.REG_STATIC = 0x161C
    bms.REG_SETUP = 0x161E
    bms.REG_DYNAMIC = 0x1620
    bms.pack_energy = {}
    bms.setup_cache = {}
    bms.static_cache = {}
    bms.dynamic_cache = {}
    bms.cache_lock = threading.Lock()
    bms.is_first_poll = False
    bms.running = False
    return bms


@pytest.fixture
def bms():
    return make_bms()


@pytest.fixture
def loaded_bms(bms, dynamic_frames, setup_frames):
    """A BMS whose caches hold every captured frame, last frame winning."""
    for pid in (0, 1):
        for frame in dynamic_frames[pid]:
            bms._handle_valid_frame(frame, 0x1620, pid)
        for frame in setup_frames[pid]:
            bms._handle_valid_frame(frame, 0x161E, pid)
    return bms


# Values decoded independently from the capture (section 7 of the P4b notes).
EXPECTED_RESISTANCES = {
    0: [58, 60, 69, 69, 83, 88, 100, 106, 92, 76, 84, 69, 66, 63, 61, 53],
    1: [122, 105, 84, 66, 67, 65, 64, 60, 64, 62, 66, 62, 64, 63, 67, 86],
}
# From the last dynamic frame of each pack (the one the cache keeps).
EXPECTED_AVG = {0: 3178, 1: 3189}
EXPECTED_DELTA = {0: 21, 1: 21}
EXPECTED_MAX_CELL = {0: 15, 1: 2}   # 1-based
EXPECTED_MIN_CELL = {0: 1, 1: 7}    # 1-based
EXPECTED_RUNTIME = {0: 24558769, 1: 71392852}
EXPECTED_MOS = {"charge": True, "discharge": True, "balance": False}
