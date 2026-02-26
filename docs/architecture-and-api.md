# Architecture and API Examples

This document provides a high-level architecture map and minimal API examples
for local development and integration testing.

## System Overview

`a2a-client-hub` is a client hub for user-managed and admin-managed A2A agents.

- Frontend (`frontend/`): Expo / React Native / Web client.
- Backend (`backend/`): FastAPI API layer, auth, persistence, scheduling, and
  A2A runtime integration.
- Database: PostgreSQL with Alembic migrations.

## Runtime Data Flow

1. User signs in via backend auth endpoints.
2. Frontend stores access token in memory and refreshes session via HttpOnly cookie.
3. User manages A2A agents (personal or hub catalog entries).
4. Backend validates and proxies outbound A2A requests with host allowlist rules.
5. Chat/session flows are persisted and surfaced in frontend tabs and detail screens.

## Key Backend Modules

- `app/api/routers/`: HTTP route definitions
- `app/services/`: domain and orchestration services
- `app/integrations/`: outbound A2A clients/extensions
- `app/db/models/`: SQLAlchemy models
- `app/core/`: config, security, logging

## API Base URL

Default local backend base URL:

```text
http://127.0.0.1:8000/api/v1
```

In shell examples below:

```bash
export API_BASE_URL="http://127.0.0.1:8000/api/v1"
```

## Authentication Examples

### Register

```bash
curl -X POST "$API_BASE_URL/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email":"alice@example.com",
    "name":"Alice",
    "password":"Pass123!",
    "timezone":"UTC",
    "invite_code":"replace-with-invite-code"
  }'
```

### Login

```bash
curl -i -X POST "$API_BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email":"alice@example.com",
    "password":"Pass123!"
  }'
```

Save the `access_token` from the response and keep the returned refresh cookie.

### Get Current User

```bash
curl "$API_BASE_URL/auth/me" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

## Agent Management Examples

### Create Personal Agent

```bash
curl -X POST "$API_BASE_URL/me/a2a/agents" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"My Agent",
    "card_url":"https://agent.example.com/.well-known/agent-card.json",
    "auth_type":"none",
    "enabled":true,
    "tags":["demo"]
  }'
```

### List Personal Agents

```bash
curl "$API_BASE_URL/me/a2a/agents?page=1&size=20" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

### Validate Agent Card

```bash
curl -X POST "$API_BASE_URL/me/a2a/agents/<AGENT_ID>/card:validate" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

## Session / Invoke Examples

### Invoke Agent via HTTP

```bash
curl -X POST "$API_BASE_URL/me/a2a/agents/<AGENT_ID>/invoke" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "query":"Summarize today'\''s key updates",
    "userMessageId":"550e8400-e29b-41d4-a716-446655440000",
    "agentMessageId":"550e8400-e29b-41d4-a716-446655440001"
  }'
```

`userMessageId` and `agentMessageId` are optional but recommended for
client/server message identity consistency. Both must be UUID strings when provided.

### Query Unified Sessions

```bash
curl -X POST "$API_BASE_URL/me/conversations:query" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "page": 1,
    "size": 20,
    "agent_id": "<AGENT_ID>"
  }'
```

`agent_id` is optional. When provided, the result is server-side filtered for
that agent only.

### Query Unified Session Messages

```bash
curl -X POST "$API_BASE_URL/me/conversations/<CONVERSATION_ID>/messages:query" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "page": 1,
    "size": 50
  }'
```

`messages:query` returns message headers only (id/role/created_at/metadata).
Message bodies are loaded from block endpoints for all roles.

### Query Message Blocks (Batch)

```bash
curl -X POST "$API_BASE_URL/me/conversations/<CONVERSATION_ID>/messages/blocks:query" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "messageIds": ["<MESSAGE_ID_1>", "<MESSAGE_ID_2>"],
    "mode": "full"
  }'
```

### Query Message Block Detail

```bash
curl -X POST "$API_BASE_URL/me/conversations/<CONVERSATION_ID>/messages/<MESSAGE_ID>/blocks/<BLOCK_SEQ>:query" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

## Notes

- Keep all timestamps in UTC at rest.
- Validate production configuration for CORS, cookies, origin checks, and key management before deployment.
