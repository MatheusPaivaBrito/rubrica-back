from io import BytesIO

from pypdf import PdfReader

from core_api.modules.tenant.tenant_identity import normalize_cnpj
from toolbox.seeds.local_accounts_catalog import ACCOUNTS, STAGING_ACCOUNTS
from toolbox.seeds.scenario_pdf import scenario_pdf
from toolbox.seeds.staging_workspace_scenarios import _fixture_cnpj


def test_staging_scenarios_use_distinct_test_identities():
    addresses = [email for email, _ in (*ACCOUNTS, *STAGING_ACCOUNTS)]
    assert len(addresses) == len(set(addresses))
    assert all(address.endswith("@example.local") for address in addresses)
    registrations = {normalize_cnpj(_fixture_cnpj(index)) for index in range(1, 17)}
    assert len(registrations) == 16


def test_downloadable_pdf_is_readable_and_labelled():
    reader = PdfReader(BytesIO(scenario_pdf("PDF empresarial de teste", copies=2)))
    assert len(reader.pages) == 2
    assert "Documento fictício" in reader.pages[0].extract_text()
    assert "Página 2 de 2" in reader.pages[1].extract_text()
