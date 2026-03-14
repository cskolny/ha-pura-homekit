# Changelog

All notable changes to **ha-pura-homekit** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] — 2026-03-14

### Fixed

- **Correct Pura REST API endpoint** — replaced the assumed GraphQL URL
  (`api.pura.com/graphql`) with the real REST base URL (`https://trypura.io/mobile/api/`).
  The previous URL did not resolve in DNS and prevented all API calls.
- **Device discovery** — the `GET v2/users/devices` response is a dict keyed by
  device form-factor (`car`, `mini`, `plus`, `wall`), not a flat list. Parser
  now flattens all values so devices of every type are discovered. Previously
  returned zero devices for all accounts.
- **Correct live on/off state** — devices were incorrectly showing as "on" when
  they were off. Root cause: the parser was reading `deviceDefaults.bay1Intensity`
  (the *default intensity setting*) as live intensity. Fixed to use
  `deviceDefaults.bay` (`0` = off, `1`/`2` = active bay) as the live state
  indicator, which is confirmed from real device responses.
- **Correct device name** — name is now read from `displayName.name` (the
  user-assigned room name) instead of a non-existent top-level `name` field.
- **Correct nightlight state** — nightlight on/off, brightness, and colour are
  now read from `deviceDefaults.nightlight` where the live values actually live.
- **Correct fragrance colour** — `placeholderColor` in the API response is a
  hex string without a `#` prefix (e.g. `"A91D3D"`). Parser now prepends `#`
  correctly.
- **Correct bay parsing** — bays are top-level keys `bay1` / `bay2` on the
  device object, not an array. Both bays are parsed and the fragrance info
  for each is extracted from the nested `fragrance` object.
- **`pycognito` replaces broken `warrant` dependency** — `warrant==0.6.1` has
  an unsolvable dependency conflict (`python-jose-cryptodome` requires two
  conflicting versions of `pycryptodome`) and could not be installed. Replaced
  with `pycognito==2024.5.1`, the same library used by pypura, maintained by
  NabuCasa. `boto3` dependency also removed.
- **Cognito auth using `Cognito` object directly** — previous implementation
  incorrectly accessed `.cognito` on a `RequestsSrpAuth` object (attribute does
  not exist). Rewrote auth to store the `pycognito.Cognito` user object directly
  and call `check_token()` in an executor for automatic token refresh.
- **`stop-all` endpoint used for turn-off** — turning a device off now calls
  `POST devices/{id}/stop-all` (the dedicated endpoint) rather than setting
  intensity to 0 on each bay individually.
- **`coordinator.py` passes bay/nightlight data to write calls** — the Pura
  write endpoints require a `controller` string from the device state. Coordinator
  now retrieves current bays and nightlight from cached data and passes them
  through to the API client so write calls include the correct controller value.
- **`aiohttp.ClientResponseError` (401) caught as `ConfigEntryAuthFailed`** —
  auth token expiry during polling now triggers HA's re-auth flow correctly
  instead of being swallowed as a generic `UpdateFailed`.

### Added

- **`deploy.sh` `--env` flag** — deploy script now supports two target
  environments: `production` (container `homeassistant`, port 8123, config
  `./config`) and `test` (container `homeassistant_test`, port 8124, config
  `./config_test`). Usage: `./deploy.sh --env test`.
- **`PURA_API.md`** — comprehensive reverse-engineered API reference covering
  all confirmed endpoints, full device object schema with field descriptions,
  intensity scale mapping, live state vs. default state distinction,
  authentication flow, write call payloads, and WebSocket endpoint.

### Changed

- **`manifest.json`** — requirements updated from `warrant==0.6.1` + `boto3`
  to `pycognito==2024.5.1`.
- **`const.py`** — `PURA_API_URL` corrected from `https://api.pura.com/graphql`
  to `https://trypura.io/mobile/api/`. Pura Cognito constants (`USER_POOL_ID`,
  `CLIENT_ID`) are now filled in with their decoded values — no manual
  extraction step required.

### Technical Notes
- Confirmed against live responses from three Pura 4 (`wall` type) devices.
- Full device response schema documented in `PURA_API.md`.

---

## [1.0.0] — 2026-03-14

### Added

#### Core Integration
- Standalone Home Assistant custom integration — **no dependency on ha-pura or any other HACS integration**.
- Direct Pura cloud API client (`pura_api.py`) using AWS Cognito `USER_SRP_AUTH` authentication with automatic token refresh.
- `DataUpdateCoordinator` (`coordinator.py`) with 30-second cloud polling and 1-second optimistic state updates after every command.

#### Humidifier Platform
- Each Pura 4 diffuser exposes as a **Humidifier** accessory in HomeKit via the HA HomeKit Bridge integration.
- Fan intensity mapped to HomeKit humidity percentage:
  | Pura Level | HomeKit Humidity % | HA Mode  |
  |-----------|--------------------| ---------|
  | Off       | 0 %                | —        |
  | Subtle    | 33 %               | subtle   |
  | Medium    | 66 %               | medium   |
  | Strong    | 100 %              | strong   |
- Humidity slider snaps to nearest defined intensity step.
- `turn_on` restores the last-used intensity level (defaults to `subtle` on first use).
- Full support for `humidifier.set_humidity`, `humidifier.set_mode`, `humidifier.turn_on`, `humidifier.turn_off` HA services.

#### Light Platform
- Each Pura 4 nightlight exposes as a **Light** accessory in HomeKit.
- Supports on/off, brightness (HA 0-255 mapped to Pura 1-10 scale), and full RGB colour (HS colour mode).
- Light entity is skipped automatically on devices that do not have a nightlight.

#### Config Flow
- Two-step UI config flow: Pura account credentials → device picker.
- Credential validation at setup time with clear, actionable error messages.
- Prevents duplicate config entries for the same physical device.
- One config entry per diffuser.

#### Developer Experience
- `deploy.sh` — one-command deploy to Raspberry Pi via rsync + SSH.
- GitHub Actions CI: ruff lint, mypy type-check, hassfest validation on every push/PR.
- GitHub Actions release: auto-packages `pura_homekit.zip` on version tag push.
- 46 unit tests covering data models, intensity/humidity mapping, brightness conversion, and RGB colour conversion.
- Full VSCode workspace configuration.
- ESPHome migration path: `PuraApiClient` is the only cloud-touching class.

---

[1.1.0]: https://github.com/cskolny/ha-pura-homekit/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/cskolny/ha-pura-homekit/releases/tag/v1.0.0