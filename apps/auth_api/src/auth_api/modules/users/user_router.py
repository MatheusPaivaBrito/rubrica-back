from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from auth_api.infrastructure.database.connection import SessionLocal
from auth_api.modules.access_control.access_control_entity import UserRoleEntity
from auth_api.modules.access_control.access_control_service import (
    access_control_service,
)
from auth_api.modules.sessions.session_router import require_authenticated_session
from auth_api.modules.sessions.session_schema import SessionRead
from auth_api.modules.users.passwords import hash_password
from auth_api.modules.users.user_entity import UserEntity
from auth_api.modules.users.user_identifier_entity import UserIdentifierEntity
from auth_api.modules.users.user_identifier_service import add_identifier
from auth_api.modules.users.user_schema import (
    UserCreate,
    UserIdentifierRead,
    UserPreferencesUpdate,
    UserRead,
)


router = APIRouter(prefix="/users", tags=["users - command"])


def _cpf_digits(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) != 11 or digits == digits[0] * 11:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="CPF inválido"
        )
    for size in (9, 10):
        total = sum(
            int(digit) * weight
            for digit, weight in zip(digits[:size], range(size + 1, 1, -1), strict=True)
        )
        check = (total * 10 % 11) % 10
        if check != int(digits[size]):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="CPF inválido"
            )
    return digits


@router.get("/signers", response_model=list[UserRead], tags=["users - query"])
async def list_signers(
    session: SessionRead = Depends(require_authenticated_session),
) -> list[UserRead]:
    with SessionLocal() as database:
        actor = database.scalar(
            select(UserEntity).where(UserEntity.email == session.subject).limit(1)
        )
        if actor is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        roles, _ = access_control_service.context_for_user(actor.id)
        if not ({"signature_admin", "signature_operator"} & set(roles)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operator role is required",
            )
        rows = database.scalars(
            select(UserEntity)
            .join(UserRoleEntity, UserRoleEntity.user_id == UserEntity.id)
            .where(
                UserEntity.is_active.is_(True),
                UserEntity.deleted_at.is_(None),
                UserRoleEntity.role.in_(["signature_signer", "signature_admin"]),
            )
            .distinct()
            .order_by(UserEntity.name, UserEntity.email)
        ).all()
        return [
            UserRead(
                id=item.id,
                name=item.name or item.email,
                email=item.email,
                role="signature_signer",
                is_active=item.is_active,
                preferred_locale=item.preferred_locale,
            )
            for item in rows
        ]


@router.patch("/me/preferences", response_model=UserRead)
async def update_my_preferences(
    payload: UserPreferencesUpdate,
    session: SessionRead = Depends(require_authenticated_session),
) -> UserRead:
    with SessionLocal.begin() as database:
        item = database.scalar(
            select(UserEntity).where(UserEntity.email == session.subject).limit(1)
        )
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        roles, _ = access_control_service.context_for_user(item.id)
        role = next(
            (candidate for candidate in roles if candidate.startswith("signature_")),
            "signature_signer",
        )
        item.preferred_locale = payload.preferred_locale
        database.flush()
        return UserRead(
            id=item.id,
            name=item.name or item.email,
            email=item.email,
            role=role,
            is_active=item.is_active,
            preferred_locale=item.preferred_locale,
        )


@router.get("/me/identifiers", response_model=list[UserIdentifierRead])
async def list_my_identifiers(
    session: SessionRead = Depends(require_authenticated_session),
) -> list[UserIdentifierRead]:
    with SessionLocal() as database:
        user = database.scalar(
            select(UserEntity).where(
                UserEntity.email == session.subject,
                UserEntity.deleted_at.is_(None),
            )
        )
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        identifiers = database.scalars(
            select(UserIdentifierEntity)
            .where(
                UserIdentifierEntity.user_id == user.id,
                UserIdentifierEntity.deleted_at.is_(None),
            )
            .order_by(UserIdentifierEntity.created_at)
        ).all()
        return [
            UserIdentifierRead.model_validate(item, from_attributes=True)
            for item in identifiers
        ]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate, session: SessionRead = Depends(require_authenticated_session)
) -> UserRead:
    with SessionLocal.begin() as database:
        actor = database.scalar(
            select(UserEntity).where(UserEntity.email == session.subject).limit(1)
        )
        if actor is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        roles, _ = access_control_service.context_for_user(actor.id)
        if "signature_admin" not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrator role is required",
            )
        item = UserEntity(
            name=payload.name.strip(),
            email=payload.email.lower(),
            cpf_hash=hash_password(_cpf_digits(payload.cpf)) if payload.cpf else None,
            password_hash=hash_password(payload.password),
            preferred_locale=payload.preferred_locale,
            email_verified=True,
            is_active=True,
        )
        database.add(item)
        try:
            database.flush()
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists",
            ) from exc
        database.add(UserRoleEntity(user_id=item.id, role=payload.role))
        if (
            payload.identity_document_type
            and payload.identity_document_country
            and payload.identity_document_value
        ):
            add_identifier(
                database,
                user_id=item.id,
                issuing_country=payload.identity_document_country,
                identifier_type=payload.identity_document_type,
                value=payload.identity_document_value,
            )
            try:
                database.flush()
            except IntegrityError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Identity document is already registered",
                ) from exc
        return UserRead(
            id=item.id,
            name=item.name or item.email,
            email=item.email,
            role=payload.role,
            is_active=item.is_active,
            preferred_locale=item.preferred_locale,
        )
