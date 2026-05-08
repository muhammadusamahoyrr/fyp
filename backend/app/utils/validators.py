import re


def validate_cnic(cnic: str) -> bool:
    return bool(re.fullmatch(r"\d{13}", cnic))


def validate_pk_phone(phone: str) -> bool:
    return bool(re.fullmatch(r"(03\d{9}|\+923\d{9})", phone))


def validate_password_strength(password: str) -> bool:
    return len(password) >= 8 and any(c.isdigit() for c in password)
