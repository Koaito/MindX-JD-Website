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

Nguồn dữ liệu: crawler_client.list_all_companies()/list_all_jobs() (đã
tự phân trang sẵn, dùng đúng pattern dashboard.py đang dùng để tính
thống kê) + 2 hàm đếm crawler_client.company_field_health()/
job_field_health() — KHÔNG cần thêm gì phía backend thật (scrap-jd-api),
toàn bộ tính on-the-fly ở đây."""

from flask import flash

import crawler_client as db_data
from crawler_client import CrawlerAPIError


def _status_tab_context() -> dict:
    """Build TOÀN BỘ context cho tab='status' — gọi từ
    blueprints/crawl.py::index() khi tab=status, tách hàm riêng theo
    đúng pattern _maintenance_tab_context() (crawl_maintenance.py) để
    crawl.py không phải biết chi tiết bên trong.

    2 nguồn (company/job) XỬ LÝ ĐỘC LẬP — lỗi lấy company KHÔNG chặn
    phần job hiển thị và ngược lại, giống cách index() bên dashboard.py
    xử lý jobs/companies trong try/except riêng."""
    try:
        companies = db_data.list_all_companies()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies = []

    try:
        jobs = db_data.list_all_jobs()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        jobs = []

    return {
        "company_health_rows": db_data.company_field_health(companies),
        "company_health_total": len(companies),
        "job_health_rows": db_data.job_field_health(jobs),
        "job_health_total": len(jobs),
    }
