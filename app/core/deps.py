from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_token
from app.models.entities import User


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the signed bearer token to a user, or 401."""
    user_id = verify_token(authorization)
    user = await db.get(User, user_id) if user_id else None
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


async def same_user(request: Request, user: User = Depends(get_current_user)) -> User:
    """Router guard for endpoints that name a ``user_id`` (query, path or JSON body): it must be the caller's.

    Admins may act for any user.
    """
    claimed = request.path_params.get("user_id") or request.query_params.get("user_id")
    if claimed is None and request.method in ("POST", "PUT", "PATCH") and \
            request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()  # cached on the request; FastAPI reuses it for the body model
        except ValueError:
            body = None
        claimed = body.get("user_id") if isinstance(body, dict) else None
    if claimed is not None and claimed != user.id and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only access your own data")
    return user
