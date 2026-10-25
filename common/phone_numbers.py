import re


def normalize_phone_number(value):
    """Normalize Uganda phone inputs to +256 while preserving explicit country codes."""
    raw_value = str(value or "").strip()
    digits = re.sub(r"\D", "", raw_value)
    if not digits:
        return ""

    if raw_value.startswith("+"):
        if digits.startswith("256") and digits[3:].startswith("0"):
            digits = "256" + digits[4:]
        return f"+{digits}"

    if digits.startswith("00"):
        digits = digits[2:]
        if digits.startswith("256") and digits[3:].startswith("0"):
            digits = "256" + digits[4:]
        return f"+{digits}"

    if digits.startswith("256"):
        if digits[3:].startswith("0"):
            digits = "256" + digits[4:]
        return f"+{digits}"

    if digits.startswith("0"):
        digits = digits[1:]
    return f"+256{digits}"


class PhoneNumberNormalizationMixin:
    phone_fields = ()

    def normalize_phone_fields(self):
        for field_name in self.phone_fields:
            setattr(self, field_name, normalize_phone_number(getattr(self, field_name, "")))

    def save(self, *args, **kwargs):
        self.normalize_phone_fields()
        return super().save(*args, **kwargs)
