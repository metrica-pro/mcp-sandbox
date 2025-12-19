from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status

from mcp_sandbox.auth.utils import SECRET_KEY, ALGORITHM, verify_password, oauth2_scheme
from mcp_sandbox.db.database import db
from mcp_sandbox.models.user import TokenData, User


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Get the current authenticated user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception

    user = db.get_user(username=token_data.username)
    if user is None:
        raise credentials_exception

    return User(**user)


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get the current authenticated active user"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def authenticate_user(username: str, password: str) -> Optional[User]:
    """Authenticate a user with username and password"""
    user = db.get_user(username=username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return User(**user)
