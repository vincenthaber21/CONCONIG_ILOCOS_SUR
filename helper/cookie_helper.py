import os
from typing import Any, Optional


def set_secure_cookie(
    response: Any,
    key: str,
    value: Any,
    *,
    max_age: Optional[int] = None,
    samesite: str = "Strict",
    secure: Optional[bool] = None,
    httponly: bool = True,
) -> None:
    """
    Set a cookie with secure defaults.

    By default, cookie transmission is restricted to HTTPS in production
    (`PRODUCTION=true`) and blocked from JavaScript access (`HttpOnly`).
    """
    if secure is None:
        secure = os.environ.get("PRODUCTION", "False").lower() == "true"

    response.set_cookie(
        key,
        value,
        max_age=max_age,
        samesite=samesite,
        secure=secure,
        httponly=httponly,
    )
