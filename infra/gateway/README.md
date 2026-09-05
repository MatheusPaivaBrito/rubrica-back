# Optional Auth/Core Gateway

This Nginx gateway exposes only product routes:

- `/auth/*` forwards to Auth without changing the path;
- `/core/*` forwards to Core and removes the `/core` prefix;
- `/gateway/health` reports gateway health;
- platform APIs are denied by the default `404` route.

Start it with:

```bash
docker compose -f docker-compose.yml -f docker-compose.gateway.yml                       --profile gateway up -d --build gateway
```

Projects extended after generation can use this command directly even
when their existing Makefile is intentionally left untouched.
