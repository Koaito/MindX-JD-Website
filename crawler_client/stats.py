"""Thống kê tổng hợp cho dashboard — không thuộc riêng domain nào."""

from .base import _request


def get_stats() -> dict:
    """GET /stats — tổng job, tổng công ty, tổng đơn ứng tuyển (total_applications,
    thêm 08/2026)... Chỉ cần API key, không cần access_token. Dùng cho dashboard."""
    return _request("GET", "/stats") or {}


def get_engagement_stats() -> dict:
    """GET /stats/engagement (thêm 08/2026, cùng lúc dashboard 4 tab) —
    trả {"jobs": [...], "monthly": {...}}:
    - jobs: MỌI job đang OPEN kèm application_count/saved_count gộp sẵn
      (dùng lọc "JD sắp hết hạn chưa ai quan tâm" / "JD ế" phía
      dashboard() mà không phải gọi N+1 request cho từng job).
    - monthly: tổng ứng tuyển/lưu job THÁNG NÀY vs THÁNG TRƯỚC, dùng
      tính % chênh lệch cho tab "Báo cáo tháng".
    Chỉ cần API key, không cần access_token — giống get_stats()."""
    return _request("GET", "/stats/engagement") or {}
