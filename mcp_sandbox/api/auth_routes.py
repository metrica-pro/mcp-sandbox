from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from mcp_sandbox.auth.auth import authenticate_user, get_current_active_user
from mcp_sandbox.auth.utils import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_password_hash,
    generate_api_key,
)
from mcp_sandbox.db.database import db
from mcp_sandbox.models.user import User, UserCreate, Token

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/register", response_model=User)
async def register_user(user_data: UserCreate):
    """Register a new user"""
    # Check if user already exists
    existing_user = db.get_user(username=user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    existing_email = db.get_user(email=user_data.email)
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    # Create new user with hashed password
    hashed_password = get_password_hash(user_data.password)
    api_key = generate_api_key()

    user_dict = {
        "username": user_data.username,
        "email": user_data.email,
        "hashed_password": hashed_password,
        "api_key": api_key,
    }

    # Create user in database
    new_user = db.create_user(user_dict)

    # Return user without hashed password
    return User(**new_user)


@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """Get access token for login"""
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """Get current logged in user"""
    return current_user


@router.get("/users/me/api-key")
async def get_api_key(current_user: User = Depends(get_current_active_user)):
    """Get API key for current user"""
    user = db.get_user(user_id=current_user.id)
    if not user or not user.get("api_key"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        )

    return {"api_key": user["api_key"]}


@router.post("/users/me/api-key/regenerate")
async def regenerate_api_key(current_user: User = Depends(get_current_active_user)):
    """Regenerate API key for current user"""
    new_api_key = generate_api_key()
    updated_user = db.update_user(current_user.id, {"api_key": new_api_key})

    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    return {"api_key": new_api_key}


@router.get("/users/me/sandboxes")
async def get_user_sandboxes(current_user: User = Depends(get_current_active_user)):
    """Get all sandboxes for current user"""
    sandboxes = db.get_user_sandboxes(current_user.id)
    return {"sandboxes": sandboxes}


@router.delete("/users/me/sandboxes/{sandbox_id}")
async def delete_user_sandbox(
    sandbox_id: str, current_user: User = Depends(get_current_active_user)
):
    """Delete a sandbox by ID (both database record and Docker container)"""
    # First, check if the sandbox exists and belongs to the current user
    if not db.is_sandbox_owner(current_user.id, sandbox_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sandbox not found or does not belong to this user",
        )

    # Get the sandbox record to find the Docker container ID
    sandbox_record = db.get_sandbox(sandbox_id)
    if not sandbox_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sandbox not found in database",
        )

    # Create a new instance of SandboxManager to handle Docker containers
    from mcp_sandbox.core.sandbox_modules.manager import SandboxManager
    from mcp_sandbox.utils.config import logger

    sandbox_manager = SandboxManager()

    # Get the Docker container ID from the record
    docker_container_id = sandbox_record.get("docker_container_id")
    if docker_container_id:
        logger.info(
            f"Deleting Docker container with ID: {docker_container_id} for sandbox: {sandbox_id}"
        )
        # Delete the Docker container using the Docker container ID
        result = sandbox_manager.delete_sandbox(docker_container_id)
        if not result.get("success", False):
            # If Docker deletion fails, log the error but continue to remove database record
            logger.error(
                f"Failed to delete Docker container: {result.get('message', 'Unknown error')}"
            )
    else:
        logger.warning(f"No Docker container ID found for sandbox: {sandbox_id}")

    # Delete the sandbox from the database
    if not db.delete_sandbox(sandbox_id):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete sandbox from database",
        )

    return {"message": "Sandbox deleted successfully"}
