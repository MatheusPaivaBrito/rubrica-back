from __future__ import annotations

from hashlib import sha256

import pytest
from asn1crypto import algos, core

from toolbox.sign_pdf_ecnpj import (
    SigningError,
    _IcpBrasilPolicy,
    _policy_identifier,
    _read_secret,
)


class _PolicyInfo(core.Sequence):
    _fields = [("policy_oid", core.ObjectIdentifier)]


def _policy_der() -> tuple[bytes, bytes]:
    policy_info = _PolicyInfo({"policy_oid": "2.16.76.1.7.1.11.1.3"})
    policy_hash = sha256(policy_info.dump()).digest()
    policy = _IcpBrasilPolicy(
        {
            "hash_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
            "policy_info": policy_info,
            "policy_hash": policy_hash,
        }
    )
    return policy.dump(), policy_hash


def test_policy_identifier_uses_digest_stored_inside_policy(tmp_path) -> None:
    policy_der, expected_hash = _policy_der()
    policy_file = tmp_path / "policy.der"
    policy_file.write_bytes(policy_der)

    identifier = _policy_identifier(policy_file, "https://example.test/policy.der")
    policy_id = identifier.chosen

    assert policy_id["sig_policy_id"].native == "2.16.76.1.7.1.11.1.3"
    assert policy_id["sig_policy_hash"]["digest"].native == expected_hash
    assert (
        policy_id["sig_policy_hash"]["digest"].native
        != sha256(policy_der).digest()
    )
    assert policy_id["sig_policy_qualifiers"][0]["sig_qualifier"].native == (
        "https://example.test/policy.der"
    )


def test_policy_identifier_rejects_non_sha256_policy(tmp_path) -> None:
    policy_info = _PolicyInfo({"policy_oid": "2.16.76.1.7.1.11.1.3"})
    policy = _IcpBrasilPolicy(
        {
            "hash_algorithm": algos.DigestAlgorithm({"algorithm": "sha1"}),
            "policy_info": policy_info,
            "policy_hash": b"x" * 20,
        }
    )
    policy_file = tmp_path / "policy.der"
    policy_file.write_bytes(policy.dump())

    with pytest.raises(SigningError, match="does not use SHA-256"):
        _policy_identifier(policy_file, "https://example.test/policy.der")


def test_password_file_is_preferred_and_trailing_newline_is_removed(
    monkeypatch, tmp_path
) -> None:
    password_file = tmp_path / "password"
    password_file.write_text("correct horse battery staple\n", encoding="utf-8")
    monkeypatch.setenv("ECNPJ_PFX_PASSWORD_FILE", str(password_file))
    monkeypatch.setenv("ECNPJ_PFX_PASSWORD", "wrong-fallback")

    assert _read_secret() == b"correct horse battery staple"
