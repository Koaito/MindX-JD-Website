"""Helper functions dùng chung toàn app (session token, phân trang, ngày
tháng...).

LƯU Ý QUAN TRỌNG — lý do file này tồn tại:
Trước khi tách blueprint, các hàm dưới đây (đặc biệt `_call_authed` và
`_paginate_args`) bị COPY-PASTE thủ công vào 10 file blueprint khác
nhau. Trong lúc copy, 2 blueprint (`activity_logs.py`,
`data_management.py`) bị dán nhầm 1 bản `_call_authed` CŨ, ĐƠN GIẢN HƠN
— không có logic tự refresh token khi access token hết hạn (401). Hậu
quả: trang Activity Logs và Data Management sẽ crash 500 (lỗi
CrawlerAPIError không được bắt) sau ~30 phút đăng nhập, trong khi các
trang khác (jobs/companies/contacts) vẫn tự refresh êm ru. Đây là 1 bug
ẩn, khó phát hiện vì chỉ xảy ra sau khi access token hết hạn.

Gom về đây để chỉ có DUY NHẤT 1 bản mỗi hàm — sửa 1 nơi, có hiệu lực ở
toàn bộ app.
"""

from datetime import datetime

from flask import request, session
from markupsafe import Markup, escape

import backend_auth
from backend_auth import BackendAuthError
from crawler_client import CrawlerAPIError


# ---------------------------------------------------------------------------
# Session token helpers
# ---------------------------------------------------------------------------

def _store_auth_tokens(access_token, refresh_token):
    session["access_token"] = access_token
    session["refresh_token"] = refresh_token


def _clear_auth_tokens():
    session.pop("access_token", None)
    session.pop("refresh_token", None)


def _auth_tokens_from_session():
    return session.get("access_token"), session.get("refresh_token")


def _call_authed(fn, *args, **kwargs):
    """Gọi 1 hàm crawler_client với access token trong session. Nếu backend
    trả 401 (access token hết hạn), tự refresh rồi gọi lại 1 lần."""
    access_token, refresh_token = _auth_tokens_from_session()
    try:
        return fn(access_token, *args, **kwargs)
    except CrawlerAPIError as exc:
        if exc.status_code != 401 or not refresh_token:
            raise
        try:
            pair = backend_auth.refresh(refresh_token)
        except BackendAuthError:
            _clear_auth_tokens()
            raise CrawlerAPIError(
                "Phiên đăng nhập đã hết hạn — vui lòng đăng nhập lại.",
                status_code=401,
            )
        _store_auth_tokens(pair["access_token"], pair["refresh_token"])
        return fn(pair["access_token"], *args, **kwargs)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def _paginate_args(default_per_page):
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    if page < 1:
        page = 1
    return page, default_per_page


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_any_date(value):
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    for parser in (
        lambda s: datetime.fromisoformat(s),
        lambda s: datetime.strptime(s, "%Y-%m-%d"),
    ):
        try:
            return parser(text).date()
        except ValueError:
            continue
    return None


def format_date(value, fmt="%d/%m/%Y"):
    if not value:
        return "—"
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        for parser in (
            lambda s: datetime.fromisoformat(s),
            lambda s: datetime.strptime(s, "%Y-%m-%d"),
        ):
            try:
                return parser(text).strftime(fmt)
            except ValueError:
                continue
        return value
    try:
        return value.strftime(fmt)
    except AttributeError:
        return "—"


def _jobs_by_month(jobs, date_field, months_back=6, only_past=False):
    today = datetime.now().date()
    month_keys = []
    y, m = today.year, today.month
    for _ in range(months_back):
        month_keys.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    month_keys.reverse()

    counts_by_key = {key: 0 for key in month_keys}
    for job in jobs:
        d = _parse_any_date(job.get(date_field))
        if d is None:
            continue
        if only_past and d >= today:
            continue
        key = (d.year, d.month)
        if key in counts_by_key:
            counts_by_key[key] += 1

    labels = ["%02d/%d" % (m, y) for (y, m) in month_keys]
    counts = [counts_by_key[key] for key in month_keys]
    return labels, counts


# ---------------------------------------------------------------------------
# Template filters
# ---------------------------------------------------------------------------

def to_bullets(value):
    if not value:
        return ""
    lines = [ln.strip(" \t-•*") for ln in value.splitlines()]
    lines = [ln for ln in lines if ln]
    if len(lines) <= 1:
        return Markup("<p>{}</p>").format(value)
    items = "".join("<li>{}</li>".format(escape(ln)) for ln in lines)
    return Markup("<ul class=\"jd-bullets\">{}</ul>").format(Markup(items))
