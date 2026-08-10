from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from auth_api.infrastructure.database.connection import SessionLocal
from auth_api.modules.access_control.access_control_entity import UserRoleEntity
from auth_api.modules.access_control.access_control_service import access_control_service
from auth_api.modules.sessions.session_router import require_authenticated_session
from auth_api.modules.sessions.session_schema import SessionRead
from auth_api.modules.users.passwords import hash_password
from auth_api.modules.users.user_entity import UserEntity
from auth_api.modules.users.user_schema import UserCreate, UserRead


router = APIRouter(prefix="/users", tags=["users - command"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, session: SessionRead = Depends(require_authenticated_session)) -> UserRead:
    with SessionLocal.begin() as database:
        actor = database.scalar(select(UserEntity).where(UserEntity.email == session.subject).limit(1))
        if actor is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        roles, _ = access_control_service.context_for_user(actor.id)
        if "signature_admin" not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role is required")
        item = UserEntity(email=payload.email.lower(), password_hash=hash_password(payload.password), is_active=True)
        database.add(item)
        try:
            database.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists") from exc
        database.add(UserRoleEntity(user_id=item.id, role=payload.role))
        return UserRead(id=str(item.id), email=item.email, role=payload.role, is_active=item.is_active)
