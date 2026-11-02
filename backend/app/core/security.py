import ipaddress
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.database.models import User

password_hasher = PasswordHasher()
bearer_scheme = HTTPBearer(auto_error=False)
LOCAL_USER_ID = str(uuid5(NAMESPACE_URL, "aether:single-user-local-profile"))
LOCAL_USER_EMAIL = "local-user@example.com"


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": str(UUID(user_id)), "iat": now, "exp": expires_at},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp"]},
        )
        return str(UUID(payload["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise ValueError("Invalid access token") from None


async def get_local_user(session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.id == LOCAL_USER_ID))
    if user is not None:
        return user

    user = User(
        id=LOCAL_USER_ID,
        email=LOCAL_USER_EMAIL,
        name="Local User",
        password_hash=hash_password(secrets.token_urlsafe(48)),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        user = await session.scalar(select(User).where(User.id == LOCAL_USER_ID))
        if user is None:
            raise
    else:
        await session.refresh(user)
    return user


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if settings.local_auth_mode:
        if request.client is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local access only")
        try:
            if not ipaddress.ip_address(request.client.host).is_loopback:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local access only")
        except ValueError:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local access only") from None
        return await get_local_user(session)

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized

    try:
        user_id = decode_access_token(credentials.credentials)
    except ValueError:
        raise unauthorized from None

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise unauthorized
    return user
