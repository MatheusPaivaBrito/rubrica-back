"""Invite a selected person through the normal secure account activation flow."""

import argparse
from getpass import getpass
from typing import get_args

from pydantic import ValidationError
from sqlalchemy import select

from auth_api.infrastructure.database.connection import SessionLocal
from auth_api.modules.accounts.account_schema import (
    IdentityDocumentType,
    PublicRegistration,
)
from auth_api.modules.accounts.account_service import (
    AccountConflictError,
    account_service,
)
from auth_api.modules.users.user_entity import UserEntity


def invite(payload: PublicRegistration) -> str:
    try:
        account_service.register(payload)
        return "created"
    except AccountConflictError:
        with SessionLocal() as database:
            user = database.scalar(
                select(UserEntity).where(
                    UserEntity.email == payload.email.strip().lower(),
                    UserEntity.deleted_at.is_(None),
                )
            )
            if user is None:
                raise
            if user.is_active or user.email_verified:
                raise ValueError(
                    "This e-mail already belongs to an active account; grant access "
                    "to its tenant with production-grant-lifetime"
                )
        account_service.request_email_verification(payload.email)
        return "verification_resent"


def invalid_document_message(document_type: str) -> str:
    if document_type == "BR_CNPJ":
        return (
            "CNPJ invalido. Informe os 14 digitos, com ou sem pontuacao, "
            "incluindo os dois digitos verificadores."
        )
    if document_type == "BR_CPF":
        return (
            "CPF invalido. Informe os 11 digitos, com ou sem pontuacao, "
            "incluindo os dois digitos verificadores."
        )
    return "Documento invalido. Confira o numero e tente novamente."


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a selected Rubrica account and e-mail its activation link."
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--locale",
        choices=("en", "pt-BR", "es", "ja-JP"),
        default="en",
    )
    parser.add_argument(
        "--document-type",
        choices=get_args(IdentityDocumentType),
        required=True,
    )
    parser.add_argument("--document-country", required=True)
    args = parser.parse_args()

    document_value = getpass("Document number (hidden): ").strip()
    try:
        payload = PublicRegistration(
            name=args.name,
            email=args.email,
            preferred_locale=args.locale,
            identity_document_type=args.document_type,
            identity_document_country=args.document_country,
            identity_document_value=document_value,
        )
    except ValidationError as error:
        identity_error = any(
            item.get("loc") == () and "Brazilian" in item.get("msg", "")
            for item in error.errors()
        )
        if identity_error:
            parser.exit(2, f"[erro] {invalid_document_message(args.document_type)}\n")
        first_error = error.errors()[0]
        message = first_error.get("msg", "Dados invalidos.")
        parser.exit(2, f"[erro] Nao foi possivel criar o convite: {message}\n")
    result = invite(payload)
    if result == "created":
        print(f"[ok] Account invitation sent to {payload.email.lower()}")
    else:
        print(
            f"[ok] Account was pending; a new activation link was sent to "
            f"{payload.email.lower()}"
        )


if __name__ == "__main__":
    main()
