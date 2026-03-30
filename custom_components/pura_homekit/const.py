"""Constants for the Pura HomeKit integration."""
from __future__ import annotations

# ── Integration identity ───────────────────────────────────────────────────────
DOMAIN = "pura_homekit"

# Platforms provided by this integration.
PLATFORMS: list[str] = ["humidifier", "light"]

# ── Pura cloud API - AWS Cognito ───────────────────────────────────────────────
# These are Pura's public app identifiers — not user credentials.
# Values decoded from pypura: base64.b64decode(pypura.const.USER_POOL_ID / CLIENT_ID)
PURA_COGNITO_REGION: str = "us-east-1"
PURA_USER_POOL_ID: str = "us-east-1_LaB718hYv"
PURA_CLIENT_ID: str = "4iekubat0jb5iljfbaalsiqf9j"

# Pura REST API base URL — trailing slash is required for path construction.
PURA_API_BASE_URL: str = "https://trypura.io/mobile/api/"

# Default polling interval in seconds (matches ha-pura reference implementation).
DEFAULT_SCAN_INTERVAL: int = 30

# ── Config-entry field keys ────────────────────────────────────────────────────
CONF_EMAIL: str = "email"
CONF_PASSWORD: str = "password"
CONF_DEVICE_ID: str = "device_id"
CONF_DEVICE_NAME: str = "device_name"

# ── Intensity ↔ HomeKit humidity mapping ──────────────────────────────────────
#
# The Pura 4 accepts intensity integers 0-10 internally.
# We collapse these into four named levels and expose them to HomeKit as
# humidity percentage values so the slider snaps cleanly to defined steps.
#
# Band definitions (midpoints used as canonical send values):
#   off     →  0
#   subtle  →  1-3   (canonical: 2)
#   medium  →  4-6   (canonical: 5)
#   strong  →  7-10  (canonical: 8)

INTENSITY_OFF: int = 0
INTENSITY_SUBTLE: int = 2
INTENSITY_MEDIUM: int = 5
INTENSITY_STRONG: int = 8

# Named intensity labels used as HA mode strings.
MODE_OFF: str = "off"
MODE_SUBTLE: str = "subtle"
MODE_MEDIUM: str = "medium"
MODE_STRONG: str = "strong"

# Modes exposed to HA / HomeKit (excludes "off" — handled by on/off toggle).
AVAILABLE_MODES: list[str] = [MODE_SUBTLE, MODE_MEDIUM, MODE_STRONG]

# Pura intensity integer → HomeKit humidity percentage.
INTENSITY_TO_HUMIDITY: dict[int, int] = {
    INTENSITY_OFF: 0,
    INTENSITY_SUBTLE: 33,
    INTENSITY_MEDIUM: 66,
    INTENSITY_STRONG: 100,
}

# HomeKit humidity percentage → Pura intensity integer (exact matches only).
# The slider snaps to the nearest defined step via _snap_to_intensity().
HUMIDITY_TO_INTENSITY: dict[int, int] = {
    0: INTENSITY_OFF,
    33: INTENSITY_SUBTLE,
    66: INTENSITY_MEDIUM,
    100: INTENSITY_STRONG,
}

# Ordered list of (pura_int, humidity_pct) tuples for nearest-neighbour snapping.
INTENSITY_STEPS: list[tuple[int, int]] = sorted(
    INTENSITY_TO_HUMIDITY.items(), key=lambda item: item[1]
)

# Named mode → canonical Pura intensity integer (for set_mode service calls).
MODE_TO_INTENSITY: dict[str, int] = {
    MODE_OFF: INTENSITY_OFF,
    MODE_SUBTLE: INTENSITY_SUBTLE,
    MODE_MEDIUM: INTENSITY_MEDIUM,
    MODE_STRONG: INTENSITY_STRONG,
}


def intensity_to_mode(intensity: int) -> str:
    """Convert a raw Pura intensity integer to the corresponding named mode string.

    Args:
        intensity: Raw Pura intensity value in the range 0-10.

    Returns:
        One of ``MODE_OFF``, ``MODE_SUBTLE``, ``MODE_MEDIUM``, or ``MODE_STRONG``.
    """
    if intensity <= 0:
        return MODE_OFF
    if intensity <= 3:
        return MODE_SUBTLE
    if intensity <= 6:
        return MODE_MEDIUM
    return MODE_STRONG
