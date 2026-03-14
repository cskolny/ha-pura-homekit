"""Constants for the Pura HomeKit integration."""
from __future__ import annotations

DOMAIN = "pura_homekit"

# Platforms provided by this integration
PLATFORMS: list[str] = ["humidifier", "light"]

# ---------------------------------------------------------------------------
# Pura API – AWS Cognito
# These are Pura's public app identifiers (not user credentials).
# Decoded from the pypura package: base64.b64decode(pypura.const.USER_POOL_ID)
# ---------------------------------------------------------------------------
PURA_COGNITO_REGION = "us-east-1"
PURA_USER_POOL_ID = "us-east-1_LaB718hYv"
PURA_CLIENT_ID = "4iekubat0jb5iljfbaalsiqf9j"

# Pura REST/GraphQL endpoint
PURA_API_URL = "https://api.pura.com/graphql"

# How often to poll the Pura API (seconds)
DEFAULT_SCAN_INTERVAL = 30

# ---------------------------------------------------------------------------
# Config-entry field keys
# ---------------------------------------------------------------------------
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"

# ---------------------------------------------------------------------------
# Intensity ↔ HomeKit humidity mapping
#
# The Pura 4 uses integer intensity values 0-10 internally.
# We collapse these into four named levels and map them to % for HomeKit.
# ---------------------------------------------------------------------------

# Pura intensity integers that correspond to each named level:
#   off     →  0
#   subtle  →  1-3   (we send 2 as the canonical value)
#   medium  →  4-6   (we send 5)
#   strong  →  7-10  (we send 8)
INTENSITY_OFF: int = 0
INTENSITY_SUBTLE: int = 2
INTENSITY_MEDIUM: int = 5
INTENSITY_STRONG: int = 8

# Named intensity labels (used as HA mode strings)
MODE_OFF = "off"
MODE_SUBTLE = "subtle"
MODE_MEDIUM = "medium"
MODE_STRONG = "strong"

AVAILABLE_MODES: list[str] = [MODE_SUBTLE, MODE_MEDIUM, MODE_STRONG]

# Pura int → HomeKit humidity %
INTENSITY_TO_HUMIDITY: dict[int, int] = {
    INTENSITY_OFF: 0,
    INTENSITY_SUBTLE: 33,
    INTENSITY_MEDIUM: 66,
    INTENSITY_STRONG: 100,
}

# HomeKit humidity % → Pura int (exact matches only; sliders snap to nearest)
HUMIDITY_TO_INTENSITY: dict[int, int] = {
    0: INTENSITY_OFF,
    33: INTENSITY_SUBTLE,
    66: INTENSITY_MEDIUM,
    100: INTENSITY_STRONG,
}

# Ordered list of (pura_int, humidity_pct) for nearest-neighbour snapping
INTENSITY_STEPS: list[tuple[int, int]] = sorted(
    INTENSITY_TO_HUMIDITY.items(), key=lambda x: x[1]
)

# Named-level → pura int (for direct set_mode calls)
MODE_TO_INTENSITY: dict[str, int] = {
    MODE_OFF: INTENSITY_OFF,
    MODE_SUBTLE: INTENSITY_SUBTLE,
    MODE_MEDIUM: INTENSITY_MEDIUM,
    MODE_STRONG: INTENSITY_STRONG,
}

# Pura int → named level (approximate – any int in the right band maps here)
def intensity_to_mode(intensity: int) -> str:
    """Convert a raw Pura intensity integer to a named mode string."""
    if intensity <= 0:
        return MODE_OFF
    if intensity <= 3:
        return MODE_SUBTLE
    if intensity <= 6:
        return MODE_MEDIUM
    return MODE_STRONG