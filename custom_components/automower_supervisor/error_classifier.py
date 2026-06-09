"""Error classification for the Automower Supervisor integration."""

from .const import NO_ACTIVE_ERROR_VALUES


def classify_error(error_message: str | None) -> str:
    """Classify error message into cutting, movement, communication, other, or none."""
    if not error_message:
        return "none"
    norm = error_message.strip().lower()
    if not norm or norm in NO_ACTIVE_ERROR_VALUES:
        return "none"

    # Klippfel (cutting)
    if any(kw in norm for kw in ["blade", "blade disc", "cutting", "cutting motor", "disc blocked"]):
        return "cutting"

    # Rörelse-/framdrivningsfel (movement)
    if any(kw in norm for kw in ["no traction", "traction", "wheel motor", "stuck", "lifted"]):
        return "movement"

    # Kommunikationsfel (communication)
    if any(kw in norm for kw in ["communication", "offline", "connection", "lost", "timeout"]):
        return "communication"

    return "other"
