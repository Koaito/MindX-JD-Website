"""Trang gộp "Thêm mới" (/them-moi) — 3 tab Job / Công ty / Người liên
hệ (08/2026, xem lịch sử trao đổi "phương án A+ — tách partial, gộp
shell, giữ nguyên 3 route POST cũ").

QUAN TRỌNG — đọc trước khi sửa:

1. Blueprint này CHỈ chứa GET /them-moi (hiện shell 3 tab). KHÔNG có
   route POST nào ở đây — logic tạo job/công ty/người liên hệ VẪN nằm
   nguyên ở jobs.add()/companies.add()/contacts.add_any() như trước
   (KHÔNG di chuyển 1 dòng nào), cố ý để giữ rủi ro thấp (xem lịch sử
   trao đổi so sánh phương án A/B/A+). 3 route đó IMPORT
   _add_hub_context() từ đây để render lại ĐÚNG shell này (giữ tab-bar,
   đúng tab đang nhập, giữ dữ liệu đã gõ) khi validate lỗi — thay vì
   render_template("add_job.html"/"add_company.html"/"add_contact.html")
   đứng riêng như code cũ.

2. _add_hub_context() là helper DÙNG CHUNG cho GET ở đây LẪN 3 nhánh
   lỗi POST bên jobs.py/companies.py/contacts.py — cố ý gom vào 1 chỗ
   (không để mỗi route tự dựng context riêng) vì danh sách công ty
   (companies) cần load ĐÚNG 1 LẦN, dùng chung cho cả tab job và tab
   contact — bài học từ data_management.py (trước đó "chỉ tải
   export_companies lúc đang ở tab export" để né round-trip thừa, giờ
   ngược lại: có nhiều nơi cùng cần company list nên gom 1 chỗ để KHÔNG
   ai vô tình gọi lại 2-3 lần).

3. GET /jobs/add, /companies/add, /contacts/add (route cũ, endpoint
   jobs.add/companies.add/contacts.add_any khi method=GET) giờ
   redirect thẳng về đây — xem code trong 3 blueprint đó. Cùng
   precedent với /saved-jobs -> /profile/saved-jobs (xem
   blueprints/profile.py, blueprints/my_stuff.py).
"""
from flask import Blueprint, render_template, request

import crawler_client as db_data
from constants import (
    CITIES_VN,
    INDUSTRIES,
    LOCATIONS,
    PARTNERSHIP_POTENTIALS,
    SALARY_PERIODS,
    SALARY_TYPES,
    WORK_TYPES,
)
from crawler_client import CrawlerAPIError
from utils.decorators import staff_required

add_hub_bp = Blueprint("add_hub", __name__)

VALID_TABS = ("job", "company", "contact")


def _add_hub_context(active_tab="job", job_form=None, company_form=None, contact_form=None):
    """Dựng context cho shell 3 tab. Gọi từ GET /them-moi (mọi form đều
    None -> 3 tab trống) HOẶC từ nhánh lỗi POST của jobs.add()/
    companies.add()/contacts.add_any() (form tương ứng = request.form
    để giữ lại dữ liệu đã nhập, xem docstring đầu file).

    active_tab: tab nào active lúc render — GET đọc từ ?tab=, nhánh lỗi
    POST luôn set đúng tab của chính form vừa submit sai."""
    if active_tab not in VALID_TABS:
        active_tab = "job"

    # Company list dùng CHUNG cho tab job (combobox _company_combobox.html)
    # và tab contact (cũng combobox đó) — gọi ĐÚNG 1 LẦN ở đây, không để
    # 2 tab tự gọi lại. list_all_companies() tự phân trang 200/lần bên
    # trong (xem crawler_client/companies.py) — cùng loại lệnh gọi
    # "kéo hết" mà bài học data_management.py đã nhắc tới.
    try:
        companies = db_data.list_all_companies()
    except CrawlerAPIError:
        companies = []

    return {
        "active_tab": active_tab,
        # ---- tab job ----
        "job": job_form,
        "industries": INDUSTRIES,
        "levels": db_data.get_level_codes(),
        "locations": LOCATIONS,
        "work_types": WORK_TYPES,
        "salary_types": SALARY_TYPES,
        "salary_periods": SALARY_PERIODS,
        "companies": companies,
        # ---- tab company ----
        "company": company_form,
        "partnership_potentials": PARTNERSHIP_POTENTIALS,
        "cities": CITIES_VN,
        # ---- tab contact ----
        "contact": contact_form,
    }


@add_hub_bp.route("/them-moi")
@staff_required
def index():
    tab = request.args.get("tab", "job")
    return render_template("add_hub.html", **_add_hub_context(active_tab=tab))
