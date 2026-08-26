"""
Crawl — trang "Crawl dữ liệu" (08/2026, CHỈ admin thấy/dùng, xem
utils/decorators.py::admin_required + blueprints/crawl.py). Gọi các
endpoint backend: GET /sources, POST /crawl, GET /crawl/{run_id},
GET /crawl (lịch sử), GET /crawl/{run_id}/logs, GET /crawl/latest-log-run
— xem sql/migration_add_crawl_runs.sql và
sql/migration_add_crawl_progress_logs.sql phía backend để biết đầy đủ
thiết kế.
"""

from .base import _request

# Thứ tự + nhãn tiếng Việt cho 8 chỉ số trong `stats` (dict trả về từ
# pipeline.run_pipeline() phía backend, xem docstring CrawlStatusOut).
# Giữ CỐ ĐỊNH thứ tự này — dùng chung cho cả bảng lịch sử (server-render)
# lẫn card "đang chạy" cập nhật qua JS (xem crawl.html, JS đọc lại đúng
# 8 key này để không phải định nghĩa nhãn 2 lần ở 2 nơi).
CRAWL_STAT_LABELS = [
    ("inserted", "Job mới"),
    ("fetched", "Tổng lấy về"),
    ("skipped_duplicate", "Trùng URL (bỏ qua)"),
    ("skipped_duplicate_repost", "Đăng lại (bỏ qua)"),
    ("updated_existing", "Đã vá job cũ"),
    ("skipped_fetch_failed", "Lỗi fetch JD (bỏ qua)"),
    ("skipped_anonymous_employer", "NTD ẩn danh (bỏ qua)"),
    ("errors", "Lỗi khác"),
]

CRAWL_STATUS_LABELS = {
    "queued": "Đang chờ", "running": "Đang chạy",
    "done": "Hoàn tất", "error": "Lỗi",
}
# Map sang class badge có sẵn (public/css/12-activity-logs.css) — thêm
# badge-info riêng cho 'queued'/'running' (chưa có sẵn, xem
# public/css/15-crawl.css, 2 màu status đó CHƯA tồn tại trong hệ badge
# success/warning/danger cũ, vốn chỉ dành cho action log Thêm/Sửa/Xoá).
CRAWL_STATUS_BADGE = {
    "queued": "badge-info", "running": "badge-info",
    "done": "badge-success", "error": "badge-danger",
}


def _normalize_crawl_run(raw: dict) -> dict:
    stats = raw.get("stats") or {}
    return {
        "run_id": raw.get("run_id"),
        "status": raw.get("status") or "",
        "status_label": CRAWL_STATUS_LABELS.get(raw.get("status"), raw.get("status") or ""),
        "status_badge": CRAWL_STATUS_BADGE.get(raw.get("status"), "badge-warning"),
        "source": raw.get("source") or "",
        "category": raw.get("category") or "",
        "pages": raw.get("pages"),
        "max_jobs": raw.get("max_jobs"),
        "triggered_by": raw.get("triggered_by"),
        # None -> "Hệ thống (tự động)": dành sẵn cho crawl lịch tự động
        # sau này (chưa làm), KHÔNG phải lỗi dữ liệu — cùng quy ước
        # actor_name ở audit_logs.py.
        "triggered_by_name": raw.get("triggered_by_name") or "Hệ thống (tự động)",
        "started_at": raw.get("started_at"),
        "finished_at": raw.get("finished_at"),
        "stats": stats,
        # Danh sách (label, value) đúng thứ tự CRAWL_STAT_LABELS — chỉ
        # có khi status='done' (stats rỗng thì thôi, template tự ẩn).
        "stat_items": [(label, stats.get(key, 0)) for key, label in CRAWL_STAT_LABELS] if stats else [],
        "error": raw.get("error") or "",
        # 08/2026 (heartbeat/tiến độ real-time, xem docstring backend
        # api/schemas/crawl.py::CrawlStatusOut) — snapshot mới nhất
        # {"fetched", "inserted", "last_update"}, None nếu chưa có
        # heartbeat nào (status vẫn 'queued', hoặc lượt crawl chạy
        # TRƯỚC KHI tính năng này tồn tại).
        "progress": raw.get("progress"),
    }


def get_sources() -> dict:
    """GET /sources — KHÔNG cần access_token (route backend chỉ yêu cầu
    X-API-Key, tự thêm sẵn trong mọi _request() — không có JWT nào ở
    đây), khác hẳn các hàm bên dưới đều bắt buộc access_token thật.

    Trả {"topcv": {"data-analyst": "Data Analyst", ...}, "vietnamworks": {...}}
    — CHỈ 2 nguồn (careerviet chưa có adapter đăng ký ở crawl_runner.py
    phía backend, xem lịch sử trao đổi — KHÔNG phải thiếu sót ở đây)."""
    return _request("GET", "/sources") or {}


def trigger_crawl(access_token, *, source, category, pages=None, max_jobs=None) -> dict:
    """POST /crawl — trả {"run_id": ..., "status": "queued"} NGAY, KHÔNG
    đợi crawl xong (có thể mất vài phút — vài chục phút).

    BẮT BUỘC access_token của admin (role='admin' thật, backend
    require_admin sẽ trả 403 nếu ss_team thường gọi) — route Flask gọi
    hàm này PHẢI tự chặn trước bằng @admin_required (xem
    blueprints/crawl.py), không dựa vào backend 403 làm lớp chặn duy
    nhất (lớp chặn chính ở frontend để UX rõ ràng hơn, backend là lớp
    chặn cuối phòng gọi thẳng URL).

    Raise CrawlerAPIError(status_code=409) nếu nguồn này đang có 1 lượt
    'queued'/'running' chưa xong — nơi gọi (route) PHẢI bắt riêng để
    flash đúng message backend trả (đã sẵn tiếng Việt, dễ hiểu)."""
    payload = {"source": source, "category": category}
    if pages is not None:
        payload["pages"] = pages
    if max_jobs is not None:
        payload["max_jobs"] = max_jobs
    return _request("POST", "/crawl", access_token=access_token, json=payload)


def get_crawl_status(access_token, run_id) -> dict:
    """GET /crawl/{run_id} — poll tiến độ/kết quả 1 lượt. BẮT BUỘC
    access_token (role tối thiểu 'ss_team' ở backend — nhưng route Flask
    ở đây vẫn luôn gọi qua @admin_required, chặt hơn mức backend yêu
    cầu, đúng yêu cầu gốc "chỉ admin thấy và dùng" của trang này)."""
    raw = _request("GET", f"/crawl/{run_id}", access_token=access_token)
    return _normalize_crawl_run(raw) if raw else None


def list_crawl_runs(access_token, *, source="", status="", triggered_by="",
                     limit=50, offset=0) -> dict:
    """GET /crawl — danh sách lịch sử, phân trang. Trả {"items": [...], "total": int}."""
    params = {"limit": limit, "offset": offset}
    if source:
        params["source"] = source
    if status:
        params["status"] = status
    if triggered_by:
        params["triggered_by"] = triggered_by
    data = _request("GET", "/crawl", access_token=access_token, params=params) or {}
    items = [_normalize_crawl_run(r) for r in data.get("items", [])]
    return {"items": items, "total": data.get("total", 0)}


def get_crawl_logs(access_token, run_id, after_id=0, limit=500) -> dict:
    """GET /crawl/{run_id}/logs?after_id=N — khu "Xem log live" ở
    trang /crawl (08/2026, xem docstring backend api/routers/crawl.py::
    get_crawl_logs). Trả {"last_id": int, "items": [{"id","level",
    "message","created_at"}, ...]} y hệt response backend, KHÔNG cần
    normalize thêm (không có mapping nhãn/badge nào áp dụng cho dòng
    log thô, khác _normalize_crawl_run ở trên).

    after_id: truyền đúng "last_id" của lần gọi TRƯỚC để chỉ nhận dòng
    MỚI — route Flask (blueprints/crawl.py::logs_json) truyền thẳng
    query string từ JS xuống đây, không tự ý đổi giá trị."""
    return _request(
        "GET", f"/crawl/{run_id}/logs", access_token=access_token,
        params={"after_id": after_id, "limit": limit},
    ) or {"last_id": after_id, "items": []}


def get_crawl_latest_log_run(access_token) -> dict:
    """GET /crawl/latest-log-run — khung "Log live" (LUÔN HIỆN cố định
    trên trang /crawl, 08/2026, xem lịch sử trao đổi) gọi lúc mở trang
    để biết run_id GẦN NHẤT (bất kể status) mà nó nên hiện log, và tiếp
    tục poll định kỳ (mỗi 6s, xem crawl.html) để tự chuyển sang run mới
    ngay khi phát hiện có lượt crawl khác bắt đầu.

    Trả None (KHÔNG raise lỗi) nếu bảng crawl_runs rỗng hoàn toàn (chưa
    từng crawl lần nào) — route Flask (blueprints/crawl.py::
    latest_log_run) tự bọc lại thành {"run_id": None} cho JS, đây là
    trạng thái hợp lệ chứ không phải lỗi — cùng quy ước response_model
    Optional[CrawlStatusOut] ở backend."""
    raw = _request("GET", "/crawl/latest-log-run", access_token=access_token)
    return _normalize_crawl_run(raw) if raw else None
