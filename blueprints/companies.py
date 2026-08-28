"""Companies blueprint - company listing and CRUD operations"""

import math
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user

import crawler_client as db_data
from crawler_client import CrawlerAPIError
import backend_auth
from backend_auth import BackendAuthError
from utils.decorators import staff_required
from constants import COMPANIES_PER_PAGE, PARTNERSHIP_POTENTIALS, CITIES_VN, CONTACT_STATUSES
from helpers import _auth_tokens_from_session, _call_authed, _paginate_args
from potential_score import suggest_partnership_potential

companies_bp = Blueprint("companies", __name__)


@companies_bp.route("/companies")
@staff_required
def index():
    q = request.args.get("q", "").strip()
    city = request.args.get("city", "")
    page, per_page = _paginate_args(COMPANIES_PER_PAGE)

    try:
        cities = db_data.list_company_cities()
        total_companies = db_data.count_companies(q=q, city=city)
        total_pages = max(1, math.ceil(total_companies / per_page))
        if page > total_pages:
            page = total_pages
        companies = db_data.list_companies(q=q, city=city, limit=per_page, offset=(page - 1) * per_page)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies, cities, total_companies, total_pages, page = [], [], 0, 1, 1

    # Gợi ý tiềm năng hợp tác NGAY TRÊN DANH SÁCH (thêm 08/2026) — trước
    # đây suggestion chỉ tính ở trang /companies/<id>/edit vì cần
    # company.jobs + contacts (GET /companies list KHÔNG kèm jobs, xem
    # _normalize_company()). Ở đây dùng list_all_jobs()/list_all_contacts()
    # (2 lệnh gọi TỔNG, đã dùng sẵn kiểu này ở dashboard.py) rồi group theo
    # company_id trong Python — RẺ HƠN NHIỀU so với gọi get_company() +
    # list_contacts() riêng cho từng công ty trong trang (per_page=20 dòng
    # sẽ thành 40 lệnh gọi API nếu làm kiểu N+1). Không chặn trang nếu lỗi
    # — chỉ đơn giản là chip "Tiềm năng" không có tooltip hover.
    if companies:
        access_token, _ = _auth_tokens_from_session()
        try:
            all_jobs = db_data.list_all_jobs()
            all_contacts = db_data.list_all_contacts(access_token) if access_token else []
        except CrawlerAPIError:
            all_jobs, all_contacts = [], []

        jobs_by_company = {}
        for j in all_jobs:
            jobs_by_company.setdefault(j["company_id"], []).append(j)
        contacts_by_company = {}
        for ct in all_contacts:
            contacts_by_company.setdefault(ct["company_id"], []).append(ct)

        for c in companies:
            company_for_score = {**c, "jobs": jobs_by_company.get(c["id"], [])}
            suggestion = suggest_partnership_potential(company_for_score, contacts_by_company.get(c["id"], []))
            suggestion["level_label"] = db_data.PARTNERSHIP_POTENTIAL_MAP.get(suggestion["level"], suggestion["level"])
            c["suggestion"] = suggestion

    return render_template(
        "companies.html", companies=companies, cities=cities,
        filters={"q": q, "city": city}, total_companies=total_companies,
        pagination_filters={k: v for k, v in {"q": q, "city": city}.items() if v},
        page=page, total_pages=total_pages, per_page=per_page,
        partnership_potentials=PARTNERSHIP_POTENTIALS,
    )


@companies_bp.route("/companies/add", methods=["GET", "POST"])
@staff_required
def add():
    if request.method == "POST":
        try:
            company = _call_authed(db_data.create_company, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_company.html", company=request.form, partnership_potentials=PARTNERSHIP_POTENTIALS, cities=CITIES_VN)
        flash(f"Đã thêm công ty {company['company']}.", "success")
        return redirect(url_for("companies.detail", company_id=company["id"]))
    return render_template("add_company.html", company=None, partnership_potentials=PARTNERSHIP_POTENTIALS, cities=CITIES_VN)


@companies_bp.route("/companies/<string:company_id>/edit", methods=["GET", "POST"])
@staff_required
def edit(company_id):
    company = db_data.get_company(company_id)
    if not company:
        abort(404)

    # Gợi ý tiềm năng hợp tác (thêm 08/2026) — CHỈ hiển thị ở trang sửa
    # (company đã có sẵn), không tính ở trang thêm mới vì công ty vừa
    # tạo chưa có job/contact nào, gợi ý sẽ luôn ra LOW vô nghĩa. Lấy
    # thêm contacts (company đã có sẵn .jobs qua get_company() ở trên,
    # nhưng KHÔNG có contacts — cần gọi riêng, giống cách detail() làm).
    access_token, _ = _auth_tokens_from_session()
    try:
        contacts_for_score = db_data.list_contacts(access_token, company_id)
    except CrawlerAPIError:
        # Không chặn trang sửa công ty chỉ vì lấy contacts lỗi — gợi ý
        # thiếu dữ liệu contact vẫn còn hơn không hiện được cả trang.
        contacts_for_score = []
    suggestion = suggest_partnership_potential(company, contacts_for_score)
    suggestion["level_label"] = db_data.PARTNERSHIP_POTENTIAL_MAP.get(suggestion["level"], suggestion["level"])

    if request.method == "POST":
        try:
            updated = _call_authed(db_data.update_company, company_id, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_company.html", company=company, edit_id=company_id, partnership_potentials=PARTNERSHIP_POTENTIALS, cities=CITIES_VN, suggestion=suggestion)
        flash(f"Đã cập nhật công ty {updated['company']}.", "success")
        return redirect(url_for("companies.detail", company_id=company_id))
    return render_template("add_company.html", company=company, edit_id=company_id, partnership_potentials=PARTNERSHIP_POTENTIALS, cities=CITIES_VN, suggestion=suggestion)


@companies_bp.route("/companies/<string:company_id>/potential", methods=["POST"])
@staff_required
def update_potential(company_id):
    """Sửa nhanh riêng field "Tiềm năng" ngay tại bảng danh sách công ty
    (thêm 08/2026, xem lịch sử trao đổi) — KHÔNG cần vào trang /edit đầy
    đủ. Dùng db_data.update_company_potential() (payload tối giản, chỉ 1
    field) thay vì db_data.update_company() (bắt buộc kèm company_name).

    Không yêu cầu note — khác update_status() bên contacts.py (note ở đó
    bắt buộc vì backend chặn cứng cho contact_status)."""
    next_url = request.form.get("next", "")

    def _redirect_back():
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("companies.index"))

    try:
        _call_authed(
            db_data.update_company_potential, company_id,
            request.form.get("partnership_potential", ""),
        )
        flash("Đã cập nhật tiềm năng hợp tác.", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    return _redirect_back()


@companies_bp.route("/companies/<string:company_id>/delete", methods=["POST"])
@staff_required
def delete(company_id):
    """Soft delete"""
    note = (request.form.get("note") or "").strip()
    if not note:
        flash("Xoá công ty bắt buộc phải nhập ghi chú lý do.", "error")
        return redirect(url_for("companies.detail", company_id=company_id))
    try:
        _call_authed(db_data.delete_company, company_id, note)
        flash("Đã xoá công ty (xoá mềm — vẫn xem lại được qua Lịch sử thao tác, JD/contact liên quan không bị mất).", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("companies.detail", company_id=company_id))
    return redirect(url_for("companies.index"))


@companies_bp.route("/companies/<string:company_id>")
@staff_required
def detail(company_id):
    company = db_data.get_company(company_id)
    if not company:
        abort(404)
    access_token, _ = _auth_tokens_from_session()
    try:
        contacts = db_data.list_contacts(access_token, company_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        contacts = []
    return render_template(
        "company_detail.html", company=company, contacts=contacts, statuses=CONTACT_STATUSES,
    )
