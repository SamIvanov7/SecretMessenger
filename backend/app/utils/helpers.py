"""Helper utilities."""
from datetime import datetime, timezone
from typing import Any, Dict

def utcnow() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)

def format_datetime(dt: datetime) -> str:
    """Format datetime to ISO string."""
    return dt.isoformat() if dt else None

def dict_without_none(d: Dict[str, Any]) -> Dict[str, Any]:
    """Remove None values from dictionary."""
    return {k: v for k, v in d.items() if v is not None}

def truncate_string(s: str, max_length: int) -> str:
    """Truncate string to max length."""
    if len(s) <= max_length:
        return s
    return s[:max_length-3] + "..."