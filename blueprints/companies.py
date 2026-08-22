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

    return render_template(
        "companies.html", companies=companies, cities=cities,
        filters={"q": q, "city": city}, total_companies=total_companies,
        pagination_filters={k: v for k, v in {"q": q, "city": city}.items() if v},
        page=page, total_pages=total_pages, per_page=per_page,
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
    if request.method == "POST":
        try:
            updated = _call_authed(db_data.update_company, company_id, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_company.html", company=company, edit_id=company_id, partnership_potentials=PARTNERSHIP_POTENTIALS, cities=CITIES_VN)
        flash(f"Đã cập nhật công ty {updated['company']}.", "success")
        return redirect(url_for("companies.detail", company_id=company_id))
    return render_template("add_company.html", company=company, edit_id=company_id, partnership_potentials=PARTNERSHIP_POTENTIALS, cities=CITIES_VN)


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
