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
from helpers import _auth_tokens_from_session


def _status_tab_context() -> dict:
    """Build TOÀN BỘ context cho tab='status' — gọi từ
    blueprints/crawl.py::index() khi tab=status, tách hàm riêng theo
    đúng pattern _maintenance_tab_context() (crawl_maintenance.py) để
    crawl.py không phải biết chi tiết bên trong.

    2 nguồn (company/job) XỬ LÝ ĐỘC LẬP — lỗi lấy 1 nguồn KHÔNG chặn
    phần còn lại hiển thị, giống hành vi cũ. get_company_data_health()
    cần access_token (backend route require_role("ss_team") vì JOIN qua
    contact — thông tin nhạy cảm), khác get_job_data_health() (public,
    chỉ cần API_KEY, giống GET /jobs)."""
    access_token, _ = _auth_tokens_from_session()

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
        # Nhóm job nghi trùng (cùng company + cùng vị trí, đang OPEN).
        "duplicate_job_groups": job_health["duplicate_job_groups"],
        # Company active chưa có contact HR nào — team không có cách
        # chủ động liên hệ hợp tác.
        "company_no_contact_missing": company_health["company_no_contact_missing"],
        "company_no_contact_total": company_health["company_no_contact_total"],
    }
