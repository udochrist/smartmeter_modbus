# SmartMeter ModBus — Home Assistant Custom Integration

Integrates **Chint DDSU-666** (single-phase) and **DTSU-666** (three-phase) smart meters
connected via **Modbus RTU over TCP** (e.g. an Elwin Modbus/TCP converter).
Code can be adjusted to support other manufacturers / devices

---

## Features

| Feature | Details |
|---|---|
| Multiple adapters | Each Modbus gateway is its own config entry |
| Multiple meters per adapter | Add as many meters as your bus supports |
| Configurable per meter | Slave ID, vendor, model, friendly name |
| Auto-discovered entities | Every Modbus register becomes a HA sensor entity |
| Full device registry | Each meter appears as its own HA *Device* |
| Live polling | Default 30 s; reconnects automatically on drop |

---

## Supported Sensors

### Both models (DDSU-666 & DTSU-666)
- Voltage L1 · Current L1
- Active Power (total) · Reactive Power (total) · Apparent Power (total)
- Power Factor (total)
- Frequency
- Energy Import (total) · Energy Export (total)

### Three-phase only (DTSU-666)
- Voltage L2 / L3 · Current L2 / L3
- Active / Reactive Power L1–L3
- Power Factor L1–L3
- Energy Import L1–L3

---

## Installation

### HACS (recommended)
1. Add this repo as a **Custom Repository** in HACS (category: *Integration*).
2. Search for "SmartMeter ModBus" and install.
3. Restart Home Assistant.

### Manual
1. Copy the `custom_components/smartmeter_modbus` folder into your HA
   `config/custom_components/` directory.
2. Restart Home Assistant.

---

## Setup

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **SmartMeter ModBus**.
3. **Step 1 – Adapter**: Enter a name (e.g. `Elwin E11`), the IP address and
   TCP port (default `502`) of your Elwin converter.
4. **Step 2 – Meters**: Add one or more meters:
   - **Meter Name** – friendly name shown in HA (e.g. `Main Grid Meter`)
   - **Slave ID** – the Modbus device address (1–247) set on the meter
   - **Vendor** – `Chint`
   - **Model** – `DDSU-666` or `DTSU-666`
5. Choose **Finish** when done.

Repeat the whole flow to add a second Elwin adapter.

### Adding / removing meters later
Go to **Settings → Devices & Services**, find the adapter entry, and click **Configure**
to open the options flow. From there you can add or remove individual meters without
restarting Home Assistant.

---

## Multiple adapters example

```
Elwin Adapter A  (192.168.1.50:502)
  ├── slave 1  → DTSU-666  "Grid Import Meter"
  └── slave 2  → DDSU-666  "Solar Inverter"

Elwin Adapter B  (192.168.1.51:502)
  └── slave 1  → DTSU-666  "Sub-panel Kitchen"
```

Each adapter is a separate HA config entry; meters within an adapter share one
polling coordinator and one TCP connection.

---

## Modbus Register Map

All registers are read with **function code 0x03** (Read Holding Registers).
Values are stored as 32-bit IEEE-754 floats in two consecutive 16-bit registers
(big-endian word and byte order).

| Name | Address | Unit | Models |
|---|---|---|---|
| Voltage L1 | 0x2000 | V | All |
| Voltage L2 | 0x2002 | V | DTSU-666 |
| Voltage L3 | 0x2004 | V | DTSU-666 |
| Current L1 | 0x200A | A | All |
| Current L2 | 0x200C | A | DTSU-666 |
| Current L3 | 0x200E | A | DTSU-666 |
| Active Power Total | 0x2014 | W | All |
| Active Power L1–L3 | 0x2016–0x201A | W | DTSU-666 |
| Reactive Power Total | 0x201E | var | All |
| Reactive Power L1–L3 | 0x2020–0x2024 | var | DTSU-666 |
| Apparent Power Total | 0x2028 | VA | All |
| Power Factor Total | 0x202A | — | All |
| Power Factor L1–L3 | 0x202C–0x2030 | — | DTSU-666 |
| Frequency | 0x2044 | Hz | All |
| Energy Import Total | 0x4000 | kWh | All |
| Energy Import L1–L3 | 0x4002–0x4006 | kWh | DTSU-666 |
| Energy Export Total | 0x400A | kWh | All |

---

## Troubleshooting

| Symptom | Check |
|---|---|
| All sensors unavailable | Ping the Elwin IP; verify port 502 is reachable |
| Only some sensors unavailable | Slave ID mismatch; check meter DIP switches |
| Wrong values | Confirm byte/word order on your Elwin firmware |
| `pymodbus` import error | Ensure `pymodbus>=3.6` is installed (HA usually handles this) |

Enable debug logging:
```yaml
# configuration.yaml
logger:
  logs:
    custom_components.chint_smartmeter: debug
```
