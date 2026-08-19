from __future__ import annotations

from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse


def is_hx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def is_cross_origin(request: Request) -> bool:
    """浏览器跨站提交检测：Origin（缺失时看 Referer）与 Host 不符即跨站；两者均缺失放行（非浏览器客户端）。"""
    from urllib.parse import urlsplit

    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        return False
    return urlsplit(source).netloc != request.headers.get("host", "")


def redirect_back(request: Request, default: str = "/", msg: str | None = None, err: str | None = None) -> RedirectResponse:
    target = request.headers.get("referer") or default
    # 去掉旧的消息参数
    if "?" in target:
        base, _, query = target.partition("?")
        params = [
            pair for pair in query.split("&")
            if pair and not pair.startswith("msg=") and not pair.startswith("err=")
        ]
        target = base + ("?" + "&".join(params) if params else "")
    if msg or err:
        separator = "&" if "?" in target else "?"
        target += separator + urlencode(
            {"msg": msg} if msg else {"err": err}
        )
    return RedirectResponse(target, status_code=303)


def hx_fragment(request: Request, html: str, status_code: int = 200):
    if is_hx(request):
        return HTMLResponse(html, status_code=status_code)
    return None


def qs(request: Request, **overrides) -> str:
    params = dict(request.query_params)
    for key, value in overrides.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = str(value)
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    return ("?" + urlencode(clean)) if clean else ""
