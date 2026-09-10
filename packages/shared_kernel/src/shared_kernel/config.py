from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel


SettingsType = TypeVar("SettingsType", bound=BaseModel)


def apply_secret_files(
    settings: SettingsType,
    mapping: dict[str, str],
) -> SettingsType:
    for value_field, file_field in mapping.items():
        secret_file = getattr(settings, file_field, None)
        if not secret_file:
            continue
        path = Path(secret_file)
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise ValueError(f"Secret file configured by {file_field} is empty")
        object.__setattr__(settings, value_field, value)
    return settings
