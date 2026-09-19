# Edge security checklist

Production traffic reaches `web` only through Cloudflare Tunnel. Keep the
origin without a published host port; otherwise clients can bypass Cloudflare
and the origin rate limits will be the only DDoS control.

## Cloudflare dashboard

Keep the zone proxied and verify these controls after every DNS or tunnel
change:

1. Leave the HTTP and network DDoS managed rules enabled with their default
   mitigation action.
2. Enable the Cloudflare managed WAF ruleset and Bot Fight Mode when available
   on the current plan.
3. Add rate limiting rules for the expensive public commands:
   - `/auth/login`, `/auth/mfa/challenge`, `/auth/register` and
     `/auth/password-recovery`: managed challenge after repeated requests;
   - `/contact/messages`: managed challenge or block after repeated requests;
   - `POST /documents`: block abusive upload rates while allowing authenticated
     users to retry normally.
4. Do not challenge verified search engine bots on `/`, `/robots.txt`,
   `/sitemap.xml`, `/contact`, `/privacy`, `/terms` or `/data-deletion`.
5. Configure origin error-rate notifications. A rise in 429, 502 or 503
   responses should be investigated.

The Nginx configuration is a second layer. It limits connections, API request
rates, body sizes and slow clients. It must not be treated as a replacement for
Cloudflare's distributed mitigation.

## Upload boundary

Only passive, unencrypted PDFs are accepted. The Core API verifies the MIME
type, PDF header and trailer, parser structure, page count and page dimensions,
and rejects JavaScript, automatic actions, embedded files, launch actions,
rich media, XFA and submit/import actions. Accepted bytes are stored unchanged
under an opaque key outside the web root with restrictive permissions.

## Database boundary

Runtime queries use SQLAlchemy expressions and bound parameters. Do not add
SQL assembled from request values. The raw SQL currently present is confined
to static Alembic migrations and contains no request input.
