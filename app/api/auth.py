from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import generate_token, hash_password, verify_password
from app.models.entities import User
from app.schemas.auth import (
    AuthTokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _session(user: User) -> AuthTokenResponse:
    if user.username in settings.ADMIN_USERNAMES and user.role != "admin":
        user.role = "admin"  # bootstrap admins configured via ADMIN_USERNAMES
    return AuthTokenResponse(user_id=user.id, username=user.username, role=user.role, token=generate_token(user.id))


@router.post("/register", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED)
async def register(request: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user account."""
    query = select(User).where(User.username == request.username)
    result = await db.execute(query)
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    user = User(
        username=request.username,
        email=request.email,
        password_hash=hash_password(request.password),
        role="student",
    )
    db.add(user)
    await db.flush()
    return _session(user)


@router.post("/login", response_model=AuthTokenResponse)
async def login(request: UserLoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate and obtain token."""
    query = select(User).where(User.username == request.username)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    return _session(user)


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Retrieve the signed-in user (also used by clients to validate a stored token)."""
    return user
