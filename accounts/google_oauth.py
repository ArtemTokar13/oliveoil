from urllib.parse import urlencode

import requests
from django.conf import settings
from django.urls import reverse

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

REQUEST_TIMEOUT = 10


class GoogleOAuthError(Exception):
    pass


def build_redirect_uri(request):
    return request.build_absolute_uri(reverse("accounts:google_callback"))


def build_authorization_url(request, state):
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": build_redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return f"{AUTHORIZATION_URL}?{urlencode(params)}"


def fetch_userinfo(request, code):
    """Exchange an authorization code for a token, then fetch the Google
    profile. Raises GoogleOAuthError on any failure — callers don't need to
    know whether it was the token exchange or the profile fetch that broke."""
    try:
        token_response = requests.post(
            TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "code": code,
                "redirect_uri": build_redirect_uri(request),
                "grant_type": "authorization_code",
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GoogleOAuthError("No se ha podido contactar con Google.") from exc

    if not token_response.ok:
        raise GoogleOAuthError("Google ha rechazado la solicitud de acceso.")

    access_token = token_response.json().get("access_token")
    if not access_token:
        raise GoogleOAuthError("Google no ha devuelto un token de acceso.")

    try:
        userinfo_response = requests.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GoogleOAuthError("No se ha podido obtener tu perfil de Google.") from exc

    if not userinfo_response.ok:
        raise GoogleOAuthError("No se ha podido obtener tu perfil de Google.")

    return userinfo_response.json()
