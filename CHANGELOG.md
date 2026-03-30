# Changelog

All notable changes to **ha-pura-homekit** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [1.2.0] — 2026-03-30

### Fixed

- **Diffuser now turns on correctly from HA / HomeKit** — the root cause was
  that `POST devices/{id}/intensity` only updates the stored default intensity
  setting in the Pura cloud; it does not command the physical device to start
  diffusing.  Confirmed from pypura v2.1.1 source (`pura.py`): the correct
  turn-on sequence is (1) `POST /intensity` to set the level, then (2)
  `POST /always-on` with `{"bay": 1}` to actually start the device.
  All previous attempts (`/timer`, `active: True` on intensity, sending to
  all bays simultaneously) were confirmed non-functional against the live API.

- **Nightlight 400 Bad Request on turn-on** — the Pura nightlight endpoint
  requires the `color` field as a bare hex string without the `#` prefix
  (e.g. `"FFFFFF"` not `"#ffffff"`).  Colours are stored internally with
  `#` for compatibility with HA colour utilities; the prefix is now stripped
  before the API payload is sent.

- **Diffuser flickering off immediately after turn-on** — the HA humidifier
  component emits a spurious `set_humidity(0)` call alongside `turn_on`
  when `target_humidity` is 0 % (the device is off).  `set_humidity(0)` was
  calling `stop-all`, which immediately reversed the turn-on command.
  Fixed with two guards:
  - `async_set_humidity` now treats `humidity=0` as a no-op (or restores
    the last-used intensity) when the device is on, rather than turning it
    off.  Explicit turn-off always goes through `async_turn_off`.
  - `target_humidity` now floors to 33 % (subtle) whenever `is_on` is
    `True`, so the HA slider never sits at 0 % while the device is on and
    the spurious `set_humidity(0)` call is never emitted in the first place.

- **Post-command re-poll was overwriting optimistic state** — after every
  command, `_optimistic_refresh` was sleeping 1 second then calling
  `async_request_refresh()`.  The Pura cloud takes several seconds to
  reflect a command, so the re-poll returned the pre-command state and
  overwrote the optimistic patch, making the UI flicker back to the old
  value.  Removed the re-poll entirely; the regular 30-second coordinator
  poll now confirms state from the cloud once the device has had time to
  process the command.

### Added

- **Comprehensive API debug logging** — every outbound request now logs its
  full payload, and every response logs its HTTP status and body.  On 4xx
  responses, the error body is logged before the exception is raised, making
  API rejections immediately visible without enabling network tracing.  The
  `_parse_device` path logs `deviceDefaults.bay` and both bay intensity
  strings on every poll so live on/off state can be verified at a glance.

### Changed

- **Turn-on path now state-aware** — `async_set_intensity` in the coordinator
  reads `device.is_on` before issuing a command.  When the device is off it
  uses the two-step `always-on` sequence.  When the device is already on it
  updates all bays via `/intensity` to keep oscillation-multi-bay mode in
  sync, which is unchanged from v1.1.0.

---

## [1.1.0] — 2026-03-14

### Fixed

- **Correct Pura REST API endpoint** — replaced the assumed GraphQL URL
  (`api.pura.com/graphql`) with the confirmed REST base URL
  (`https://trypura.io/mobile/api/`). The previous URL did not resolve in DNS
  and prevented all API calls.
- **Device discovery** — the `GET v2/users/devices` response is a dict keyed
  by device form-factor (`car`, `mini`, `plus`, `wall`), not a flat list.
  Parser now flattens all values so devices of every type are discovered.
- **Correct live on/off state** — fixed to use `deviceDefaults.bay`
  (`0` = off, `1`/`2` = active bay slot) as the live state indicator.
- **Correct device name** — now read from `displayName.name`.
- **Correct nightlight state** — now read from `deviceDefaults.nightlight`.
- **Correct fragrance colour** — `placeholderColor` in the API response is a
  hex string without a `#` prefix; parser now prepends `#` correctly.
- **Correct bay parsing** — bays are top-level keys `bay1`/`bay2` on the
  device object, not an array.
- **`pycognito` replaces broken `warrant` dependency**.
- **Cognito auth rewritten** — stores the `pycognito.Cognito` user object
  directly and calls `check_token()` in an executor for automatic refresh.
- **`stop-all` endpoint used for turn-off**.
- **Coordinator passes bay/nightlight data to write calls** — ensures the
  correct `controller` value is included.
- **`aiohttp.ClientResponseError` (401) raised as `ConfigEntryAuthFailed`**.

### Added

- **`deploy.sh` `--env` flag** — supports `production` and `test` targets.
- **`PURA_API.md`** — comprehensive reverse-engineered API reference.

### Changed

- **`manifest.json`** — requirements updated to `pycognito==2024.5.1`.
- **`const.py`** — `PURA_API_URL` corrected; Cognito constants filled in.

---

## [1.0.0] — 2026-03-14

### Added

- Initial release — standalone HA custom integration with direct Pura cloud
  API access.
- Humidifier platform: fan intensity mapped to HomeKit humidity percentage.
- Light platform: nightlight on/off, brightness, and RGB colour.
- Two-step config flow: credentials → device picker.
- `DataUpdateCoordinator` with 30-second polling.
- `deploy.sh` for one-command Raspberry Pi deployment.

---

[Unreleased]: https://github.com/cskolny/ha-pura-homekit/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/cskolny/ha-pura-homekit/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/cskolny/ha-pura-homekit/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/cskolny/ha-pura-homekit/releases/tag/v1.0.0
