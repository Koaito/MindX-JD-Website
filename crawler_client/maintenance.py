"""
Maintenance — tab "Bảo trì dữ liệu" trong trang "Vận hành dữ liệu"
(08/2026, xem lịch sử trao đổi "phương án B — generic runner dùng
chung", CHỈ admin bấm chạy được, ss_team đọc lịch sử được — xem
blueprints/crawl_maintenance.py). Gọi các endpoint backend: POST
/maintenance/{job_type}, GET /maintenance/{run_id}, GET /maintenance
(lịch sử), GET /maintenance/{run_id}/logs, GET
/maintenance/latest-log-runs — xem sql/migration_add_maintenance_runs.sql
phía backend để biết đầy đủ thiết kế.

ĐỐI XỨNG crawler_client/crawl.py — khác ở 2 điểm:
  1. 5 job_type có SHAPE stats KHÁC NHAU (khác crawl chỉ 1 shape 8 field
     cố định) -> MAINTENANCE_STAT_LABELS là dict {job_type: [...]} thay
     vì 1 list phẳng.
  2. get_maintenance_latest_log_runs() trả {job_type: run|None} cho CẢ
     5 job_type 1 lần gọi, khác get_crawl_latest_log_run() chỉ trả 1
     nguồn (trang có 5 card cố định, không lặp qua get_sources() động
     như crawl).
"""

from .base import _request

# Nhãn tiếng Việt cho 5 job_type — NGUỒN SỰ THẬT DUY NHẤT phía frontend,
# khớp đúng MAINTENANCE_JOB_TYPES ở api/schemas/maintenance.py phía
# backend (chỉ khai lại tên, không import chéo qua HTTP được). Thêm job
# thứ 6 sau này: thêm 1 dòng ở đây + 1 dòng MAINTENANCE_STAT_LABELS bên
# dưới là đủ, KHÔNG cần sửa gì khác ở blueprints/templates (đều tự lặp
# qua MAINTENANCE_JOBS).
MAINTENANCE_JOBS = [
    {
        "job_type": "backfill_company_profiles",
        "label": "Vá hồ sơ công ty",
        # 08/2026 — viết lại theo đúng bảng đối chiếu script (README):
        # vá industry/company_size/address/website (+ products_services
        # nhặt kèm), đọc từ source_profile_url đã lưu (đúng trang
        # TopCV/VietnamWorks/CareerViet gốc) — miễn phí, chỉ tốn thời
        # gian chờ, không gọi API trả phí nào.
        "description": "Vá industry, company_size, address, website (kèm products_services) — đọc lại đúng trang nguồn đã lưu (source_profile_url). Miễn phí, chỉ tốn thời gian chờ.",
        "costs_money": False,
    },
    {
        "job_type": "enrich_profile_from_website",
        "label": "Tra cứu từ website công ty",
        # 08/2026 — theo bảng: vá industry/products_services, đọc từ
        # companies.website + 1 lần gọi Gemini/công ty để phân loại
        # (không dùng Tavily) — chi phí rẻ, không phải miễn phí tuyệt
        # đối nhưng cũng không thuộc diện "TỐN PHÍ THẬT" như 2 job dưới.
        "description": "Vá industry, products_services — đọc companies.website + 1 lần gọi Gemini/công ty để phân loại. Chi phí rẻ (không dùng Tavily).",
        "costs_money": False,
    },
    {
        "job_type": "enrich_web_info",
        "label": "Tra cứu web (Tavily + Gemini)",
        # 08/2026 — theo bảng: vá website/tax_id, đọc từ Tavily search (2
        # query/công ty) + Gemini trích xuất — tốn phí nhất trong 5 job,
        # chỉ nên chạy cho công ty chưa có source_profile_url.
        "description": "Vá website, tax_id — Tavily search (2 query/công ty) + Gemini trích xuất. TỐN PHÍ THẬT, tốn nhất trong 5 job — chỉ nên chạy cho công ty chưa có source_profile_url.",
        "costs_money": True,
    },
    {
        "job_type": "get_fb_linkedin",
        "label": "Tìm Facebook/LinkedIn công ty",
        # 08/2026 (sửa mô tả sai): job này KHÔNG gọi Tavily/Gemini — xem
        # get_company_fb_linkedin_link.py, chỉ crawl HTML thô
        # (curl_cffi + BeautifulSoup) từ companies.website đã có sẵn để
        # tìm link social ngay trên site công ty, hoàn toàn miễn phí.
        # Giới hạn thật: site dạng SPA/React/Next.js render bằng JS thì
        # HTML thô rỗng, script không đọc được — không phải chi phí tiền.
        "description": "Vá fanpage_url, linkedin_url — đọc companies.website (crawl HTML thô). Miễn phí, nhưng giới hạn với site dạng SPA/React (render bằng JS).",
        "costs_money": False,
    },
    {
        "job_type": "check_expired_jobs",
        "label": "Dọn job hết hạn",
        "description": "Kiểm tra deadline + kiểm tra link job còn sống không, tự đóng job đã hết hạn/nguồn đã gỡ.",
        "costs_money": False,
        "supports_dry_run": True,
    },
]

# job_type -> label, dùng tra cứu nhanh ở nơi khác (route/template) thay
# vì tự lặp MAINTENANCE_JOBS mỗi lần cần 1 nhãn.
MAINTENANCE_JOB_LABELS = {j["job_type"]: j["label"] for j in MAINTENANCE_JOBS}

# 08/2026 — BẮT BUỘC truyền "limit" cho job này khi trigger (khớp
# MAINTENANCE_JOB_TYPES_REQUIRE_LIMIT phía backend, xem
# api/schemas/maintenance.py) — form ở _maintenance_tab.html tự thêm
# `required` cho input limit của đúng card này (lớp chặn ĐẦU, backend
# 400 là lớp chặn CUỐI, không phải duy nhất).
#
# 08/2026 (sửa bug) — TRƯỚC ĐÂY còn có "get_fb_linkedin" trong set này
# theo giả định sai (còn sót lại từ trước khi mô tả job này được sửa
# đúng ở trên — job KHÔNG gọi Tavily/Gemini, hoàn toàn miễn phí), khiến
# card "Tìm Facebook/LinkedIn công ty" luôn ép nhập limit dù không có
# rủi ro tốn phí gì nếu để trống chạy hết. Đã đồng bộ lại đúng với
# MAINTENANCE_JOB_TYPES_REQUIRE_LIMIT phía backend.
MAINTENANCE_JOB_TYPES_REQUIRE_LIMIT = frozenset({"enrich_web_info"})

# Chỉ job_type này nhận dry_run/check_deadline_only — card của job_type
# khác KHÔNG render 2 checkbox này (xem _maintenance_tab.html).
MAINTENANCE_CHECK_EXPIRED_JOB_TYPE = "check_expired_jobs"

# Thứ tự + nhãn tiếng Việt cho `stats` từng job_type — đọc trực tiếp từ
# docstring/nội dung THẬT của 5 file run() phía backend (Scrap_JD/
# backfill_company_profiles.py, enrich_company_profile_from_website.py,
# enrich_company_web_info.py, get_company_fb_linkedin_link.py,
# check_expired_source_jobs.py), KHÔNG suy đoán — giữ CỐ ĐỊNH thứ tự
# này, dùng chung cho cả bảng lịch sử (server-render) lẫn card "đang
# chạy" (JS đọc lại đúng key để không định nghĩa nhãn 2 lần).
MAINTENANCE_STAT_LABELS = {
    "backfill_company_profiles": [
        ("checked", "Đã kiểm tra"),
        ("updated", "Đã vá"),
        ("unchanged", "Không đổi"),
        ("unknown_domain", "Domain lạ (bỏ qua)"),
        ("errors", "Lỗi"),
    ],
    "enrich_profile_from_website": [
        ("checked", "Đã kiểm tra"),
        ("updated", "Đã cập nhật"),
        ("industry_updated", "Đã vá ngành nghề"),
        ("products_services_updated", "Đã vá sản phẩm/dịch vụ"),
        ("low_confidence", "Độ tin cậy thấp (bỏ qua)"),
        ("no_page_content", "Không đọc được trang (bỏ qua)"),
        ("errors", "Lỗi"),
    ],
    "enrich_web_info": [
        ("checked", "Đã kiểm tra"),
        ("updated", "Đã cập nhật"),
        ("no_result", "Không tìm thấy kết quả"),
        ("website_name_mismatch", "Tên/website lệch nhau (bỏ qua)"),
        ("merged_duplicate_company", "Gộp công ty trùng"),
        ("errors", "Lỗi"),
    ],
    "get_fb_linkedin": [
        ("checked", "Đã kiểm tra"),
        ("updated", "Đã cập nhật"),
        ("no_link_found", "Không tìm thấy link"),
        ("found_via_subpage", "Tìm thấy qua trang con"),
        ("linkedin_personal_only_skipped", "Chỉ có LinkedIn cá nhân (bỏ qua)"),
        ("website_is_social_domain", "Website đã là social domain (bỏ qua)"),
        ("likely_js_rendered", "Trang cần JS render (bỏ qua)"),
        ("challenge_page", "Bị chặn bởi trang challenge"),
        ("fetch_failed", "Lỗi tải trang"),
    ],
    "check_expired_jobs": [
        ("checked", "Đã kiểm tra"),
        ("expired_by_deadline", "Đóng do quá deadline"),
        ("expired_by_source_dead", "Đóng do nguồn đã gỡ"),
        ("still_alive", "Vẫn còn sống"),
        ("cần_kiểm_tra_tay", "Cần kiểm tra tay"),
    ],
}

MAINTENANCE_STATUS_LABELS = {
    "queued": "Đang chờ", "running": "Đang chạy",
    "done": "Hoàn tất", "error": "Lỗi",
}
# Dùng lại đúng class badge đã có cho crawl (public/css/15-crawl.css) —
# cùng ý nghĩa status, không cần định nghĩa badge riêng.
MAINTENANCE_STATUS_BADGE = {
    "queued": "badge-info", "running": "badge-info",
    "done": "badge-success", "error": "badge-danger",
}


def _normalize_maintenance_run(raw: dict) -> dict:
    stats = raw.get("stats") or {}
    job_type = raw.get("job_type") or ""
    stat_labels = MAINTENANCE_STAT_LABELS.get(job_type, [])
    params = raw.get("params") or {}
    return {
        "run_id": raw.get("run_id"),
        "job_type": job_type,
        "job_label": MAINTENANCE_JOB_LABELS.get(job_type, job_type),
        "status": raw.get("status") or "",
        "status_label": MAINTENANCE_STATUS_LABELS.get(raw.get("status"), raw.get("status") or ""),
        "status_badge": MAINTENANCE_STATUS_BADGE.get(raw.get("status"), "badge-warning"),
        "params": params,
        "limit": params.get("limit"),
        "dry_run": params.get("dry_run", False),
        "check_deadline_only": params.get("check_deadline_only", False),
        "triggered_by": raw.get("triggered_by"),
        # None -> "Hệ thống (tự động)": dành sẵn cho chạy lịch tự động
        # sau này (chưa làm) — cùng quy ước triggered_by_name ở
        # _normalize_crawl_run().
        "triggered_by_name": raw.get("triggered_by_name") or "Hệ thống (tự động)",
        "started_at": raw.get("started_at"),
        "finished_at": raw.get("finished_at"),
        "stats": stats,
        # Danh sách (label, value) đúng thứ tự MAINTENANCE_STAT_LABELS[job_type]
        # — chỉ có khi status='done' (stats rỗng thì template tự ẩn).
        "stat_items": [(label, stats.get(key, 0)) for key, label in stat_labels] if stats else [],
        "error": raw.get("error") or "",
    }


def trigger_maintenance_run(access_token, *, job_type, limit=None,
                             dry_run=None, check_deadline_only=None) -> dict:
    """POST /maintenance/{job_type} — trả {"run_id", "job_type", "status":
    "queued"} NGAY, KHÔNG đợi chạy xong.

    BẮT BUỘC access_token của admin thật (backend require_admin trả 403
    nếu ss_team thường gọi) — route Flask gọi hàm này PHẢI tự chặn
    trước bằng @admin_required (xem blueprints/crawl_maintenance.py),
    cùng nguyên tắc trigger_crawl().

    limit=None nghĩa là "chạy hết, không giới hạn" — BẮT BUỘC truyền số
    thật cho job_type trong MAINTENANCE_JOB_TYPES_REQUIRE_LIMIT (backend
    400 nếu thiếu, xem docstring hằng số đó ở trên).

    dry_run/check_deadline_only CHỈ có tác dụng khi job_type ==
    MAINTENANCE_CHECK_EXPIRED_JOB_TYPE — backend 400 nếu truyền ở
    job_type khác.

    Raise CrawlerAPIError(status_code=409) nếu job_type này đang có 1
    lượt 'queued'/'running' chưa xong — nơi gọi (route) PHẢI bắt riêng
    để flash đúng message backend trả (đã sẵn tiếng Việt)."""
    payload = {}
    if limit is not None:
        payload["limit"] = limit
    if dry_run is not None:
        payload["dry_run"] = dry_run
    if check_deadline_only is not None:
        payload["check_deadline_only"] = check_deadline_only
    return _request(
        "POST", f"/maintenance/{job_type}", access_token=access_token, json=payload,
    )


def get_maintenance_status(access_token, run_id) -> dict:
    """GET /maintenance/{run_id} — poll tiến độ/kết quả 1 lượt chạy.
    Trả None nếu run_id không tồn tại (404) — nơi gọi (route Flask) tự
    quyết định coi đây là lỗi hay không, cùng quy ước get_crawl_status()."""
    raw = _request("GET", f"/maintenance/{run_id}", access_token=access_token)
    return _normalize_maintenance_run(raw) if raw else None


def list_maintenance_runs(access_token, *, job_type="", status="", triggered_by="",
                           limit=50, offset=0) -> dict:
    """GET /maintenance — danh sách lịch sử, phân trang. Trả {"items": [...], "total": int}."""
    params = {"limit": limit, "offset": offset}
    if job_type:
        params["job_type"] = job_type
    if status:
        params["status"] = status
    if triggered_by:
        params["triggered_by"] = triggered_by
    data = _request("GET", "/maintenance", access_token=access_token, params=params) or {}
    items = [_normalize_maintenance_run(r) for r in data.get("items", [])]
    return {"items": items, "total": data.get("total", 0)}


def get_maintenance_logs(access_token, run_id, after_id=0, limit=500) -> dict:
    """GET /maintenance/{run_id}/logs?after_id=N — khu "Xem log live" ở
    tab Bảo trì dữ liệu, cùng cách hoạt động get_crawl_logs() (poll tăng
    dần theo after_id, KHÔNG normalize thêm)."""
    return _request(
        "GET", f"/maintenance/{run_id}/logs", access_token=access_token,
        params={"after_id": after_id, "limit": limit},
    ) or {"last_id": after_id, "items": []}


def get_maintenance_latest_log_runs(access_token) -> dict:
    """GET /maintenance/latest-log-runs — khung "Log live" của MỖI
    trong 5 card job_type gọi lúc mở trang để biết run_id GẦN NHẤT (bất
    kể status) mà nó nên hiện log — KHÁC get_crawl_latest_log_run() ở
    chỗ trả đủ 5 job_type CÙNG 1 LẦN (dict {job_type: run|None}) thay vì
    1 nguồn, vì trang có 5 card cố định cần hiện log riêng biệt cho
    từng card cùng lúc lúc tải trang (5 lần gọi API riêng sẽ chậm hơn
    không cần thiết).

    Backend (db.get_latest_maintenance_run_per_job_type) CHỈ trả key
    cho job_type ĐÃ từng chạy ít nhất 1 lần — hàm này tự lặp qua
    MAINTENANCE_JOBS để LUÔN trả đủ 5 key, job_type nào backend không
    trả (chưa từng chạy) -> value None (KHÔNG phải lỗi, template tự
    hiện "Chưa có lượt chạy nào."), cùng quy ước get_crawl_latest_log_run()."""
    raw = _request("GET", "/maintenance/latest-log-runs", access_token=access_token) or {}
    return {
        j["job_type"]: (
            _normalize_maintenance_run(raw[j["job_type"]]) if raw.get(j["job_type"]) else None
        )
        for j in MAINTENANCE_JOBS
    }
