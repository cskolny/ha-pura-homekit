---
name: ha-pura-homekit
globs: "**/*.py"
alwaysApply: false
description: Rules for the ha-pura-homekit HA integration
---

# ha-pura-homekit

- Domain: `pura_homekit`
- Bridges Pura diffusers via HomeKit Accessory Protocol (HAP)
- Pairing state in config_entry — never re-pair on reload
- HAP characteristic UUIDs documented in const.py with comments
- Pairing codes NEVER logged — use REDACTED substitution
- device_info: manufacturer="Pura", model from HAP accessory info
- unique_id pattern: `{domain}_{device_id}_{characteristic}`