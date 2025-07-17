"""Validation utilities."""
import os
import re
from typing import Optional

def validate_email(email: str) -> bool:
    """Validate email format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_username(username: str) -> bool:
    """Validate username format."""
    # Username must be 3-50 characters, alphanumeric with underscores
    if not 3 <= len(username) <= 50:
        return False
    return re.match(r'^[a-zA-Z0-9_]+$', username) is not None

def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
    """Validate password strength."""
    if len(password) < 6:
        return False, "Password must be at least 6 characters long"
    
    # Additional checks can be added here
    # has_upper = any(c.isupper() for c in password)
    # has_lower = any(c.islower() for c in password)
    # has_digit = any(c.isdigit() for c in password)
    
    return True, None

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage."""
    # Remove path separators and null bytes
    filename = filename.replace("/", "_").replace("\\", "_").replace("\0", "")
    
    # Limit length
    name, ext = os.path.splitext(filename)
    if len(name) > 100:
        name = name[:100]
    
    return name + ext