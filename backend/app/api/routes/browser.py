import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.browser.manager import (
    BrowserPolicyError,
    BrowserUnavailableError,
    get_browser_manager,
)
from app.core.security import get_current_user

router = APIRouter(prefix="/api/v1/browser", tags=["local browser"])


class BrowserOpenRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


async def require_loopback(request: Request) -> None:
    if request.client is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local browser access only")
    try:
        is_loopback = ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local browser access only")


def _ensure_enabled() -> None:
    if not get_browser_manager().enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Local browser automation is disabled")


def _to_http_error(error: Exception) -> HTTPException:
    if isinstance(error, BrowserPolicyError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))


@router.get("/status", dependencies=[Depends(require_loopback), Depends(get_current_user)])
async def browser_status() -> dict:
    try:
        return await get_browser_manager().status()
    except BrowserUnavailableError as exc:
        raise _to_http_error(exc) from None


@router.post("/open", dependencies=[Depends(require_loopback), Depends(get_current_user)])
async def open_browser_page(payload: BrowserOpenRequest) -> dict[str, str]:
    _ensure_enabled()
    try:
        return await get_browser_manager().open(payload.url)
    except (BrowserPolicyError, BrowserUnavailableError) as exc:
        raise _to_http_error(exc) from None


@router.get("/read", dependencies=[Depends(require_loopback), Depends(get_current_user)])
async def read_browser_page() -> dict[str, str]:
    _ensure_enabled()
    try:
        return await get_browser_manager().read_page()
    except (BrowserPolicyError, BrowserUnavailableError) as exc:
        raise _to_http_error(exc) from None


@router.post(
    "/close",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_loopback), Depends(get_current_user)],
)
async def close_browser() -> None:
    await get_browser_manager().close()
