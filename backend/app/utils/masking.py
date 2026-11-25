import re

_AADHAAR_RE = re.compile(r"\d{12}")


def mask_aadhaar(aadhaar: str) -> str:
    """'123456789012' -> 'XXXX-XXXX-9012'. Only the last four digits survive."""
    if not _AADHAAR_RE.fullmatch(aadhaar):
        raise ValueError("Aadhaar must be exactly 12 digits")
    return f"XXXX-XXXX-{aadhaar[-4:]}"
