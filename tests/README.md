# Tests

Unit tests for the JK BMS parser, `get_analog_data()` and the sensor / binary
sensor entity classes. They run without Home Assistant installed (minimal
stand-ins for the base classes are provided by `conftest.py`); with Home
Assistant on the path the real classes are used instead.

```bash
uv run --with pytest python -m pytest
```

`fixtures/waveshare-jk-raw-frames-2026-10-30_22-12-04.json` is a 30 s passive
capture of two JK_PB packs behind an RS485/Ethernet bridge: twelve 300-byte
frames, three dynamic (0x1620) and three setup (0x161E) per pack. No static
(0x161C) frame, so no serial number or identification data.
