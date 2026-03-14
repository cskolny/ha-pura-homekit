# Pura API Reference

Reverse-engineered from the [pypura](https://github.com/natekspencer/pypura) library
and confirmed against live API responses from three Pura 4 devices.

---

## Authentication

Pura uses **AWS Cognito USER_SRP_AUTH** — a zero-knowledge password proof
that never sends your password in plaintext.

| Constant | Value | Source |
|----------|-------|--------|
| `USER_POOL_ID` | `us-east-1_LaB718hYv` | base64-decoded from `pypura/const.py` |
| `CLIENT_ID` | `4iekubat0jb5iljfbaalsiqf9j` | base64-decoded from `pypura/const.py` |
| Region | `us-east-1` | inferred from pool ID |

### Flow

```
1. pycognito.Cognito(user_pool_id, client_id, region, username)
2. user.authenticate(password=password)
   → AWS Cognito performs SRP challenge/response exchange
   → Populates: user.id_token, user.access_token, user.refresh_token
3. id_token (JWT) used as Bearer token on all API requests
4. user.check_token() called before each request to auto-refresh if near expiry
```

### Auth header

```
Authorization: Bearer <id_token>
Content-Type: application/json
```

---

## Base URL

```
https://trypura.io/mobile/api/
```

All paths below are relative to this base.

---

## Endpoints

### GET `v2/users/devices`

Returns all devices on the authenticated account, grouped by form factor.

**Response shape:**
```json
{
  "car":  [],
  "mini": [],
  "plus": [],
  "wall": [ <device>, <device>, ... ]
}
```

The keys represent Pura device form factors:
| Key | Device type |
|-----|-------------|
| `wall` | Pura 4 (wall plug) |
| `plus` | Pura Plus |
| `mini` | Pura Mini |
| `car`  | Pura Car |

Your Pura 4 devices appear under `wall`. Collect all values from all keys to
support accounts with mixed device types.

---

### POST `devices/{deviceId}/intensity`

Set the diffusion intensity for one bay.

**Request body:**
```json
{
  "bay":        1,
  "controller": "default",
  "intensity":  5
}
```

| Field | Type | Description |
|-------|------|-------------|
| `bay` | int | Slot number: `1` or `2` |
| `controller` | string | Always `"default"` for Pura 4 (from `device.controller`) |
| `intensity` | int | `0` = off, `1–10` = diffusing (see intensity scale below) |

**Response:** `{"success": true}` on success.

---

### POST `devices/{deviceId}/stop-all`

Stops all bays immediately. Equivalent to setting intensity=0 on all bays
but uses the dedicated endpoint pypura exposes.

**Request body:** empty `{}`

**Response:** `{"success": true}`

---

### POST `devices/{deviceId}/nightlight`

Set the nightlight state.

**Request body:**
```json
{
  "active":     true,
  "brightness": 7,
  "color":      "FFFFFF",
  "controller": "default"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `active` | bool | `true` = on, `false` = off |
| `brightness` | int | `1–10` |
| `color` | string | Hex colour **without** `#` prefix, e.g. `"FF8800"` |
| `controller` | string | Always `"default"` for Pura 4 |

**Response:** `{"success": true}`

---

## Device Object (full schema)

Confirmed from live Pura 4 response.

```jsonc
{
  // ── Identity ──────────────────────────────────────────────────────────
  "deviceId":    "24DCC3221124",        // MAC-address-style unique ID
  "deviceVer":   "v48",                 // device firmware generation
  "fwVersion":   "7.5.3",              // firmware version string
  "hwVersion":   "4.3",                // hardware revision
  "model":       1,                    // internal model int (1 = Pura 4)
  "controller":  "default",            // used in all write calls

  // ── Display ───────────────────────────────────────────────────────────
  "displayName": {
    "name": "Upstairs Diffuser",       // user-assigned room name ← USE THIS
    "type": "hallway"                  // room type label
  },

  // ── Connectivity ──────────────────────────────────────────────────────
  "connected":           true,
  "disconnectReason":    null,
  "lastConnectedAt":     null,
  "lastDisconnectedAt":  null,
  "wifi": {
    "rssi": "good",                    // "excellent" | "good" | "fair" | "poor"
    "ssid": "ASUS"
  },

  // ── Live state ────────────────────────────────────────────────────────
  // THIS is how you determine if the device is on or off:
  "deviceDefaults": {
    "bay":           0,                // ← LIVE ACTIVE BAY: 0=off, 1=bay1, 2=bay2
    "bay1Intensity": "subtle",         // default intensity when bay1 turns on
    "bay2Intensity": "subtle",         // default intensity when bay2 turns on
    "nightlight": {
      "active":     false,             // ← LIVE nightlight on/off
      "brightness": 10,                // ← LIVE brightness (1-10)
      "color":      "FFFFFF"           // ← LIVE colour, hex WITHOUT #
    }
  },

  "diffusionMode": "oscillation-multi-bay",  // "standard" | "oscillation-multi-bay"
  "ambientMode":   false,
  "oscillation":   null,
  "timer":         null,              // null = no active timer

  // ── Bay 1 ─────────────────────────────────────────────────────────────
  "bay1": {
    "activeAt":    0,                  // unix timestamp when activated, 0 = inactive
    "wearingTime": 179237,             // total seconds this vial has diffused
    "code":        "VNTH",             // fragrance code
    "vialId":      "E002080997552700", // physical vial serial
    "id":          1764538900,
    "isSmartVial": true,
    "lowFragrance": false,
    "remaining": {
      "percent":      71,
      "days":         "16-18 days",
      "lowFragrance": false
    },
    "fragrance": {
      "id":              "19798333-4480-43ff-81d9-cf223b7f4550",
      "name":            "Holiday",
      "brandName":       "NEST",
      "description":     "The quintessential aroma of the season",
      "fragranceCode":   "VNTH",
      "placeholderColor": "A91D3D",    // hex WITHOUT # — use as display colour
      "fragranceFormat": "vial",
      "expectedLifeHours": 147,
      "productId":       "7052695994477",
      "productHandle":   "holiday",
      "variantId":       "40703042551917",
      "sqImgUrl":        "https://cdn.shopify.com/...",
      "vialUrl":         "https://cdn.shopify.com/...",
      "bgImgUrl":        "https://cdn.shopify.com/...",
      "bgScentImgUrl":   "https://cdn.shopify.com/...",
      "smellsLike":      ["cinnamon", "orange", "eucalyptus"],
      "feelsLike":       ["comforting", "cheerful", "bright"],
      "scentNotes": {
        "top":    ["fruity", "citrus", "pineapple"],
        "middle": ["spruce", "cinnamon", "clove"],
        "bottom": ["musk", "amber", "vanilla"]
      },
      "scentTypes": [
        {"name": "Amber", "iconUrl": "https://cdn.shopify.com/..."},
        {"name": "Fruity", "iconUrl": "https://cdn.shopify.com/..."}
      ]
    }
  },

  // ── Bay 2 (same shape as bay1) ────────────────────────────────────────
  "bay2": { "...": "same fields as bay1" },

  // ── Scheduling ────────────────────────────────────────────────────────
  "schedules": [
    {
      "id":    "2ee3b7fc-be29-407b-8afe-3794b96573dd",
      "name":  "Schedule 1",
      "bay":   1,
      "days": {
        "monday": true, "tuesday": true, "wednesday": true,
        "thursday": true, "friday": false, "saturday": false, "sunday": true
      },
      "start":         "0600",         // "HHMM" 24-hour
      "end":           "0700",
      "intensity":     "subtle",
      "disableUntil":  1773140400,     // unix timestamp — schedule paused until this time
      "number":        0,
      "nightlight": {
        "active": true, "brightness": 10, "color": "FFFFFF"
      }
    }
  ],

  // ── Other fields ──────────────────────────────────────────────────────
  "awayMode":    {"away": false, "enabled": false},
  "setupComplete": true,
  "onboardedAt": 1722549569,           // unix timestamp
  "position":    2,                    // display order in the app
  "deviceLocation": {"timezone": "America/New_York"},
  "roomProfile": {
    "name":   "Hallway",
    "type":   "hallway",
    "size":   {"id": 2, "label": "Medium", "value": "8 x 12 ft"},
    "height": {"id": 0, "label": "8 ft or lower", "value": "8 ft or lower"}
  },
  "capabilities": {
    "diffusionModes": ["standard", "oscillation-multi-bay"]
  },
  "ota": {"percent": 100, "status": "Finished"},
  "otaVer": 223592179
}
```

---

## Intensity Scale

The API uses integers `0–10` for intensity in write calls and string labels
in `deviceDefaults`.

| String label | Integer value | HomeKit humidity % | Description |
|-------------|---------------|-------------------|-------------|
| `"off"`     | `0`           | `0 %`             | Not diffusing |
| `"subtle"`  | `2`           | `33 %`            | Low intensity |
| `"medium"`  | `5`           | `66 %`            | Medium intensity |
| `"strong"`  | `8`           | `100 %`           | High intensity |

The integer values `2`, `5`, `8` are the midpoints of each band (Pura accepts
`1–3` for subtle, `4–6` for medium, `7–10` for strong).

---

## Live State vs. Default State

This is the most important subtlety in the API:

| Field | What it means |
|-------|---------------|
| `deviceDefaults.bay` | **Live state**: `0` = off, `1` = bay 1 active, `2` = bay 2 active |
| `deviceDefaults.bay1Intensity` | **Setting**: intensity to use when bay 1 is turned on |
| `deviceDefaults.bay2Intensity` | **Setting**: intensity to use when bay 2 is turned on |
| `deviceDefaults.nightlight.active` | **Live state**: whether the nightlight is on right now |
| `bay1.activeAt` | Unix timestamp when bay 1 became active; `0` = not active |
| `bay2.activeAt` | Unix timestamp when bay 2 became active; `0` = not active |

A device with `deviceDefaults.bay=0` is **off** even if `bay1Intensity="medium"`.
The intensity string is simply what intensity will be used the *next time* it turns on.

---

## WebSocket (Real-time Updates)

Pura also exposes a WebSocket endpoint for real-time state push:

```
wss://socket.trypura.io
```

**Connection headers:**
```
Authorization: Bearer <id_token>
```

Messages are JSON. The integration currently uses REST polling (30s) rather
than the WebSocket because the message schema is not fully documented.
Adding WebSocket support would eliminate polling latency.

---

## Notes

- `deviceId` is in the format of a MAC address without separators: `"24DCC3221124"`
- Colour values throughout are hex strings **without** the `#` prefix
- The `controller` field on a device is always `"default"` for Pura 4; it must
  be passed back verbatim in all write calls
- `timer: null` means no active timer; a running timer looks like
  `{"bay": 1, "start": <ts>, "end": <ts>, "intensity": "subtle"}`
- Schedules with `disableUntil` set to a future timestamp are paused
