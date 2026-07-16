import re

PASSWORD_POLICY = "Password must be 8 to 72 characters and include a number and an uppercase letter"

# bcrypt rejects secrets longer than 72 bytes, so cap here to fail with a clear
# message instead of a 500 from the hashing layer.
_MAX_PASSWORD_BYTES = 72


def validate_cnic(cnic: str) -> bool:
    return bool(re.fullmatch(r"\d{13}", cnic))


def validate_pk_phone(phone: str) -> bool:
    return bool(re.fullmatch(r"(03\d{9}|\+923\d{9})", phone))


def validate_password_strength(password: str) -> bool:
    return (
        len(password) >= 8
        and len(password.encode("utf-8")) <= _MAX_PASSWORD_BYTES
        and any(c.isdigit() for c in password)
        and any(c.isupper() for c in password)
    )
