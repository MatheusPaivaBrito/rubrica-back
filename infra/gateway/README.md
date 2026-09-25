# Optional Auth/Core Gateway

This Nginx gateway exposes only product routes:

- `/auth/*` forwards to Auth without changing the path;
- `/core/*` forwards to Core and removes the `/core` prefix;
- `/gateway/health` reports gateway health;
- platform APIs are denied by the default `404` route.

Start it with:

```bash
docker compose --env-file .env -f compose/local.yml up -d --build gateway

In production, configure the Cloudflare Tunnel public hostname service URL as
`http://gateway:8080`. Only the gateway binds a host port (`127.0.0.1:7171`);
the web application, APIs, PostgreSQL and Redis remain available only through
the Docker networks.
```

Projects extended after generation can use this command directly even
when their existing Makefile is intentionally left untouched.
