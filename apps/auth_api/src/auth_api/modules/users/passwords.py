import bcrypt


def validate_password_length(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("password must be at most 72 UTF-8 bytes")
    return password


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False
