import re


DEFAULT_COUNTRY_CODE = "234"


def normalize_phone_number(value: str, country_code: str = DEFAULT_COUNTRY_CODE) -> str:
    """Return a canonical international phone number without the leading +."""
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return ""

    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith(country_code):
        return digits
    if digits.startswith("0"):
        return country_code + digits[1:]
    if len(digits) == 10:
        return country_code + digits
    return digits


def phone_numbers_match(left: str, right: str) -> bool:
    return bool(normalize_phone_number(left)) and normalize_phone_number(left) == normalize_phone_number(right)
