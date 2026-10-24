from base64 import b64encode
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError

from core_api.modules.signature_request.database_workflow_service import DatabaseSignatureWorkflowService, WorkflowError
from core_api.modules.signature_request.workflow_schema import (
    ClientEvidence,
    GeolocationEvidence,
    SignCommand,
    StampCustomization,
    StampPosition,
)


def _png_data_url(*, width: int = 4, height: int = 4) -> str:
    output = BytesIO()
    Image.new("RGBA", (width, height), (24, 122, 102, 255)).save(output, format="PNG")
    return "data:image/png;base64," + b64encode(output.getvalue()).decode("ascii")


def test_stamp_images_are_decoded_and_normalized_as_real_pngs() -> None:
    value = _png_data_url()

    customization = StampCustomization(show_logo=True, logo_png_data_url=value)
    command = SignCommand(
        consent=True,
        consent_version="rubrica-evidence-v2",
        client=ClientEvidence(),
        geolocation=GeolocationEvidence(status="denied"),
        drawn_signature_png_data_url=value,
    )

    assert customization.logo_png_data_url.startswith("data:image/png;base64,")
    assert command.drawn_signature_png_data_url.startswith("data:image/png;base64,")


def test_stamp_images_reject_fake_png_headers() -> None:
    fake = "data:image/png;base64," + b64encode(b"\x89PNG\r\n\x1a\nnot-an-image").decode("ascii")

    with pytest.raises(ValidationError, match="PNG image is invalid"):
        StampCustomization(show_logo=True, logo_png_data_url=fake)


def test_positions_for_different_signers_cannot_overlap() -> None:
    first_signer = uuid4()
    second_signer = uuid4()
    positions = [
        StampPosition(page=1, x=0.5, y=0.5, signer_id=first_signer),
        StampPosition(page=1, x=0.55, y=0.55, signer_id=second_signer),
    ]

    with pytest.raises(WorkflowError, match="overlap"):
        DatabaseSignatureWorkflowService._reject_overlapping_positions(positions)


def test_positions_on_different_pages_do_not_overlap() -> None:
    positions = [
        StampPosition(page=1, x=0.5, y=0.5, signer_id=uuid4()),
        StampPosition(page=2, x=0.5, y=0.5, signer_id=uuid4()),
    ]

    DatabaseSignatureWorkflowService._reject_overlapping_positions(positions)


def test_stamp_variant_is_stored_per_position() -> None:
    full = StampPosition(page=1, x=0.5, y=0.5, display_variant="full")
    minimal = StampPosition(page=2, x=0.5, y=0.5, display_variant="minimal")
    drawn = StampPosition(page=3, x=0.5, y=0.5, display_variant="drawn")

    assert [full.display_variant, minimal.display_variant, drawn.display_variant] == [
        "full",
        "minimal",
        "drawn",
    ]
