from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass, field
from functools import lru_cache
from html import escape
from io import BytesIO
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M

from shared_kernel.localization import normalize_locale


BRAND_MARK_CONTENT_ID = "rubrica-brand-mark"


@dataclass(frozen=True)
class InlineEmailImage:
    content: str
    filename: str
    content_id: str
    content_type: str = "image/png"

    def as_payload(self) -> dict[str, str]:
        return {
            "content": self.content,
            "filename": self.filename,
            "content_id": self.content_id,
            "content_type": self.content_type,
        }


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    text: str
    html: str
    inline_images: tuple[InlineEmailImage, ...] = field(default_factory=tuple)

    def as_payload(self, *, recipient: str, idempotency_key: str) -> dict[str, object]:
        return {
            "recipient": recipient,
            "subject": self.subject,
            "content": self.text,
            "html": self.html,
            "inline_images": [image.as_payload() for image in self.inline_images],
            "idempotency_key": idempotency_key,
        }


ACCOUNT_COPY = {
    "en": {
        "activation_subject": "Activate your Rubrica account",
        "activation_eyebrow": "WELCOME TO RUBRICA",
        "activation_title": "Create your password",
        "activation_intro": "Your Rubrica account is ready.",
        "activation_body": "Confirm your email and choose a password to access your workspace.",
        "activation_action": "Activate account",
        "recovery_subject": "Reset your Rubrica password",
        "recovery_eyebrow": "ACCOUNT SECURITY",
        "recovery_title": "Reset your password",
        "recovery_intro": "We received a request to reset your Rubrica password.",
        "recovery_body": "Use the button below to choose a new password. If you did not request this, you can ignore this email.",
        "recovery_action": "Choose new password",
        "expiry": "For your security, this link expires and can only be used once.",
    },
    "pt-BR": {
        "activation_subject": "Ative sua conta Rubrica",
        "activation_eyebrow": "BEM-VINDO AO RUBRICA",
        "activation_title": "Crie sua senha",
        "activation_intro": "Sua conta Rubrica está pronta.",
        "activation_body": "Confirme seu e-mail e escolha uma senha para acessar seu espaço de trabalho.",
        "activation_action": "Ativar conta",
        "recovery_subject": "Redefina sua senha do Rubrica",
        "recovery_eyebrow": "SEGURANÇA DA CONTA",
        "recovery_title": "Redefina sua senha",
        "recovery_intro": "Recebemos uma solicitação para redefinir sua senha do Rubrica.",
        "recovery_body": "Use o botão abaixo para escolher uma nova senha. Se não foi você, ignore este e-mail.",
        "recovery_action": "Escolher nova senha",
        "expiry": "Para sua segurança, este link expira e só pode ser usado uma vez.",
    },
    "es": {
        "activation_subject": "Activa tu cuenta de Rubrica",
        "activation_eyebrow": "BIENVENIDO A RUBRICA",
        "activation_title": "Crea tu contraseña",
        "activation_intro": "Tu cuenta de Rubrica está lista.",
        "activation_body": "Confirma tu correo y elige una contraseña para acceder a tu espacio de trabajo.",
        "activation_action": "Activar cuenta",
        "recovery_subject": "Restablece tu contraseña de Rubrica",
        "recovery_eyebrow": "SEGURIDAD DE LA CUENTA",
        "recovery_title": "Restablece tu contraseña",
        "recovery_intro": "Recibimos una solicitud para restablecer tu contraseña de Rubrica.",
        "recovery_body": "Usa el botón para elegir una nueva contraseña. Si no lo solicitaste, ignora este correo.",
        "recovery_action": "Elegir nueva contraseña",
        "expiry": "Por tu seguridad, este enlace caduca y solo puede utilizarse una vez.",
    },
    "ja-JP": {
        "activation_subject": "Rubrica アカウントを有効にする",
        "activation_eyebrow": "RUBRICA へようこそ",
        "activation_title": "パスワードを作成",
        "activation_intro": "Rubrica アカウントの準備ができました。",
        "activation_body": "メールアドレスを確認し、ワークスペースにアクセスするためのパスワードを設定してください。",
        "activation_action": "アカウントを有効にする",
        "recovery_subject": "Rubrica のパスワードを再設定",
        "recovery_eyebrow": "アカウントセキュリティ",
        "recovery_title": "パスワードを再設定",
        "recovery_intro": "Rubrica のパスワード再設定リクエストを受け付けました。",
        "recovery_body": "下のボタンから新しいパスワードを設定してください。心当たりがない場合は、このメールを無視してください。",
        "recovery_action": "新しいパスワードを設定",
        "expiry": "安全のため、このリンクには有効期限があり、一度だけ使用できます。",
    },
}

SIGNATURE_INVITATION_COPY = {
    "en": {
        "subject": "Rubrica: signature requested for {document}",
        "eyebrow": "DOCUMENT FOR SIGNATURE",
        "title": "Your signature was requested",
        "invitation": "You were invited to review and sign “{document}”.",
        "account": "Sign in with the Rubrica account associated with this email address.",
        "action": "Review and sign document",
        "note": "This is a private access link. Do not forward this email. You can also scan the QR Code with your phone.",
    },
    "pt-BR": {
        "subject": "Rubrica: assinatura solicitada para {document}",
        "eyebrow": "DOCUMENTO PARA ASSINATURA",
        "title": "Sua assinatura foi solicitada",
        "invitation": "Você foi convidado para revisar e assinar “{document}”.",
        "account": "Entre com a conta Rubrica associada a este endereço de e-mail.",
        "action": "Revisar e assinar documento",
        "note": "Este é um link de acesso privado. Não encaminhe este e-mail. Você também pode escanear o QR Code com seu celular.",
    },
    "es": {
        "subject": "Rubrica: firma solicitada para {document}",
        "eyebrow": "DOCUMENTO PARA FIRMAR",
        "title": "Se solicitó tu firma",
        "invitation": "Te invitaron a revisar y firmar “{document}”.",
        "account": "Inicia sesión con la cuenta Rubrica asociada a esta dirección de correo.",
        "action": "Revisar y firmar documento",
        "note": "Este es un enlace de acceso privado. No reenvíes este correo. También puedes escanear el código QR con tu teléfono.",
    },
    "ja-JP": {
        "subject": "Rubrica: {document} の署名依頼",
        "eyebrow": "署名対象文書",
        "title": "署名が依頼されました",
        "invitation": "「{document}」の確認と署名を依頼されています。",
        "account": "このメールアドレスに関連付けられた Rubrica アカウントでログインしてください。",
        "action": "文書を確認して署名する",
        "note": "これは非公開のアクセスリンクです。このメールを転送しないでください。スマートフォンで QR コードを読み取ることもできます。",
    },
}


def account_activation_email(
    *, name: str | None, action_url: str, locale: str, public_url: str
) -> RenderedEmail:
    copy = ACCOUNT_COPY[normalize_locale(locale)]
    return _branded_email(
        subject=copy["activation_subject"],
        eyebrow=copy["activation_eyebrow"],
        title=copy["activation_title"],
        greeting_name=name,
        paragraphs=(copy["activation_intro"], copy["activation_body"]),
        action_label=copy["activation_action"],
        action_url=action_url,
        note=copy["expiry"],
        public_url=public_url,
    )


def password_recovery_email(
    *, name: str | None, action_url: str, locale: str, public_url: str
) -> RenderedEmail:
    copy = ACCOUNT_COPY[normalize_locale(locale)]
    return _branded_email(
        subject=copy["recovery_subject"],
        eyebrow=copy["recovery_eyebrow"],
        title=copy["recovery_title"],
        greeting_name=name,
        paragraphs=(copy["recovery_intro"], copy["recovery_body"]),
        action_label=copy["recovery_action"],
        action_url=action_url,
        note=copy["expiry"],
        public_url=public_url,
    )


def signature_invitation_email(
    *,
    signer_name: str,
    document_title: str,
    signing_url: str,
    locale: str,
    public_url: str,
) -> RenderedEmail:
    copy = SIGNATURE_INVITATION_COPY[normalize_locale(locale)]
    qr_image = _qr_code(signing_url)
    return _branded_email(
        subject=copy["subject"].format(document=document_title),
        eyebrow=copy["eyebrow"],
        title=copy["title"],
        greeting_name=signer_name,
        paragraphs=(
            copy["invitation"].format(document=document_title),
            copy["account"],
        ),
        action_label=copy["action"],
        action_url=signing_url,
        note=copy["note"],
        public_url=public_url,
        qr_content_id=qr_image.content_id,
        inline_images=(qr_image,),
    )


def branded_message_email(
    *, subject: str, body: str, public_url: str, eyebrow: str = "RUBRICA"
) -> RenderedEmail:
    paragraphs = tuple(part for part in body.split("\n\n") if part.strip()) or (body,)
    return _branded_email(
        subject=subject,
        eyebrow=eyebrow,
        title=subject,
        paragraphs=paragraphs,
        public_url=public_url,
    )


def _qr_code(value: str) -> InlineEmailImage:
    code = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=6,
        border=4,
    )
    code.add_data(value)
    code.make(fit=True)
    output = BytesIO()
    code.make_image(fill_color="#3b151d", back_color="white").save(
        output, format="PNG"
    )
    return InlineEmailImage(
        content=b64encode(output.getvalue()).decode("ascii"),
        filename="rubrica-signing-qr.png",
        content_id="rubrica-signing-qr",
    )


@lru_cache(maxsize=1)
def _brand_mark() -> InlineEmailImage:
    content = Path(__file__).with_name("assets").joinpath("rubrica-email-mark.png").read_bytes()
    return InlineEmailImage(
        content=b64encode(content).decode("ascii"),
        filename="rubrica-mark.png",
        content_id=BRAND_MARK_CONTENT_ID,
    )


def _branded_email(
    *,
    subject: str,
    eyebrow: str,
    title: str,
    paragraphs: tuple[str, ...],
    public_url: str,
    greeting_name: str | None = None,
    action_label: str | None = None,
    action_url: str | None = None,
    note: str | None = None,
    qr_content_id: str | None = None,
    inline_images: tuple[InlineEmailImage, ...] = (),
) -> RenderedEmail:
    clean_subject = " ".join(subject.split())[:160]
    root_url = public_url.rstrip("/")
    safe_paragraphs = "".join(
        f'<p style="margin:0 0 18px;color:#62494d;font-size:16px;line-height:1.65">'
        f"{escape(paragraph).replace(chr(10), '<br>')}</p>"
        for paragraph in paragraphs
    )
    greeting = (
        f'<p style="margin:0 0 18px;color:#30191d;font-size:17px;font-weight:700">'
        f"Hello, {escape(greeting_name)}.</p>"
        if greeting_name
        else ""
    )
    action = ""
    if action_label and action_url:
        safe_url = escape(action_url, quote=True)
        action = (
            '<table role="presentation" cellspacing="0" cellpadding="0" style="margin:28px 0">'
            f'<tr><td style="border-radius:999px;background:#a82035"><a href="{safe_url}" '
            'style="display:inline-block;padding:14px 24px;color:#ffffff;text-decoration:none;'
            f'font-size:16px;font-weight:800">{escape(action_label)}</a></td></tr></table>'
            '<p style="margin:0 0 18px;color:#8a7377;font-size:12px;line-height:1.55">'
            'If the button does not work, copy and paste this address into your browser:<br>'
            f'<a href="{safe_url}" style="color:#8f1d2c;word-break:break-all">{safe_url}</a></p>'
        )
    qr = ""
    if qr_content_id:
        qr = (
            '<div style="margin:26px 0 10px;padding:20px;border:1px solid #ead8d5;'
            'border-radius:16px;background:#fffaf8;text-align:center">'
            f'<img src="cid:{escape(qr_content_id, quote=True)}" width="210" height="210" '
            'alt="QR Code for the secure signing link" style="display:block;margin:0 auto;max-width:100%;height:auto">'
            '<p style="margin:10px 0 0;color:#80676b;font-size:13px">Scan to open on your phone</p></div>'
        )
    note_html = (
        '<div style="margin-top:26px;padding:14px 16px;border-left:4px solid #a82035;'
        f'background:#fff0ee;color:#6f575b;font-size:13px;line-height:1.55">{escape(note)}</div>'
        if note
        else ""
    )
    safe_root = escape(root_url, quote=True)
    html = f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f6f1ef;font-family:Arial,sans-serif">
<div style="display:none;max-height:0;overflow:hidden;color:transparent">{escape(clean_subject)}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f1ef">
<tr><td align="center" style="padding:32px 14px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:#ffffff;border:1px solid #ead8d5;border-radius:22px;overflow:hidden">
<tr><td style="padding:24px 34px;background:#3b151d">
<a href="{safe_root}" style="display:inline-block;color:#ffffff;text-decoration:none">
<table role="presentation" cellspacing="0" cellpadding="0"><tr>
<td width="40" height="40" align="center" valign="middle" style="width:40px;height:40px">
<img src="cid:{BRAND_MARK_CONTENT_ID}" width="40" height="40" alt="Rubrica" style="display:block;width:40px;height:40px;border:0">
</td>
<td style="padding-left:11px;color:#ffffff;font-family:Arial,sans-serif;font-size:22px;font-weight:800;line-height:40px">Rubrica</td>
</tr></table></a>
</td></tr>
<tr><td style="padding:38px 34px 34px">
<div style="margin-bottom:12px;color:#a82035;font-size:12px;font-weight:900;letter-spacing:2px">{escape(eyebrow)}</div>
<h1 style="margin:0 0 24px;color:#3b151d;font-family:Georgia,serif;font-size:34px;line-height:1.15;font-weight:500">{escape(title)}</h1>
{greeting}{safe_paragraphs}{action}{qr}{note_html}
</td></tr>
<tr><td style="padding:22px 34px;border-top:1px solid #eadcda;background:#fffaf8;color:#8a7377;font-size:12px;line-height:1.6">
Rubrica · Secure electronic signatures<br><a href="{safe_root}" style="color:#8f1d2c;text-decoration:none">{safe_root}</a>
</td></tr></table>
</td></tr></table></body></html>"""
    text_parts = [clean_subject]
    if greeting_name:
        text_parts.append(f"Hello, {greeting_name}.")
    text_parts.extend(paragraphs)
    if action_label and action_url:
        text_parts.extend((action_label, action_url))
    if note:
        text_parts.append(note)
    text_parts.append(f"Rubrica · {root_url}")
    return RenderedEmail(
        subject=clean_subject,
        text="\n\n".join(text_parts),
        html=html,
        inline_images=(_brand_mark(), *inline_images),
    )
