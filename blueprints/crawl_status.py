"""Context cho tab "Tình trạng dữ liệu" ở trang "Vận hành dữ liệu"
(08/2026, xem lịch sử trao đổi). Cho admin thấy nhanh company/job đang
thiếu field nào/tỉ lệ bao nhiêu — KHÔNG cần vào thẳng database, đúng vấn
đề gốc nêu ra: admin không có quyền DB để tự biết dữ liệu đang thiếu gì.

KHÁC blueprints/crawl_maintenance.py ở chỗ tab này CHỈ ĐỌC (không có
form trigger/route POST nào) nên KHÔNG cần dùng chung `crawl_bp` — không
có route nào phải đăng ký, `_status_tab_context()` được
blueprints/crawl.py::index() gọi trực tiếp và import Ở ĐẦU file (không
cần import trễ như crawl_maintenance.py, vì file đó phải import ngược
`crawl_bp` từ blueprints.crawl mới vướng vòng lặp — file này thì
không).

ĐÃ ĐỔI (08/2026, xem lịch sử trao đổi "crawl_status.py nặng nhất trong
các route đã audit"): trước đây dùng list_all_companies()/
list_all_jobs(include_content=True)/list_all_contacts() — kéo TOÀN BỘ
company/job (kèm cột parsed_content JSONB dài)/contact trong DB về
Flask rồi tự đếm/group/tìm trùng bằng Python (company_field_health()/
job_field_health()/list_expired_open_jobs()/job_health_by_source()/
find_duplicate_job_groups()/count_companies_without_contact() ở
crawler_client/). Nặng hơn cả case /companies cũ vì có thêm field JSONB
— chi phí round-trip + kích thước payload tỉ lệ thuận với TỔNG SỐ
company/job/contact trong toàn hệ thống, kể cả khi tab này chỉ cần vài
con số tổng hợp.

Giờ dùng 2 endpoint mới ở backend (get_company_data_health()/
get_job_data_health() bên scrap-jd-api) — backend tự tính bằng SQL
GROUP BY/COUNT FILTER, KHÔNG BAO GIỜ serialize parsed_content qua
network, chi phí không còn tăng theo tổng số record toàn hệ thống nữa,
chỉ còn 2 round-trip cố định."""

from flask import flash

import crawler_client as db_data
from crawler_client import CrawlerAPIError
from helpers import _auth_tokens_from_session, _parse_any_date


def _annotate_duplicate_keep_suggestion(groups):
    """THÊM 09/2026 (xem lịch sử trao đổi "job nghi trùng lặp — thêm
    nút thao tác được", hướng 2 "gợi ý nên giữ job nào") — gán thêm
    key 'suggest_keep' (True/False/None) vào TỪNG job trong mỗi nhóm
    duplicate_job_groups (sửa tại chỗ, group['jobs'] là list dict).

    Cả 2 job trong 1 nhóm đều đang "Đang tuyển" (OPEN) nên KHÔNG thể
    dựa vào status để phân biệt — chỉ còn deadline là tín hiệu sẵn có
    (không cần gọi thêm API nào): deadline thường = ngày crawl + N ngày
    cố định theo từng nguồn, nên bản crawl SAU sẽ có deadline XA HƠN.
    Coi job có deadline xa nhất trong nhóm là bản "mới hơn, nên giữ".

    CHỈ gợi ý khi có CĂN CỨ RÕ RÀNG: ít nhất 2 job parse được deadline
    VÀ các deadline đó không trùng nhau hết — nếu không, mọi job trong
    nhóm nhận suggest_keep=None (không hiện badge gì, để ss_team tự
    xem xét) thay vì đoán bừa. True chỉ gán cho ĐÚNG 1 job (deadline xa
    nhất, duy nhất) — các job còn lại (kể cả job không parse được
    deadline) nhận False."""
    for group in groups:
        jobs = group.get("jobs") or []
        parsed = [(_parse_any_date(j.get("deadline")), j) for j in jobs]
        valid_dates = {d for d, _ in parsed if d is not None}
        if len(valid_dates) < 2:
            for _, j in parsed:
                j["suggest_keep"] = None
            continue
        latest = max(valid_dates)
        for d, j in parsed:
            j["suggest_keep"] = (d == latest)
    return groups


def _status_tab_context() -> dict:
    """Build TOÀN BỘ context cho tab='status' — gọi từ
    blueprints/crawl.py::index() khi tab=status, tách hàm riêng theo
    đúng pattern _maintenance_tab_context() (crawl_maintenance.py) để
    crawl.py không phải biết chi tiết bên trong.

    2 nguồn (company/job) XỬ LÝ ĐỘC LẬP — lỗi lấy 1 nguồn KHÔNG chặn
    phần còn lại hiển thị, giống hành vi cũ. get_company_data_health()
    cần access_token (backend route require_role("ss_team") vì JOIN qua
    contact — thông tin nhạy cảm), khác get_job_data_health() (public,
    chỉ cần API_KEY, giống GET /jobs).

    WIDGET CHÉO (KHÔI PHỤC 09/2026, xem docstring đầu
    blueprints/crawl.py "khôi phục ss_team xem được" — cùng đợt sửa):
    tab 'status' TỰ NÓ không có job nền nào, nên hiện CẢ 2 loại (crawl
    lẫn bảo trì) đang chạy — khác 2 tab kia chỉ cần hiện thêm ĐÚNG 1
    loại còn thiếu. Import 2 hàm *_raw() TRỄ (không ở đầu file) vì lúc
    module này được import (ở ĐẦU blueprints/crawl.py, TRƯỚC khi
    crawl_bp/các hàm khác trong file đó tồn tại — xem docstring phần
    trên) mà import ngược blueprints.crawl/blueprints.crawl_maintenance
    ở đây sẽ vỡ vòng lặp ngay lúc khởi động app. Để trong hàm này thì an
    toàn vì nó chỉ CHẠY lúc có request, lúc đó cả 2 module kia đã load
    xong hoàn toàn."""
    from blueprints.crawl import _SOURCE_LABELS, _all_active_crawl_runs_raw
    from blueprints.crawl_maintenance import _active_maintenance_runs_raw

    access_token, _ = _auth_tokens_from_session()

    try:
        cross_crawl_active_runs = _all_active_crawl_runs_raw(access_token)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        cross_crawl_active_runs = {}

    try:
        cross_maintenance_active_runs = _active_maintenance_runs_raw(access_token)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        cross_maintenance_active_runs = {}

    try:
        company_health = db_data.get_company_data_health(access_token)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        company_health = {
            "company_health_rows": [], "company_health_total": 0,
            "company_no_contact_missing": 0, "company_no_contact_total": 0,
        }

    try:
        job_health = db_data.get_job_data_health()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        job_health = {
            "job_health_rows": [], "job_health_total": 0,
            "expired_open_jobs": [], "job_health_by_source": [],
            "duplicate_job_groups": [],
        }
    else:
        _annotate_duplicate_keep_suggestion(job_health["duplicate_job_groups"])

    return {
        "company_health_rows": company_health["company_health_rows"],
        "company_health_total": company_health["company_health_total"],
        "job_health_rows": job_health["job_health_rows"],
        "job_health_total": job_health["job_health_total"],
        # Job đã hết hạn (deadline < hôm nay) nhưng status vẫn OPEN —
        # dữ liệu "rác" hiển thị nhầm học viên thấy job còn tuyển.
        "expired_open_jobs": job_health["expired_open_jobs"],
        # Breakdown job_field_health() theo từng nguồn crawl (TopCV/
        # VietnamWorks/CareerViet/MANUAL/Không rõ nguồn) — biết nguồn
        # nào cần ưu tiên sửa parser.
        "job_health_by_source": job_health["job_health_by_source"],
        # Nhóm job nghi trùng (cùng company + cùng vị trí, đang OPEN) —
        # mỗi job trong group['jobs'] đã có thêm 'suggest_keep'
        # (True/False/None, xem _annotate_duplicate_keep_suggestion()
        # ở trên) để template hiện badge gợi ý + nút "Đóng job này".
        "duplicate_job_groups": job_health["duplicate_job_groups"],
        # Company active chưa có contact HR nào — team không có cách
        # chủ động liên hệ hợp tác.
        "company_no_contact_missing": company_health["company_no_contact_missing"],
        "company_no_contact_total": company_health["company_no_contact_total"],
        # cross_crawl_active_runs/cross_maintenance_active_runs + nhãn —
        # widget nổi (_status_tab.html, MỚI thêm 09/2026) dùng để hiện
        # CẢ 2 loại job nền đang chạy, xem docstring ở trên.
        "cross_crawl_active_runs": cross_crawl_active_runs,
        "cross_maintenance_active_runs": cross_maintenance_active_runs,
        "cross_crawl_labels": _SOURCE_LABELS,
        "cross_maintenance_labels": db_data.MAINTENANCE_JOB_LABELS,
        "cross_crawl_status_labels": db_data.CRAWL_STATUS_LABELS,
        "cross_maintenance_status_labels": db_data.MAINTENANCE_STATUS_LABELS,
    }
