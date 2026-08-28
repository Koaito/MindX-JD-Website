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

Nguồn dữ liệu: crawler_client.list_all_companies()/list_all_jobs()/
list_all_contacts() (đã tự phân trang sẵn, dùng đúng pattern
dashboard.py đang dùng để tính thống kê) + các hàm đếm
company_field_health()/job_field_health()/list_expired_open_jobs()/
job_health_by_source()/find_duplicate_job_groups()/
count_companies_without_contact() — KHÔNG cần thêm gì phía backend thật
(scrap-jd-api), toàn bộ tính on-the-fly ở đây (thêm 08/2026, mở rộng
sau đợt fix bug parsed_content, xem lịch sử trao đổi)."""

from flask import flash

import crawler_client as db_data
from crawler_client import CrawlerAPIError
from helpers import _call_authed


def _status_tab_context() -> dict:
    """Build TOÀN BỘ context cho tab='status' — gọi từ
    blueprints/crawl.py::index() khi tab=status, tách hàm riêng theo
    đúng pattern _maintenance_tab_context() (crawl_maintenance.py) để
    crawl.py không phải biết chi tiết bên trong.

    3 nguồn (company/job/contact) XỬ LÝ ĐỘC LẬP — lỗi lấy 1 nguồn KHÔNG
    chặn phần còn lại hiển thị, giống cách index() bên dashboard.py xử
    lý jobs/companies trong try/except riêng. contact cần access_token
    (list_all_contacts() là route có JWT, khác list_all_jobs()/
    list_all_companies() — public) — dùng _call_authed() (helpers.py)
    đúng pattern mọi route @admin_required khác trong file này đang
    dùng."""
    try:
        companies = db_data.list_all_companies()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies = []

    try:
        # include_content=True (thêm 08/2026) — BẮT BUỘC ở tab này, khác
        # mọi nơi khác đang gọi list_all_jobs() mặc định False. Tab này
        # cần đọc skills/requirements/benefits/description để đếm thiếu
        # (job_field_health()), mà backend GET /jobs mặc định KHÔNG trả
        # parsed_content — thiếu tham số này sẽ quay lại đúng bug cũ (báo
        # sai 100% job thiếu nội dung dù DB có đủ, xem lịch sử trao đổi).
        jobs = db_data.list_all_jobs(include_content=True)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        jobs = []

    try:
        contacts = _call_authed(db_data.list_all_contacts)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        contacts = []

    company_no_contact_missing, company_no_contact_total = db_data.count_companies_without_contact(
        companies, contacts,
    )

    return {
        "company_health_rows": db_data.company_field_health(companies),
        "company_health_total": len(companies),
        "job_health_rows": db_data.job_field_health(jobs),
        "job_health_total": len(jobs),
        # Job đã hết hạn (deadline < hôm nay) nhưng status vẫn OPEN —
        # dữ liệu "rác" hiển thị nhầm học viên thấy job còn tuyển.
        "expired_open_jobs": db_data.list_expired_open_jobs(jobs),
        # Breakdown job_field_health() theo từng nguồn crawl (TopCV/
        # VietnamWorks/CareerViet/MANUAL/Không rõ nguồn) — biết nguồn
        # nào cần ưu tiên sửa parser.
        "job_health_by_source": db_data.job_health_by_source(jobs),
        # Nhóm job nghi trùng (cùng company + cùng vị trí, đang OPEN).
        "duplicate_job_groups": db_data.find_duplicate_job_groups(jobs),
        # Company active chưa có contact HR nào — team không có cách
        # chủ động liên hệ hợp tác.
        "company_no_contact_missing": company_no_contact_missing,
        "company_no_contact_total": company_no_contact_total,
    }
