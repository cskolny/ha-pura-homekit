# ha-pura-homekit

[![Release](https://img.shields.io/github/v/release/yourusername/ha-pura-homekit?style=for-the-badge)](https://github.com/yourusername/ha-pura-homekit/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/yourusername/ha-pura-homekit/ci.yml?style=for-the-badge&label=CI)](https://github.com/yourusername/ha-pura-homekit/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

**Standalone** Home Assistant custom integration that bridges [Pura 4](https://pura.com) smart fragrance diffusers directly into **Apple HomeKit** as humidifier and light accessories.

> **No dependency on ha-pura or any other HACS integration.** This project owns the complete stack from Pura cloud API authentication all the way to the HomeKit accessory — giving you full end-to-end control.

---

## Features

| Feature | Details |
|---------|---------|
| **Humidifier accessory** | On/Off + intensity via HomeKit humidity % |
| **Intensity mapping** | off → 0 %, subtle → 33 %, medium → 66 %, strong → 100 % |
| **Fragrance modes** | subtle / medium / strong available as HA humidifier modes |
| **Nightlight accessory** | On/Off, brightness (1-10), and full RGB colour |
| **Polling** | 30-second cloud poll with 1-second optimistic UI update |
| **Multi-device** | One config entry per diffuser; three entries for three Pura 4 units |
| **ESPHome ready** | Client layer is isolated so a local ESPHome client can be swapped in |

---

## How HomeKit Sees It

```
Apple Home App
├── Living Room Diffuser      (Humidifier)
│     └── Humidity slider: 0 % / 33 % / 66 % / 100 %
└── Living Room Diffuser Nightlight  (Light)
      ├── On / Off
      ├── Brightness
      └── Color
```

---

## Prerequisites

1. **Home Assistant** (Container or any install) **2026.3.1** or later
2. **HomeKit Bridge** integration enabled in Home Assistant
3. A **Pura account** with email + password login  
   *(If you registered via Apple/Google/Facebook you must set a password in the Pura app first — see Troubleshooting below)*

---

## Installation

### Manual (recommended for development)

```bash
# On your Mac — from the project root
rsync -avz --delete \
  custom_components/pura_homekit/ \
  pi@raspberrypi.local:/path/to/homeassistant/config/custom_components/pura_homekit/

# Restart HA
ssh pi@raspberrypi.local "docker restart homeassistant"
```

### HACS (once published)

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Add `https://github.com/yourusername/ha-pura-homekit` — type **Integration**
3. Install **Pura HomeKit Bridge**
4. Restart Home Assistant

---

## Configuration

1. **Settings → Devices & Services → Add Integration**
2. Search for **Pura HomeKit Bridge**
3. Enter your Pura email and password — the integration validates them immediately
4. Select the diffuser to add
5. Repeat for each additional diffuser (each gets its own config entry)

### HomeKit Bridge

After the integration is set up, include the new entities in HomeKit Bridge.

**Option A — filter in `configuration.yaml`:**
```yaml
homekit:
  filter:
    include_entity_globs:
      - humidifier.pura_*
      - light.pura_*
```

**Option B — add via UI:**  
Settings → Devices & Services → HomeKit Bridge → Configure → Manage Entities

Scan the QR code in Apple Home to add the bridge. Your diffusers will appear as **Humidifier** and **Light** accessories.

---

## Entity Reference

For each configured Pura 4 diffuser this integration creates:

| Entity ID | Domain | Description |
|-----------|--------|-------------|
| `humidifier.pura_<device_name>` | `humidifier` | Diffuser on/off + intensity |
| `light.pura_<device_name>_nightlight` | `light` | Device LED on/off, brightness, RGB |

---

## Intensity ↔ Humidity Mapping

| Pura Level | Raw Intensity | HomeKit Humidity % | HA Mode |
|-----------|---------------|--------------------|---------|
| Off       | 0             | 0 %                | —       |
| Subtle    | 2             | 33 %               | subtle  |
| Medium    | 5             | 66 %               | medium  |
| Strong    | 8             | 100 %              | strong  |

The raw intensity sent to the Pura API (`2`, `5`, `8`) matches the midpoint of each Pura intensity band.  All values in `const.py` so they're easy to adjust.

The HomeKit humidity slider can land on any value 0-100.  The integration snaps it to the nearest defined step (e.g. `50` → `medium`).

---

## Automations

```yaml
# Turn on at medium intensity
service: humidifier.set_humidity
target:
  entity_id: humidifier.living_room
data:
  humidity: 66

# Turn on at strong via named mode
service: humidifier.set_mode
target:
  entity_id: humidifier.living_room
data:
  mode: strong

# Turn off
service: humidifier.turn_off
target:
  entity_id: humidifier.living_room

# Set nightlight to warm amber
service: light.turn_on
target:
  entity_id: light.living_room_nightlight
data:
  brightness_pct: 60
  color_name: orange
```

---

## Architecture

```
Apple Home App
      │  HAP (HomeKit Accessory Protocol)
      ▼
HomeKit Bridge (HA built-in)
      │  HA humidifier / light service calls
      ▼
pura_homekit  (this integration)
  ├── __init__.py        – entry setup / teardown
  ├── coordinator.py     – DataUpdateCoordinator, owns the API client
  ├── pura_api.py        – PuraApiClient: Cognito auth + GraphQL calls
  ├── entity.py          – PuraEntity base (CoordinatorEntity)
  ├── humidifier.py      – PuraHumidifierEntity
  └── light.py           – PuraNightlightEntity
      │  HTTPS / GraphQL
      ▼
Pura Cloud API (api.pura.com/graphql)
      │  WiFi / MQTT
      ▼
Pura 4 Diffuser
```

### ESPHome Migration

The `PuraApiClient` in `pura_api.py` is the only cloud-touching class.  When you flash your Pura 4 devices with ESPHome:

1. Create `esphome_client.py` with the same interface (`async_get_devices`, `async_set_all_bays_intensity`, `async_set_nightlight`)
2. In `coordinator.py`, replace the `PuraApiClient` import with your new client
3. Update `config_flow.py` to collect the local IP / hostname instead of Pura credentials
4. The entities, coordinator logic, and HomeKit mapping remain unchanged

---

## Development

### Local Setup

```bash
git clone https://github.com/yourusername/ha-pura-homekit
cd ha-pura-homekit
python -m venv .venv
source .venv/bin/activate
pip install homeassistant ruff mypy pytest pytest-asyncio
```

### Lint, Type-check, Test

```bash
ruff check custom_components/
mypy custom_components/pura_homekit --ignore-missing-imports
pytest tests/ -v
```

### Deploy to Raspberry Pi

```bash
rsync -avz --delete \
  custom_components/pura_homekit/ \
  pi@raspberrypi.local:/path/to/homeassistant/config/custom_components/pura_homekit/

ssh pi@raspberrypi.local "docker restart homeassistant"
```

### Releasing

```bash
# 1. Bump version in manifest.json
# 2. Commit + push to main
git tag v1.0.0
git push origin v1.0.0
# GitHub Actions builds pura_homekit.zip and publishes the release automatically
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Invalid email or password" | If you registered with Apple/Google/Facebook, you must set a password: open the Pura app → Settings → sign out → "Sign into your account" → "Forgot your password?" |
| "Cannot connect" | Check internet connectivity; verify the Pura app works on the same network |
| Device shows unavailable | The Pura device is offline or out of WiFi range; check the Pura app |
| HomeKit shows wrong intensity | The raw intensity integers in `const.py` may differ from your firmware version — check HA state attributes after a manual change in the Pura app |
| Nightlight entity missing | Some older Pura models lack nightlight hardware; the entity is skipped when `nightlight` is absent from the API response |

**Enable debug logging:**
```yaml
# configuration.yaml
logger:
  logs:
    custom_components.pura_homekit: debug
```

---

## License

MIT — see [LICENSE](LICENSE)

---

## Credits

Pura API protocol research: [natekspencer/pypura](https://github.com/natekspencer/pypura) and [homebridge-plugins/homebridge-pura](https://github.com/homebridge-plugins/homebridge-pura)