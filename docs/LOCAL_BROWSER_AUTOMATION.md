# Aether local browser automation

The backend can launch a visible Chromium window with a persistent profile reserved for Aether. It is disabled by default. In this initial implementation, Aether can open an HTTPS page on an exact host allowlist and read limited visible page text. There are no tools for clicking, typing, submitting forms, sending messages, uploading, deleting, purchasing, or posting.

## Setup on Windows

From the repository root, install the backend dependencies and Chromium:

```powershell
cd backend
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Set these values in `backend/.env`:

```dotenv
AETHER_BROWSER_ENABLED=true
AETHER_BROWSER_PROFILE_DIR=C:\Users\YOUR_NAME\.aether\browser-profile
AETHER_BROWSER_ALLOWED_HOSTS=web.whatsapp.com,www.youtube.com,youtube.com,www.instagram.com,instagram.com
AETHER_BROWSER_SHARE_PAGE_CONTENT_WITH_MODEL=false
AETHER_BROWSER_MAX_PAGE_CHARS=12000
```

Use an absolute profile path belonging to your Windows account. Add only exact hostnames you trust. Redirects and page subresources are checked against the same allowlist; add required public hostnames individually if a site's login or assets need them. Requests to IP literals, private/non-public IP addresses, non-HTTPS URLs, non-default ports, and hosts outside the allowlist are blocked.

Start the backend from `backend` with `python -m uvicorn app.main:app --reload`. With `LOCAL_AUTH_MODE=true`, local browser endpoints do not require a bearer token, but the backend still verifies that the request comes from loopback. If local auth mode is disabled, normal API authentication is also required. Do not expose the backend port to your network.

## Manual login and use

With the backend running, open a site in Aether's visible browser:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/browser/open `
  -ContentType 'application/json' `
  -Body '{"url":"https://web.whatsapp.com"}'
```

Complete login yourself in that browser window. The separate profile keeps Aether's site sessions apart from your normal browser. Subsequent requests reuse that profile:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/browser/status
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/browser/read
```

`POST /api/v1/browser/close` closes the browser but preserves its profile. `GET /api/v1/browser/read` returns the page's visible text only to the local API caller.

## Agent access and privacy

When enabled, the assistant can use the restricted `browser_open` tool. The `browser_read` tool is withheld unless both browser automation and `AETHER_BROWSER_SHARE_PAGE_CONTENT_WITH_MODEL=true` are enabled. Page content may contain prompt injection and personal data; when read through the agent tool, it is sent to the configured model provider (currently OpenRouter) and retained with the tool execution/checkpoint data in Aether's database. Keep model sharing disabled unless you explicitly accept both data flows. Page text is truncated to the configured limit and treated as untrusted data.

The browser profile contains login state and cookies. Protect the Windows account and profile directory, and do not copy this profile or reuse it as your normal browser profile. Browser automation can also be restricted by websites; use official APIs for business-critical workflows.
