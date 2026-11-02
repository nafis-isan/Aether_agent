import asyncio
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlsplit

from app.config import settings


class BrowserPolicyError(ValueError):
    """A browser navigation request violates the local browser policy."""


class BrowserUnavailableError(RuntimeError):
    """The local browser could not be started or used."""


class LocalBrowserManager:
    def __init__(self) -> None:
        self._playwright = None
        self._context = None
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return settings.browser_enabled

    def _allowed_hosts(self) -> set[str]:
        return {host.strip().lower().rstrip(".") for host in settings.browser_allowed_hosts.split(",") if host.strip()}

    def validate_url(self, url: str) -> str:
        if len(url) > 2048:
            raise BrowserPolicyError("Browser URL is too long")
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            port = parsed.port
        except ValueError:
            raise BrowserPolicyError("Browser URL is invalid") from None
        if (
            parsed.scheme.lower() != "https"
            or host is None
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
        ):
            raise BrowserPolicyError("Only HTTPS URLs on the default port are allowed")
        host = host.lower().rstrip(".")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise BrowserPolicyError("IP address navigation is not allowed")
        if host not in self._allowed_hosts():
            raise BrowserPolicyError("This host is not in Aether's browser allowlist")
        return url

    async def _resolve_public_host(self, host: str) -> None:
        loop = asyncio.get_running_loop()
        try:
            addresses = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            raise BrowserPolicyError("The allowed browser host could not be resolved") from None
        if not addresses or any(
            not ipaddress.ip_address(address[4][0]).is_global
            for address in addresses
        ):
            raise BrowserPolicyError("Browser requests to private or non-public networks are blocked")

    async def _guard_request(self, route) -> None:
        try:
            url = self.validate_url(route.request.url)
            host = urlsplit(url).hostname
            if host is None:
                raise BrowserPolicyError("Browser URL is invalid")
            await self._resolve_public_host(host)
        except (BrowserPolicyError, ValueError):
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def _ensure_context(self):
        if not settings.browser_enabled:
            raise BrowserUnavailableError("Local browser automation is disabled")
        if self._context is not None:
            return self._context
        try:
            from playwright.async_api import Error as PlaywrightError, async_playwright
        except ImportError as exc:
            raise BrowserUnavailableError(
                "Playwright is not installed. Install backend requirements and Chromium."
            ) from exc
        try:
            self._playwright = await async_playwright().start()
            profile_dir = Path(settings.browser_profile_dir).expanduser().resolve()
            profile_dir.mkdir(parents=True, exist_ok=True)
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                service_workers="block",
                args=["--no-first-run"],
            )
            await self._context.route("**/*", self._guard_request)
        except (OSError, PlaywrightError) as exc:
            if self._context is not None:
                await self._context.close()
                self._context = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            raise BrowserUnavailableError(
                "Could not start Chromium. Install the Playwright Chromium browser and check the profile directory."
            ) from exc
        return self._context

    async def open(self, url: str) -> dict[str, str]:
        self.validate_url(url)
        host = urlsplit(url).hostname
        if host is None:
            raise BrowserPolicyError("Browser URL is invalid")
        await self._resolve_public_host(host)

        async with self._lock:
            context = await self._ensure_context()
            from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

            pages = context.pages
            page = pages[0] if pages else await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self.validate_url(page.url)
                return {"url": page.url, "title": await page.title()}
            except PlaywrightTimeoutError:
                raise BrowserUnavailableError("The browser timed out while loading the requested page") from None
            except PlaywrightError as exc:
                raise BrowserUnavailableError("The browser could not load the requested page") from exc

    async def read_page(self) -> dict[str, str]:
        async with self._lock:
            context = await self._ensure_context()
            from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

            pages = context.pages
            if not pages:
                raise BrowserUnavailableError("No page is open in Aether's browser")
            page = pages[0]
            self.validate_url(page.url)
            try:
                text = await page.locator("body").inner_text(timeout=10000)
                return {
                    "url": page.url,
                    "title": await page.title(),
                    "text": text[: settings.browser_max_page_chars],
                }
            except PlaywrightTimeoutError:
                raise BrowserUnavailableError("The browser timed out while reading the page") from None
            except PlaywrightError as exc:
                raise BrowserUnavailableError("The browser could not read the current page") from exc

    async def status(self) -> dict[str, str | bool | None]:
        if not settings.browser_enabled:
            return {"enabled": False, "open": False, "url": None, "title": None}
        async with self._lock:
            pages = self._context.pages if self._context is not None else []
            if not pages:
                return {"enabled": True, "open": False, "url": None, "title": None}
            page = pages[0]
            from playwright.async_api import Error as PlaywrightError

            try:
                return {"enabled": True, "open": True, "url": page.url, "title": await page.title()}
            except PlaywrightError as exc:
                raise BrowserUnavailableError("The browser status could not be read") from exc

    async def close(self) -> None:
        async with self._lock:
            context, playwright = self._context, self._playwright
            self._context = None
            self._playwright = None
            try:
                if context is not None:
                    await context.close()
            finally:
                if playwright is not None:
                    await playwright.stop()


_browser_manager = LocalBrowserManager()


def get_browser_manager() -> LocalBrowserManager:
    return _browser_manager
