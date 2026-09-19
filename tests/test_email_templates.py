from base64 import b64decode

import pytest

from shared_kernel.email_templates import (
    account_activation_email,
    branded_message_email,
    password_recovery_email,
    signature_invitation_email,
)


@pytest.mark.parametrize(
    ("locale", "expected_subject"),
    [
        ("en", "Activate your Rubrica account"),
        ("pt-BR", "Ative sua conta Rubrica"),
        ("es", "Activa tu cuenta de Rubrica"),
        ("ja-JP", "Rubrica アカウントを有効にする"),
    ],
)
def test_account_activation_template_is_localized_and_branded(
    locale: str, expected_subject: str
) -> None:
    email = account_activation_email(
        name="Taylor",
        action_url="https://rubricasignature.com/verify-email?token=secret",
        locale=locale,
        public_url="https://rubricasignature.com",
    )

    assert email.subject == expected_subject
    assert "https://rubricasignature.com/icons/rubrica-mark.png" in email.html
    assert "token=secret" in email.html
    assert "token=secret" in email.text
    assert email.inline_images == ()


def test_password_recovery_template_escapes_user_content() -> None:
    email = password_recovery_email(
        name='<script>alert("x")</script>',
        action_url="https://rubricasignature.com/reset-password?token=secret&next=1",
        locale="en",
        public_url="https://rubricasignature.com",
    )

    assert "<script>" not in email.html
    assert "&lt;script&gt;" in email.html
    assert "token=secret&amp;next=1" in email.html


def test_signature_invitation_contains_local_inline_qr_and_fallback_link() -> None:
    signing_url = "https://rubricasignature.com/signing/private-token"
    email = signature_invitation_email(
        signer_name="Alex",
        document_title='Contract <Q4> & "Terms"',
        signing_url=signing_url,
        public_url="https://rubricasignature.com",
    )

    assert "Contract &lt;Q4&gt; &amp; &quot;Terms&quot;" in email.html
    assert signing_url in email.text
    assert 'src="cid:rubrica-signing-qr"' in email.html
    assert len(email.inline_images) == 1
    qr_image = email.inline_images[0]
    assert qr_image.content_id == "rubrica-signing-qr"
    assert qr_image.content_type == "image/png"
    assert b64decode(qr_image.content).startswith(b"\x89PNG\r\n\x1a\n")
    assert "api.qr" not in email.html.lower()


def test_generic_template_preserves_plain_text_and_escapes_html() -> None:
    email = branded_message_email(
        subject="Contact <support>",
        body="Name: User\nEmail: user@example.com\n\n<script>unsafe</script>",
        public_url="https://rubricasignature.com",
    )

    assert "Name: User\nEmail: user@example.com" in email.text
    assert "<script>" not in email.html
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in email.html
