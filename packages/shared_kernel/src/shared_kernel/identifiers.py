from typing import TypeAlias
from uuid import UUID, uuid4


Identifier: TypeAlias = UUID


def new_identifier() -> Identifier:
    return uuid4()
