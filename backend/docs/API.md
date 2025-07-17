# Messenger API Documentation

## Authentication

All API endpoints except `/auth/login` and `/auth/register` require authentication via JWT token.

Include the token in the Authorization header:
```
Authorization: Bearer <token>
```

## Rate Limiting

API endpoints are rate-limited to 100 requests per minute per IP address.

## WebSocket Protocol

### Connection

Connect to `/ws?token=<jwt_token>`

### Message Format

All WebSocket messages use JSON format:
```json
{
  "type": "event_type",
  "data": {}
}
```

### Error Handling

Errors are returned in the format:
```json
{
  "type": "error",
  "data": {
    "message": "Error description"
  }
}
```

## File Upload Limits

- Maximum file size: 100MB
- Allowed formats: images, videos, audio, PDF, ZIP, text files

## Status Codes

- 200: Success
- 201: Created
- 400: Bad Request
- 401: Unauthorized
- 403: Forbidden
- 404: Not Found
- 413: File Too Large
- 429: Too Many Requests
- 500: Internal Server Error