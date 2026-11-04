#!/usr/bin/env bash
# Fictional evidence-only sandbox example. Machine token must stay server-side.
set -euo pipefail
set +x
: "${RUBRICA_API_BASE:?Set this environment HTTPS origin}"
: "${RUBRICA_COMPARTMENT_ID:?Set the sandbox compartment UUID}"
: "${RUBRICA_API_TOKEN:?Set a sandbox token with the scopes documented in /docs}"
case "$RUBRICA_API_BASE" in https://*) ;; *) echo 'HTTPS origin required' >&2; exit 2;; esac
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
base="${RUBRICA_API_BASE%/}"
api="$base/api/v1/sandbox/compartments/$RUBRICA_COMPARTMENT_ID"
request() { curl --fail-with-body --silent --show-error -H "Authorization: Bearer $RUBRICA_API_TOKEN" "$@"; }
poll() {
  local path="$1" token="$2" status
  for ((attempt=0; attempt<60; attempt++)); do
    curl --fail-with-body --silent --show-error -H "Authorization: Bearer $token" "$path" > "$work/job.json"
    status="$(jq -r .status "$work/job.json")"
    case "$status" in
      succeeded) return 0 ;;
      failed|uncertain|erased) echo "Work requires attention: $status (no automatic signature reissue)" >&2; return 1 ;;
    esac
    sleep 2
  done
  echo 'Polling timeout; consult the same job before retrying' >&2; return 1
}
run_key="sandbox-$(date -u +%Y%m%dT%H%M%S)-$$"
curl --fail --silent --show-error "$base/docs/sample.pdf" > "$work/sample.pdf"
request -X POST "$api/documents?filename=ficticio.pdf" -H 'Content-Type: application/pdf' \
  -H "Idempotency-Key: $run_key-upload" --data-binary "@$work/sample.pdf" > "$work/document.json"
document_id="$(jq -er .id "$work/document.json")"
request -X POST "$api/documents/$document_id/scan" > "$work/scan.json"
poll "$api/jobs/$(jq -er .id "$work/scan.json")" "$RUBRICA_API_TOKEN"
expiry="$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ)"
jq -n --arg id "$document_id" --arg expiry "$expiry" '{document_id:$id, expires_at:$expiry, signers:[{
  external_id:"ficticio-001", name:"Pessoa ficticia", email:"ficticio@example.test", signature_mode:"evidence",
  stamp:{page:1,x:0.5,y:0.8,locale:"pt-BR"}}]}' > "$work/request.json"
request -X POST "$api/signature-requests" -H 'Content-Type: application/json' -H "Idempotency-Key: $run_key-request" \
  --data-binary "@$work/request.json" > "$work/created.json"
request_id="$(jq -er .id "$work/created.json")"
request -X POST "$api/signature-requests/$request_id/open" > "$work/opened.json"
jq '{signer_id:.signers[0].id}' "$work/opened.json" > "$work/signer.json"
request -X POST "$api/signature-requests/$request_id/sessions" -H 'Content-Type: application/json' \
  --data-binary "@$work/signer.json" > "$work/session.json"
signer_token="$(jq -er .session_token "$work/session.json")"
jq '{consent:true,consent_version:"rubrica-enterprise-evidence-v1",document_sha256:.document_sha256}' \
  "$work/opened.json" > "$work/consent.json"
# Simulates a fictional consenting signer only; never use this in place of real consent.
curl --fail-with-body --silent --show-error -X POST "$base/api/v1/sandbox/signing-session/consent" \
  -H "Authorization: Bearer $signer_token" -H 'Content-Type: application/json' --data-binary "@$work/consent.json" > "$work/sign.json"
poll "$base/api/v1/sandbox/signing-session/jobs/$(jq -er .id "$work/sign.json")" "$signer_token"
request "$api/signature-requests/$request_id/artifact" --output "$work/result.pdf"
expected="$(jq -er .result.artifact_sha256 "$work/job.json")"
actual="$(sha256sum "$work/result.pdf" | cut -d ' ' -f 1)"
[[ "$actual" = "$expected" ]] || { echo 'Artifact hash mismatch' >&2; exit 1; }
echo "[ok] Fictional sandbox flow completed; request=$request_id; PDF SHA-256 verified"
