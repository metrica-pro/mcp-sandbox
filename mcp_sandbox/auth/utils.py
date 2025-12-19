from datetime import datetime, timedelta
from typing import Optional
import secrets
import string
import bcrypt
from jose import jwt

from fastapi.security import OAuth2PasswordBearer

# Security configuration
SECRET_KEY = (
    "your-secret-key-should-be-stored-securely-in-env-vars"  # In production use env var
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 300

# Security settings
BCRYPT_ROUNDS = 12  # Work factor for bcrypt (equivalent to bcrypt__rounds=12)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify that a plain password matches the hashed password"""
    # Convert plain password to bytes if it's not already
    if isinstance(plain_password, str):
        plain_password = plain_password.encode("utf-8")

    # Convert hashed password to bytes if it's not already
    if isinstance(hashed_password, str):
        hashed_password = hashed_password.encode("utf-8")

    # Use bcrypt to verify the password
    try:
        return bcrypt.checkpw(plain_password, hashed_password)
    except ValueError:
        # Handle invalid hash format
        return False


def get_password_hash(password: str) -> str:
    """Hash a password for storing"""
    # Convert password to bytes if it's not already
    if isinstance(password, str):
        password = password.encode("utf-8")

    # Generate a salt with the specified number of rounds
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)

    # Hash the password and convert to string for storage
    hashed = bcrypt.hashpw(password, salt)

    # Return as string for database storage
    return hashed.decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


def generate_api_key() -> str:
    """Generate a secure API key"""
    alphabet = string.ascii_letters + string.digits
    api_key = "".join(secrets.choice(alphabet) for _ in range(32))
    return api_key
