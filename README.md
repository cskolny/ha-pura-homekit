# Pura HomeKit Bridge — Home Assistant Custom Integration

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.3%2B-blue?logo=homeassistant)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Release](https://img.shields.io/github/v/release/cskolny/ha-pura-homekit)](https://github.com/cskolny/ha-pura-homekit/releases)

Control your **Pura 4 smart fragrance diffusers** from Apple HomeKit — no third-party integrations, no HACS dependencies. Each diffuser appears as a **Humidifier** accessory with intensity mapped to humidity percentage, and the device nightlight appears as a **Light** accessory with full brightness and colour control.

## How It Works

```
Apple Home App
      │  HAP (HomeKit Accessory Protocol)
      ▼
HomeKit Bridge  (HA built-in integration)
      │  HA humidifier / light service calls
      ▼
pura_homekit  (this integration)
  ├── coordinator.py   polls Pura cloud API every 30s
  ├── pura_api.py      authenticates via AWS Cognito + GraphQL
  ├── humidifier.py    intensity → humidity % entity
  └── light.py         nightlight on/off, brightness, RGB entity
      │  HTTPS / GraphQL
      ▼
Pura Cloud API  (api.pura.com)
      │  WiFi
      ▼
Pura 4 Diffuser
```

Authentication uses your Pura email and password — the same credentials you use in the Pura mobile app. Tokens are refreshed automatically; your password is stored encrypted by Home Assistant and never sent anywhere except Pura's own AWS Cognito service.

**Intensity → Humidity mapping:**

| Pura Level | HomeKit Humidity % | HA Mode  |
|-----------|---------------------|----------|
| Off       | 0 %                 | —        |
| Subtle    | 33 %                | subtle   |
| Medium    | 66 %                | medium   |
| Strong    | 100 %               | strong   |

The HomeKit humidity slider snaps to the nearest defined step — so dragging to any value always lands cleanly on off, subtle, medium, or strong.

---

## Features

- 🌿 **Humidifier accessory** — on/off and intensity control via HomeKit humidity slider
- 💡 **Nightlight accessory** — on/off, brightness, and full RGB colour control
- 🔑 **Direct Pura API** — no ha-pura or any other dependency; owns the full auth stack
- 🔄 **30-second polling** with 1-second optimistic UI updates after every command
- ↩️ **Intensity memory** — turning a diffuser back on restores the last-used intensity
- ⚙️ **Full config flow** — set up entirely from the HA UI, no `configuration.yaml` changes
- 🔒 **Encrypted credential storage** — passwords stored by HA's built-in config entry store
- 🛣️ **ESPHome migration path** — API client layer is isolated; swap in a local client when ready
- 🚀 **`deploy.sh`** — one-command deployment to your Raspberry Pi

---

## Requirements

- Home Assistant running in Docker (Container install) **2026.3 or later**
- HomeKit Bridge integration enabled in Home Assistant
- A Pura account with **email + password** login

> **Social login note:** If you registered with Apple, Google, or Facebook you must set a password before using this integration. Open the Pura app → Settings → sign out → "Sign into your account" → "Forgot your password?" and follow the steps.

---

## Installation

### Manual

1. Copy the `custom_components/pura_homekit/` folder into your HA config directory:
   ```
   config/
   └── custom_components/
       └── pura_homekit/
           ├── __init__.py
           ├── coordinator.py
           ├── pura_api.py
           ├── entity.py
           ├── humidifier.py
           ├── light.py
           ├── config_flow.py
           ├── const.py
           ├── manifest.json
           ├── strings.json
           └── translations/
               └── en.json
   ```

2. Restart Home Assistant.

3. Go to **Settings → Devices & Services → Add Integration → Pura HomeKit Bridge**

4. Enter your Pura email and password — the integration validates them immediately.

5. Select the diffuser to add. Repeat for each additional diffuser (each gets its own config entry).

### HACS (Custom repository)

1. In HACS → Integrations → three-dot menu → **Custom repositories**
2. Add `https://github.com/cskolny/ha-pura-homekit` with category **Integration**
3. Search for "Pura HomeKit Bridge" and install
4. Restart Home Assistant, then follow steps 3–5 above

---

## HomeKit Bridge Setup

After the integration is configured, include the new entities in HomeKit Bridge so they appear in the Apple Home app.

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

Scan the QR code shown in the HomeKit Bridge integration card to pair with the Apple Home app. Each configured diffuser will appear as a **Humidifier** accessory and a separate **Nightlight** light accessory.

---

## Usage

Once set up, each Pura 4 appears in HomeKit with two accessories:

| Accessory | Type | Controls |
|-----------|------|----------|
| `Living Room Diffuser` | Humidifier | On/Off, humidity slider (0 / 33 / 66 / 100 %) |
| `Living Room Diffuser Nightlight` | Light | On/Off, brightness, colour |

### Automations

Standard HA service calls work on both entity types:

```yaml
# Turn on at medium intensity
service: humidifier.set_humidity
target:
  entity_id: humidifier.living_room_diffuser
data:
  humidity: 66

# Turn on at strong via named mode
service: humidifier.set_mode
target:
  entity_id: humidifier.living_room_diffuser
data:
  mode: strong

# Turn off
service: humidifier.turn_off
target:
  entity_id: humidifier.living_room_diffuser

# Set nightlight to warm amber at 60% brightness
service: light.turn_on
target:
  entity_id: light.living_room_diffuser_nightlight
data:
  brightness_pct: 60
  color_name: orange
```

---

## Entities

For each configured Pura 4 diffuser this integration creates two entities:

| Entity ID | Domain | Description |
|-----------|--------|-------------|
| `humidifier.pura_<name>` | `humidifier` | Diffuser on/off + intensity |
| `light.pura_<name>_nightlight` | `light` | Nightlight on/off, brightness, RGB |

> The nightlight entity is skipped automatically on any device that does not report nightlight hardware in the Pura API response.

---

## Deploying to Raspberry Pi

The `deploy.sh` script in the repository root rsyncs the integration to your Pi and optionally restarts Home Assistant in one command:

```bash
# Full deploy + HA restart
./deploy.sh

# Deploy files only — restart manually later
./deploy.sh --skip-restart
```

The script stamps `manifest.json` with the current git SHA on every deploy, which prevents Home Assistant from serving a stale cached version of the integration during development.

---

## Log Files

| Location | Contents |
|----------|----------|
| HA logs (`Settings → System → Logs`) | API polling results, command errors, token refresh events |
| Debug logs (see below) | Full GraphQL request/response detail |

Enable debug logging for detailed output:

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.pura_homekit: debug
```

---

## Troubleshooting

**"Invalid email or password" at setup**
- Verify credentials in the Pura mobile app.
- If you registered with Apple/Google/Facebook, you must set a password first — see the social login note in Requirements above.

**Device shows unavailable in HA or HomeKit**
- The Pura device is offline or out of WiFi range. Check the Pura app.
- If all three devices go unavailable simultaneously, the Pura cloud API may be down.

**Intensity not changing after a command**
- Check HA logs for API errors (`Settings → System → Logs`).
- Enable debug logging (see above) for full detail.

**Nightlight entity missing**
- Your device does not report nightlight hardware in the API response. The entity is intentionally skipped.

**HomeKit shows stale state**
- The integration polls every 30 seconds. Wait one poll cycle or trigger a manual refresh via Developer Tools → States.

---

## Complementary Projects

This integration is part of a suite of Home Assistant custom components sharing the same code style, coordinator pattern, and config-flow structure:

- **[HA Docker Updater](https://github.com/cskolny/ha-docker-updater)** — update your HA Docker container from the HA UI
- **[Green Button Energy Import](https://github.com/cskolny/ha-green-button-energy)** — import utility energy data from Green Button CSV files

---

## License

MIT License — see [LICENSE](LICENSE) for details.