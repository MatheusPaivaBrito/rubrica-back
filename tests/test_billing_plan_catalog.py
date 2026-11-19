from core_api.modules.billing.plan_catalog import (
    CATALOG,
    LIFETIME,
    PROFESSIONAL,
    SERPROID,
    TEAM,
    TRUSTED_TIMESTAMP,
    document_limit,
    normalized_seats,
)


def test_professional_expansion_adds_twenty_documents_per_seat() -> None:
    plan = CATALOG[PROFESSIONAL]

    assert normalized_seats(plan, 9) == 9
    assert document_limit(plan, 9) == 200


def test_team_starts_with_two_hundred_twenty_documents() -> None:
    plan = CATALOG[TEAM]

    assert normalized_seats(plan, 10) == 10
    assert document_limit(plan, 10) == 220
    assert document_limit(plan, 12) == 260


def test_lifetime_is_team_capability_with_ten_seats_and_unlimited_documents() -> None:
    plan = CATALOG[LIFETIME]

    assert normalized_seats(plan, 99) == 10
    assert document_limit(plan, 10) is None
    assert TRUSTED_TIMESTAMP in plan.entitlements
    assert SERPROID in plan.entitlements
