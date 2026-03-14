# Changelog

All notable changes to **ha-pura-homekit** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- Humidity slider snaps to nearest defined intensity step (handles arbitrary 0-100 slider values from HomeKit).
- `turn_on` restores the last-used intensity level (defaults to `subtle` on first use).
- Full support for `humidifier.set_humidity`, `humidifier.set_mode`, `humidifier.turn_on`, `humidifier.turn_off` HA services.

#### Light Platform
- Each Pura 4 nightlight exposes as a **Light** accessory in HomeKit.
- Supports on/off, brightness (HA 0-255 mapped to Pura 1-10 scale), and full RGB colour (HS colour mode).
- Light entity is skipped automatically on devices that do not have a nightlight.

#### Config Flow
- Two-step UI config flow: Pura account credentials → device picker.
- Credential validation at setup time — surfaces authentication errors with clear, actionable messages.
- Prevents duplicate config entries for the same physical device via unique ID enforcement.
- One config entry per diffuser; run setup again for each additional Pura 4.

#### Developer Experience
- `deploy.sh` — one-command deploy to Raspberry Pi via rsync + SSH with `--skip-restart` flag support.
- GitHub Actions CI workflow: ruff lint, mypy type-check, hassfest validation on every push/PR.
- GitHub Actions release workflow: auto-packages `pura_homekit.zip` and publishes a GitHub Release on version tag push.
- 46 unit tests covering data models, intensity/humidity mapping, brightness conversion, and RGB colour conversion.
- Full VSCode workspace configuration (Ruff formatter, Python type-checking, recommended extensions).
- Structured for ESPHome migration: `PuraApiClient` is the only cloud-touching class — swap it for a local client without touching any entity or coordinator code.

### Technical Notes
- Requires `warrant` and `boto3` packages for Cognito SRP authentication (declared in `manifest.json`).
- `PURA_USER_POOL_ID` and `PURA_CLIENT_ID` must be populated in `const.py` before first use — see README for extraction instructions.
- Tested against Home Assistant 2026.3.1 (Container) with HomeKit Bridge on Raspberry Pi.

---

<!-- next release goes here

## [Unreleased]

### Added
### Changed
### Fixed
### Removed

-->

[1.0.0]: https://github.com/yourusername/ha-pura-homekit/releases/tag/v1.0.0
