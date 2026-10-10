"""Sign one PDF with a local ICP-Brasil A1 PKCS#12 and a SERPRO timestamp.

This is an operator CLI. It is intentionally independent from Rubrica's web flow.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from asn1crypto import algos, core
from pyhanko import keys
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import signers
from pyhanko.sign.ades import cades_asn1
from pyhanko.sign.ades.api import CAdESSignedAttrSpec
from pyhanko.sign.fields import SigSeedSubFilter
from pyhanko.sign.validation import async_validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

# Importing the shared timestamp service also initialises legacy workflow
# singletons. Keep that incidental local storage outside the repository.
os.environ["DOCUMENT_STORAGE_PATH"] = str(
    Path(tempfile.gettempdir()) / "rubrica-ecnpj-cli"
)

from core_api.modules.signature_request.serpro_timestamp_service import (
    apply_serpro_timestamp,
    timestamp_enabled,
    validate_pdf_timestamp,
)


class SigningError(RuntimeError):
    """Raised when the requested signing operation cannot complete safely."""


class _IcpBrasilPolicy(core.Sequence):
    # ICP-Brasil policy artefacts carry the digest that belongs in
    # id-aa-ets-sigPolicyId as their third top-level element. This is not the
    # SHA-256 of the complete DER file.
    _fields = [
        ("hash_algorithm", algos.DigestAlgorithm),
        ("policy_info", core.Any),
        ("policy_hash", core.OctetString),
    ]


@dataclass(frozen=True)
class CliConfig:
    input_pdf: Path
    output_pdf: Path
    pfx_file: Path
    signer_trust_roots: Path
    policy_file: Path
    policy_url: str
    field_name: str
    reason: str
    location: str | None


def _env_path(name: str) -> Path | None:
    value = os.getenv(name, "").strip()
    return Path(value).expanduser() if value else None


def _read_secret() -> bytes:
    password_file = _env_path("ECNPJ_PFX_PASSWORD_FILE")
    if password_file:
        try:
            password = password_file.read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as exc:
            raise SigningError("Could not read ECNPJ_PFX_PASSWORD_FILE") from exc
    elif "ECNPJ_PFX_PASSWORD" in os.environ:
        password = os.environ["ECNPJ_PFX_PASSWORD"]
    elif sys.stdin.isatty():
        password = getpass.getpass("Senha do certificado A1: ")
    else:
        raise SigningError(
            "Set ECNPJ_PFX_PASSWORD_FILE or run in a terminal to enter the password securely"
        )
    if not password:
        raise SigningError("The certificate password is empty")
    return password.encode("utf-8")


def _read_pdf(path: Path) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise SigningError(f"Could not read input PDF: {path}") from exc
    if not content.startswith(b"%PDF-"):
        raise SigningError("Input is not a PDF file")
    try:
        PdfFileReader(BytesIO(content), strict=True)
    except Exception as exc:
        raise SigningError("Input PDF is malformed or unsupported") from exc
    return content


def _load_roots(path: Path):
    try:
        roots = list(keys.load_certs_from_pemder_data(path.read_bytes()))
    except (OSError, ValueError) as exc:
        raise SigningError(f"Could not load trust roots: {path}") from exc
    if not roots:
        raise SigningError(f"Trust root bundle is empty: {path}")
    return roots


def _policy_identifier(policy_file: Path, policy_url: str):
    try:
        policy = _IcpBrasilPolicy.load(policy_file.read_bytes(), strict=True)
        policy_info = core.Sequence.load(policy["policy_info"].dump(), strict=True)
        policy_oid = str(policy_info[0].native)
        hash_algorithm = str(policy["hash_algorithm"]["algorithm"].native)
        policy_hash = policy["policy_hash"].native
    except (OSError, ValueError, TypeError, IndexError) as exc:
        raise SigningError("ICP-Brasil signature policy DER is invalid") from exc
    if hash_algorithm.lower().replace("-", "") != "sha256":
        raise SigningError("The selected signature policy does not use SHA-256")
    if not policy_oid or not policy_hash:
        raise SigningError("The signature policy OID or digest is missing")

    qualifier = cades_asn1.SigPolicyQualifierInfo(
        {
            "sig_policy_qualifier_id": "sp_uri",
            "sig_qualifier": core.IA5String(policy_url),
        }
    )
    policy_id = cades_asn1.SignaturePolicyId(
        {
            "sig_policy_id": policy_oid,
            "sig_policy_hash": algos.DigestInfo(
                {
                    "digest_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
                    "digest": policy_hash,
                }
            ),
            "sig_policy_qualifiers": [qualifier],
        }
    )
    return cades_asn1.SignaturePolicyIdentifier(
        name="signature_policy_id", value=policy_id
    )


def sign_pdf(config: CliConfig, password: bytes) -> tuple[bytes, str]:
    try:
        signer = signers.SimpleSigner.load_pkcs12(
            pfx_file=str(config.pfx_file), passphrase=password
        )
    except Exception as exc:
        raise SigningError(
            "Could not open the PKCS#12 certificate (file or password is invalid)"
        ) from exc
    if signer is None:
        raise SigningError("PKCS#12 does not contain a usable certificate and private key")

    roots = _load_roots(config.signer_trust_roots)
    validation_context = ValidationContext(
        trust_roots=roots,
        allow_fetching=True,
        revocation_mode="require",
    )
    metadata = signers.PdfSignatureMetadata(
        field_name=config.field_name,
        md_algorithm="sha256",
        reason=config.reason,
        location=config.location,
        subfilter=SigSeedSubFilter.PADES,
        embed_validation_info=True,
        validation_context=validation_context,
        cades_signed_attr_spec=CAdESSignedAttrSpec(
            signature_policy_identifier=_policy_identifier(
                config.policy_file, config.policy_url
            )
        ),
    )
    source = _read_pdf(config.input_pdf)
    output = BytesIO()
    try:
        signers.PdfSigner(metadata, signer=signer).sign_pdf(
            IncrementalPdfFileWriter(BytesIO(source)), output=output
        )
    except Exception as exc:
        raise SigningError(
            "PAdES signing failed; verify the certificate chain and revocation services"
        ) from exc
    subject = signer.signing_cert.subject.human_friendly
    return output.getvalue(), subject


async def _verify_signature(pdf: bytes, roots_file: Path) -> dict[str, object]:
    reader = PdfFileReader(BytesIO(pdf), strict=True)
    signatures = [
        item for item in reader.embedded_signatures if item.sig_object_type != "/DocTimeStamp"
    ]
    if len(signatures) != 1:
        raise SigningError(f"Expected one PDF signature, found {len(signatures)}")
    context = ValidationContext(
        trust_roots=_load_roots(roots_file),
        allow_fetching=True,
        revocation_mode="require",
    )
    try:
        status = await async_validate_pdf_signature(
            signatures[0], signer_validation_context=context
        )
    except Exception as exc:
        raise SigningError("Local PAdES trust validation failed") from exc
    coverage = getattr(status.coverage, "name", str(status.coverage))
    modification = getattr(status.modification_level, "name", str(status.modification_level))
    if not status.intact or not status.valid or not status.trusted or status.revoked:
        raise SigningError("Local PAdES validation did not approve the signature")
    return {
        "valid": status.valid,
        "intact": status.intact,
        "trusted": status.trusted,
        "revoked": status.revoked,
        "coverage": coverage,
        "modification_level": modification,
        "digest_algorithm": status.md_algorithm,
        "signer_subject": status.signing_cert.subject.human_friendly,
        "signer_certificate_sha256": status.signing_cert.sha256.hex(),
    }


def verify_final_pdf(pdf: bytes, signer_trust_roots: Path) -> dict[str, object]:
    signature = asyncio.run(_verify_signature(pdf, signer_trust_roots))
    timestamp = validate_pdf_timestamp(pdf)
    return {
        "pdf_sha256": sha256(pdf).hexdigest(),
        "signature": signature,
        "document_timestamp": timestamp,
        "scope": (
            "Local cryptographic, chain and revocation validation using the configured "
            "trust roots; this is not an ITI VALIDAR conformance verdict."
        ),
    }


def execute(config: CliConfig) -> dict[str, object]:
    for required in (
        config.input_pdf,
        config.pfx_file,
        config.signer_trust_roots,
        config.policy_file,
    ):
        if not required.is_file():
            raise SigningError(f"Required file does not exist: {required}")
    if config.input_pdf.resolve() == config.output_pdf.resolve():
        raise SigningError("Output must be different from the original PDF")
    if config.output_pdf.exists():
        raise SigningError(f"Refusing to overwrite existing output: {config.output_pdf}")
    if not timestamp_enabled():
        raise SigningError("SERPRO timestamp configuration is incomplete")

    signed, subject = sign_pdf(config, _read_secret())
    try:
        stamped, timestamp_metadata = apply_serpro_timestamp(signed)
    except Exception as exc:
        raise SigningError("SERPRO document timestamp failed") from exc
    if not timestamp_metadata:
        raise SigningError("SERPRO did not produce a document timestamp")

    verification = verify_final_pdf(stamped, config.signer_trust_roots)
    try:
        config.output_pdf.parent.mkdir(parents=True, exist_ok=True)
        with config.output_pdf.open("xb") as stream:
            stream.write(stamped)
    except OSError as exc:
        raise SigningError(f"Could not create output PDF: {config.output_pdf}") from exc
    return {
        "output": str(config.output_pdf),
        "signer_subject": subject,
        "verification": verification,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("output_pdf", type=Path)
    parser.add_argument("--pfx", type=Path, default=_env_path("ECNPJ_PFX_FILE"))
    parser.add_argument(
        "--signer-trust-roots",
        type=Path,
        default=_env_path("ECNPJ_ICP_TRUST_ROOTS_FILE"),
    )
    parser.add_argument(
        "--policy-file", type=Path, default=_env_path("ECNPJ_SIGNATURE_POLICY_FILE")
    )
    parser.add_argument(
        "--policy-url", default=os.getenv("ECNPJ_SIGNATURE_POLICY_URL", "").strip()
    )
    parser.add_argument("--field-name", default="EmpresaSignature1")
    parser.add_argument(
        "--reason", default="Assinatura digital da pessoa juridica titular do e-CNPJ"
    )
    parser.add_argument("--location", default=None)
    return parser


def main() -> None:
    args = _parser().parse_args()
    missing = [
        name
        for name, value in (
            ("--pfx/ECNPJ_PFX_FILE", args.pfx),
            ("--signer-trust-roots/ECNPJ_ICP_TRUST_ROOTS_FILE", args.signer_trust_roots),
            ("--policy-file/ECNPJ_SIGNATURE_POLICY_FILE", args.policy_file),
            ("--policy-url/ECNPJ_SIGNATURE_POLICY_URL", args.policy_url),
        )
        if not value
    ]
    if missing:
        _parser().error("missing required configuration: " + ", ".join(missing))
    config = CliConfig(
        input_pdf=args.input_pdf,
        output_pdf=args.output_pdf,
        pfx_file=args.pfx,
        signer_trust_roots=args.signer_trust_roots,
        policy_file=args.policy_file,
        policy_url=args.policy_url,
        field_name=args.field_name,
        reason=args.reason,
        location=args.location,
    )
    try:
        result = execute(config)
    except SigningError as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
