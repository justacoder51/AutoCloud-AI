"""Server-side identity token for a configured private Cloud Run API."""

from urllib.parse import urlsplit


def api_headers(url: str, mode: str = "none") -> dict:
    if mode == "none":
        return {}
    parsed = urlsplit(url)
    if (mode != "cloudrun" or parsed.scheme != "https" or not parsed.hostname
            or not parsed.hostname.endswith(".run.app") or parsed.username or parsed.password
            or parsed.port or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Cloud Run authentication requires a configured HTTPS run.app origin")
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import fetch_id_token

    token = fetch_id_token(Request(), url.rstrip("/"))
    # Send both Authorization (for Cloud Run edge IAM, where GFE strips the signature)
    # and X-AutoCloud-Authorization (preserved intact for cryptographic verification).
    return {
        "Authorization": f"Bearer {token}",
        "X-AutoCloud-Authorization": f"Bearer {token}",
    }
