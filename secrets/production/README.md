# Production secrets

Create one local file for each example file in this directory, removing the
.example suffix. Real values are ignored by Git and must exist only on the
production host with mode 0600.

Required files:

- postgres_password
- auth_seed_admin_password
- auth_mfa_encryption_key
- auth_identity_encryption_key
- auth_identity_hmac_key
- notification_internal_service_key
- core_internal_service_key
- resend_api_key
- evidence_secret
- stripe_secret_key
- stripe_webhook_secret
- cloudflare.ini

Generate independent random application secrets; never reuse a database,
administrator, encryption, HMAC or service-to-service secret.

    umask 077
    openssl rand -base64 48 > secrets/production/postgres_password
    openssl rand -base64 48 > secrets/production/auth_seed_admin_password
    openssl rand -base64 48 > secrets/production/auth_mfa_encryption_key
    openssl rand -base64 48 > secrets/production/auth_identity_encryption_key
    openssl rand -base64 48 > secrets/production/auth_identity_hmac_key
    openssl rand -base64 48 > secrets/production/notification_internal_service_key
    openssl rand -base64 48 > secrets/production/core_internal_service_key
    openssl rand -base64 48 > secrets/production/evidence_secret

Paste the Resend and Stripe values into their respective files. For Cloudflare,
copy cloudflare.ini.example to cloudflare.ini and replace its placeholder.

Validate the Compose model without printing secret values:

    docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
