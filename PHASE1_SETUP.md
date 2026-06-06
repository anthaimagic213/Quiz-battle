# Phase 1: Social Chat Implementation - Setup Guide

## Overview

Phase 1 implements the social chat foundation with the following components:

**Models:**
- [x] `Friendship` - user friendships
- [x] `FriendRequest` - friend requests (pending/accepted/rejected)
- [x] `Conversation` - direct or group conversations
- [x] `ConversationMember` - membership in conversations
- [x] `Message` - chat messages with soft delete support

**Schemas (Pydantic):**
- [x] `schemas/social.py` - all request/response schemas for social features

**Services (Business Logic):**
- [x] `services/social_service.py` - FriendshipService, ConversationService, MessageService

**API Endpoints:**
- [x] `api/v1/endpoints/friends.py` - friend request & friendship APIs
- [x] `api/v1/endpoints/conversations.py` - conversation management APIs
- [x] `api/v1/endpoints/messages.py` - message APIs (CRUD)

## Structure: Separation of Concerns

```
Request → Endpoint (Route Handler)
  ↓
Schema (Validation)
  ↓
Service (Business Logic)
  ↓
Model (Database)
  ↓
Database
```

Each layer is independent:
- **Routes** handle HTTP concerns only
- **Schemas** validate input/output
- **Services** contain all business logic (no HTTP)
- **Models** are SQLAlchemy ORM definitions

This makes services reusable (e.g., for WebSocket handlers, scheduled tasks, etc.) and easy to test.

## Setup Steps

### 1. Create Database Migration

```bash
cd backend
alembic revision --autogenerate -m "Add social chat tables"
```

This will create a new migration file in `alembic/versions/`. Review it to ensure all social tables are included.

### 2. Run Migration

```bash
alembic upgrade head
```

This creates all social tables in the database.

### 3. Test the Endpoints

You can test the APIs using:
- Swagger UI: `http://localhost:8000/docs`
- curl, Postman, or any API client

**Example API calls:**

```bash
# 1. Send a friend request
POST /api/v1/friends/requests
{
  "addressee_id": "uuid-of-friend"
}

# 2. Get pending friend requests
GET /api/v1/friends/requests/pending

# 3. Accept a friend request
POST /api/v1/friends/requests/{request_id}/respond
{
  "status": "accepted"
}

# 4. Create a direct conversation
POST /api/v1/conversations
{
  "type": "direct",
  "member_ids": ["uuid-of-other-user"]
}

# 5. List conversations
GET /api/v1/conversations

# 6. Send a message
POST /api/v1/conversations/{conversation_id}/messages
{
  "content": "Hello!"
}

# 7. Get messages
GET /api/v1/conversations/{conversation_id}/messages?limit=50&offset=0

# 8. Mark conversation as read
POST /api/v1/conversations/{conversation_id}/messages/{message_id}/mark-read
```

## What's NOT Included Yet

- ❌ WebSocket for real-time chat (Phase 2)
- ❌ AI integration (Phase 3+)
- ❌ Qdrant vector search (Phase 2)
- ❌ Message typing indicators, reactions, etc.

## Next Steps After Phase 1

Once Phase 1 is stable:

1. Add WebSocket endpoint `/ws/chat/{conversation_id}` for real-time messaging
2. Add Redis Pub/Sub for multi-instance WebSocket broadcast
3. Implement Qdrant vector embeddings for quiz retrieval
4. Add AI service integration endpoints

## Database Schema

### friendships
```
id (UUID)
user_id_1 (FK users)
user_id_2 (FK users)
created_at
```

### friend_requests
```
id (UUID)
requester_id (FK users)
addressee_id (FK users)
status (pending|accepted|rejected)
created_at
updated_at
```

### conversations
```
id (UUID)
type (direct|group)
direct_key (indexed, for 1-1 lookups)
title (optional, for groups)
created_at
updated_at
last_message_at (for sorting)
```

### conversation_members
```
id (UUID)
conversation_id (FK conversations)
user_id (FK users)
role (member|admin)
last_read_at
joined_at
```

### messages
```
id (UUID)
conversation_id (FK conversations)
sender_id (FK users)
sender_type (user|ai|system)
content
is_ai_generated
metadata (JSONB, for future AI context)
created_at
updated_at
deleted_at (soft delete)
```

## Authentication

All endpoints require `Authorization: Bearer {token}` header.
The current user is extracted from the JWT token.

## Error Handling

- 400: Bad request (validation, business logic)
- 403: Forbidden (permission denied)
- 404: Not found
- 500: Server error

## Code Organization Rationale

**Why separate services from routes?**
- Testable: Services have no HTTP dependencies
- Reusable: WebSocket handlers, background tasks can use same service
- Maintainable: Business logic is isolated from routing logic

**Why JSONB metadata in messages?**
- Allows storing AI context, citations, retrieval refs without schema changes
- Flexible for future AI features

**Why soft delete on messages?**
- Preserves conversation history
- Allows recovery if needed
- Keeps referential integrity

**Why direct_key for 1-1 conversations?**
- Fast lookup of existing conversation between two users
- Uses sorted UUIDs: `min(user1) | max(user2)`

## Troubleshooting

**Foreign key errors on migration?**
- Ensure User table exists first
- Check cascade rules in migrations

**Unique constraint on friendships?**
- Prevents duplicate friendship between same users
- Both (user1, user2) and (user2, user1) resolve to same friendship

**API returns 403 Forbidden?**
- User must be a member of the conversation
- Check conversation membership in conversation_members table
