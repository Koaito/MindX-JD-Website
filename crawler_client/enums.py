"""
GET /enums (cache TTL 5 phút) — nguồn thật cho mọi enum backend
(level_code, job_status, work_type...).
"""

import time

from .base import CrawlerAPIError, _request, logger

# CẬP NHẬT 08/2026: TRƯỚC ĐÂY list này hardcode tĩnh ở đây, trùng lặp
# y hệt LEVEL_CODE_VALUES bên backend (constants.py) — nếu backend đổi
# (thêm/bớt level) mà quên sửa tay ở đây thì lệch data ÂM THẦM (không
# lỗi rõ ràng, chỉ dropdown thiếu/sai option). Giờ lấy từ GET /enums
# (api/routers/meta.py backend) qua get_level_codes() bên dưới, có cache
# TTL 5 phút để KHÔNG round-trip mạng mỗi lần mở tab import (vẫn giữ
# đúng lý do hardcode ban đầu — tránh gọi API mỗi request — nhưng không
# còn rủi ro lệch tay nữa).
#
# _LEVEL_CODES_FALLBACK: CHỈ dùng khi gọi GET /enums thất bại (backend
# down/timeout) VÀ chưa có cache nào thành công trước đó — safety net để
# app không crash/trắng dropdown, không phải nguồn sự thật chính.
_LEVEL_CODES_FALLBACK = ["Intern", "Fresher", "Junior", "Middle", "Senior", "Lead", "Manager"]

_ENUMS_CACHE_TTL_SECONDS = 300  # 5 phút — đủ ngắn để nhận thay đổi backend
                                  # nhanh, đủ dài để không gọi API mỗi request
_enums_cache: dict = {"data": None, "fetched_at": 0.0}


def get_enums(force_refresh: bool = False) -> dict:
    """GET /enums (cache TTL 5 phút) — nguồn thật cho mọi enum backend
    (level_code, job_status, work_type...). Thay thế dần các *_MAP hardcode
    ở jobs.py/companies.py/contacts.py nếu cần thêm value mới mà không
    muốn sửa tay ở đó.

    Cache theo tiến trình (process-level, không phải theo user/session) —
    đúng vì enum là dữ liệu toàn cục, không phụ thuộc ai đang đăng nhập.
    Nếu gọi API thất bại: dùng cache cũ (dù đã hết TTL) nếu có, tránh làm
    hỏng trang chỉ vì backend chậm 1 nhịp; chỉ khi CHƯA từng cache thành
    công lần nào mới rơi vào trường hợp rỗng (caller tự xử lý qua
    get_level_codes() có fallback riêng)."""
    now = time.monotonic()
    is_stale = (now - _enums_cache["fetched_at"]) > _ENUMS_CACHE_TTL_SECONDS
    if not force_refresh and _enums_cache["data"] is not None and not is_stale:
        return _enums_cache["data"]

    try:
        data = _request("GET", "/enums") or {}
    except CrawlerAPIError as exc:
        if _enums_cache["data"] is not None:
            logger.warning("GET /enums thất bại (%s) — dùng cache cũ đã hết hạn.", exc)
            return _enums_cache["data"]
        logger.warning("GET /enums thất bại (%s) và chưa có cache nào — trả rỗng.", exc)
        return {}

    _enums_cache["data"] = data
    _enums_cache["fetched_at"] = now
    return data


def get_level_codes() -> list[str]:
    """7 giá trị level_code hợp lệ, dùng cho dropdown "chọn lại level" ở
    bước Import (_dm_import.html) và tính jobs_by_level ở dashboard.
    Lấy từ get_enums() (cache TTL 5 phút); nếu chưa từng cache được lần
    nào (vd lúc app vừa khởi động mà backend đang down), rơi về
    _LEVEL_CODES_FALLBACK để dropdown không bị rỗng hoàn toàn."""
    values = get_enums().get("level_code")
    return values if values else list(_LEVEL_CODES_FALLBACK)
