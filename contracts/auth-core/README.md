# Auth/Core Contract

This contract governs communication between Auth and Core.

Core owns business resources. Auth owns users, roles and revocable browser
sessions. Core forwards a bearer token to `GET /access-control/context`; Auth
returns the authenticated subject, roles and permission keys. Core must never
accept an actor identity from a client payload.
