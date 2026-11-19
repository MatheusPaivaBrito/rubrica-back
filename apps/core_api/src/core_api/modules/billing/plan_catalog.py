from dataclasses import dataclass


FREE = "rubrica_free"
ESSENTIAL = "rubrica_base"
PROFESSIONAL = "rubrica_intermediate"
TEAM = "rubrica_team"
LIFETIME = "rubrica_lifetime"


@dataclass(frozen=True)
class PlanDefinition:
    code: str
    included_seats: int
    included_documents: int | None
    entitlements: frozenset[str]
    allows_seat_expansion: bool = False


EVIDENCE = "evidence_signature"
TRUSTED_TIMESTAMP = "trusted_timestamp"
SERPROID = "serproid_signature"
CUSTOM_STAMP_PLACEMENT = "custom_stamp_placement"
CUSTOM_STAMP_BASIC = "custom_stamp_basic"
CUSTOM_STAMP_BRANDING = "custom_stamp_branding"
BUSINESS_REPRESENTATION = "business_representation"
TEAM_MANAGEMENT = "team_management"
EMAIL_INVITATIONS = "email_invitations"

TEAM_ENTITLEMENTS = frozenset(
    {
        EVIDENCE,
        TRUSTED_TIMESTAMP,
        SERPROID,
        CUSTOM_STAMP_PLACEMENT,
        CUSTOM_STAMP_BASIC,
        CUSTOM_STAMP_BRANDING,
        BUSINESS_REPRESENTATION,
        TEAM_MANAGEMENT,
        EMAIL_INVITATIONS,
    }
)


CATALOG = {
    FREE: PlanDefinition(FREE, 1, None, frozenset({EVIDENCE})),
    ESSENTIAL: PlanDefinition(
        ESSENTIAL,
        1,
        20,
        frozenset(
            {
                EVIDENCE,
                TRUSTED_TIMESTAMP,
                SERPROID,
                CUSTOM_STAMP_PLACEMENT,
                CUSTOM_STAMP_BASIC,
            }
        ),
    ),
    PROFESSIONAL: PlanDefinition(
        PROFESSIONAL,
        3,
        80,
        TEAM_ENTITLEMENTS,
        allows_seat_expansion=True,
    ),
    TEAM: PlanDefinition(
        TEAM,
        10,
        220,
        TEAM_ENTITLEMENTS,
        allows_seat_expansion=True,
    ),
    LIFETIME: PlanDefinition(
        LIFETIME,
        10,
        None,
        TEAM_ENTITLEMENTS,
    ),
}

ADDITIONAL_SEAT_DOCUMENTS = 20


def normalize_product_code(product_code: object) -> str:
    value = str(product_code or ESSENTIAL)
    return ESSENTIAL if value == "rubrica_mvp" else value


def account_plan(*, product_code: object, paid: bool, lifetime: bool) -> PlanDefinition:
    if lifetime:
        return CATALOG[LIFETIME]
    if not paid:
        return CATALOG[FREE]
    return CATALOG.get(normalize_product_code(product_code), CATALOG[ESSENTIAL])


def normalized_seats(plan: PlanDefinition, contracted_seats: int | None) -> int:
    if not plan.allows_seat_expansion:
        return plan.included_seats
    return max(contracted_seats or plan.included_seats, plan.included_seats)


def document_limit(plan: PlanDefinition, seats: int) -> int | None:
    if plan.included_documents is None:
        return None
    extras = max(seats - plan.included_seats, 0)
    return plan.included_documents + extras * ADDITIONAL_SEAT_DOCUMENTS
