# Import ORM entities here so Alembic can discover metadata.
from auth_api.modules.access_control.access_control_entity import UserRoleEntity  # noqa: F401
from auth_api.modules.users.user_entity import UserEntity  # noqa: F401
