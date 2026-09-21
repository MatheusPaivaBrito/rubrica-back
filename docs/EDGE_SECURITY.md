# Edge security checklist

Production traffic reaches `web` only through Cloudflare Tunnel. Keep the
origin without a published host port; otherwise clients can bypass Cloudflare
and the origin rate limits will be the only DDoS control.

## Cloudflare dashboard

Keep the zone proxied and verify these controls after every DNS or tunnel
change:

1. Leave the HTTP and network DDoS managed rules enabled with their default
   mitigation action. On Free, the Free Managed WAF Ruleset is deployed by
   default; verify that it is active in **Security > WAF > Managed rules**.
2. Enable **Security > Settings > Bot traffic > Bot fight mode** after testing
   the Stripe webhook and normal sign-in. This switch covers the entire zone
   and cannot be exempted per path on Free; leave it off if it breaks those
   machine-to-machine requests.
3. In **Security > Security rules > Create rule > Rate limiting rule**, use the
   Free plan's single rule for `/auth/login`, `/auth/mfa/challenge`,
   `/auth/register`, `/auth/password-recovery` and `/auth/password-reset`.
   Count by IP, start with 10 requests per 10 seconds and action **Block**.
   Path expression:

   ```text
   http.request.uri.path in {"/auth/login" "/auth/mfa/challenge" "/auth/register" "/auth/password-recovery" "/auth/password-reset"}
   ```

   Review Security Events and legitimate login attempts before tightening.
   An interstitial Managed Challenge on an API `fetch` request can break the
   application, so use Block for these JSON endpoints. The application also
   validates a Turnstile token on login and limits login and MFA attempts itself.
4. The contact form already uses Cloudflare Turnstile and verifies the token
   on the Core API; configure its widget and keys using
   [`CONTACT_AND_SEARCH_SETUP.md`](CONTACT_AND_SEARCH_SETUP.md). Do not rely on
   a browser-only CAPTCHA check. The Nginx origin limits `/contact/messages`
   and uploads separately when Free has only one edge rate limit rule.
5. Do not challenge verified search engine bots on `/`, `/robots.txt`,
   `/sitemap.xml`, `/contact`, `/privacy`, `/terms` or `/data-deletion`.
6. Configure origin error-rate notifications. A rise in 429, 502 or 503
   responses should be investigated.

The dashboard settings need to be applied in the Cloudflare account and
verified with Security Events; changing this file does not activate them.

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
