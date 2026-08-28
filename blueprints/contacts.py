"""Contacts blueprint - company contact person management"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user

import crawler_client as db_data
from crawler_client import CrawlerAPIError
import backend_auth
from backend_auth import BackendAuthError
from utils.decorators import staff_required
from constants import CONTACT_STATUSES
from helpers import _auth_tokens_from_session, _call_authed

contacts_bp = Blueprint("contacts", __name__)


@contacts_bp.route("/contacts")
@staff_required
def index():
    """Trang "Danh sách contact" — có 2 tab (query param ?tab=...), cùng
    pattern ?tab=export|import ở data_management.py:
      danh-sach : bảng contact gộp toàn hệ thống (hành vi cũ, mặc định)
      quan-ly   : quản lý mẫu email liên hệ (list + form thêm/sửa/xoá)

    Chỉ tab "danh-sach" mới cần load contacts/companies/staff — tab
    "quan-ly" tự load riêng ở _email_templates_tab() bên dưới, tránh
    gọi API thừa không dùng tới khi đang ở tab kia."""
    tab = request.args.get("tab", "danh-sach")
    if tab not in ("danh-sach", "quan-ly"):
        tab = "danh-sach"

    if tab == "quan-ly":
        return _email_templates_tab()

    status_vn = request.args.get("status", "")
    company_id = request.args.get("company_id", "")
    search = request.args.get("q", "").strip()

    status_raw = db_data.CONTACT_STATUS_MAP_REV.get(status_vn, "") if status_vn else ""

    access_token, _ = _auth_tokens_from_session()
    try:
        contacts = db_data.list_all_contacts(
            access_token, status_raw=status_raw, company_id=company_id, search=search,
        )
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        contacts = []

    try:
        companies = db_data.list_all_companies()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies = []

    try:
        all_users = backend_auth.list_users(access_token)
        staff_members = [u for u in all_users if u.get("role") in ("ss_team", "admin")]
    except BackendAuthError as exc:
        flash(str(exc), "error")
        staff_members = []
    staff_by_id = {u["ss_user_id"]: u for u in staff_members}

    return render_template(
        "contacts.html", tab=tab, contacts=contacts, companies=companies, statuses=CONTACT_STATUSES,
        staff_members=staff_members, staff_by_id=staff_by_id,
        filters={"status": status_vn, "company_id": company_id, "q": search},
    )


def _email_templates_tab():
    """Tab "Quản lý mẫu email" (/contacts?tab=quan-ly) — danh sách mẫu +
    2 form thêm/sửa render trực tiếp trong _email_template_manager.html
    (không route riêng /contacts/email-templates/add, giữ mọi thao tác
    trong 1 trang, giống style _dm_import.html gộp nhiều bước 1 chỗ)."""
    access_token, _ = _auth_tokens_from_session()
    try:
        templates = db_data.list_email_templates(access_token)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        templates = []

    try:
        placeholder_help = db_data.get_placeholder_help(access_token)
    except CrawlerAPIError:
        placeholder_help = {}

    edit_id = request.args.get("edit", "")
    editing = None
    if edit_id:
        try:
            editing = db_data.get_email_template(access_token, edit_id)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
        if editing is None and edit_id:
            flash("Không tìm thấy mẫu email cần sửa (có thể đã bị xoá).", "error")

    return render_template(
        "contacts.html", tab="quan-ly", templates=templates,
        placeholder_help=placeholder_help, editing=editing,
        status_choices=db_data.CONTACT_STATUS_CHOICES, status_map=db_data.CONTACT_STATUS_MAP,
    )


@contacts_bp.route("/contacts/email-templates/add", methods=["POST"])
@staff_required
def email_template_add():
    recommended_for = request.form.getlist("recommended_for")
    form = {**request.form.to_dict(), "recommended_for": recommended_for}
    try:
        _call_authed(db_data.create_email_template, form)
        flash("Đã thêm mẫu email.", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    return redirect(url_for("contacts.index", tab="quan-ly"))


@contacts_bp.route("/contacts/email-templates/<string:template_id>/edit", methods=["POST"])
@staff_required
def email_template_edit(template_id):
    recommended_for = request.form.getlist("recommended_for")
    form = {**request.form.to_dict(), "recommended_for": recommended_for}
    try:
        _call_authed(db_data.update_email_template, template_id, form)
        flash("Đã cập nhật mẫu email.", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("contacts.index", tab="quan-ly", edit=template_id))
    return redirect(url_for("contacts.index", tab="quan-ly"))


@contacts_bp.route("/contacts/email-templates/<string:template_id>/delete", methods=["POST"])
@staff_required
def email_template_delete(template_id):
    note = (request.form.get("note") or "").strip()
    if not note:
        flash("Xoá mẫu email bắt buộc phải nhập ghi chú lý do.", "error")
        return redirect(url_for("contacts.index", tab="quan-ly"))
    try:
        _call_authed(db_data.delete_email_template, template_id, note)
        flash("Đã xoá mẫu email.", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    return redirect(url_for("contacts.index", tab="quan-ly"))


@contacts_bp.route("/contacts/add", methods=["GET", "POST"])
@staff_required
def add_any():
    """Add contact without company context"""
    try:
        companies = db_data.list_all_companies()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies = []

    if request.method == "POST":
        company_id = request.form.get("company_id", "")
        if not company_id:
            flash("Cần chọn công ty.", "error")
            return render_template("add_contact.html", company=None, companies=companies, contact=request.form)
        try:
            _call_authed(db_data.create_contact, company_id, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_contact.html", company=None, companies=companies, contact=request.form)
        flash("Đã thêm người liên hệ.", "success")
        return redirect(url_for("contacts.index"))

    return render_template("add_contact.html", company=None, companies=companies, contact=None)


@contacts_bp.route("/companies/<string:company_id>/contacts/add", methods=["GET", "POST"])
@staff_required
def add(company_id):
    """Add contact in company context"""
    company = db_data.get_company(company_id)
    if not company:
        abort(404)
    if request.method == "POST":
        try:
            _call_authed(db_data.create_contact, company_id, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_contact.html", company=company, contact=request.form)
        flash("Đã thêm người liên hệ.", "success")
        return redirect(url_for("companies.detail", company_id=company_id))
    return render_template("add_contact.html", company=company, contact=None)


@contacts_bp.route("/companies/<string:company_id>/contacts/<string:contact_id>/edit", methods=["GET", "POST"])
@staff_required
def edit(company_id, contact_id):
    access_token, _ = _auth_tokens_from_session()
    contact = db_data.get_contact(access_token, company_id, contact_id)
    company = db_data.get_company(company_id)
    if not contact or not company:
        abort(404)
    if request.method == "POST":
        try:
            _call_authed(
                db_data.update_contact, company_id, contact_id, request.form,
                request.form.get("activity_note", ""),
            )
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_contact.html", company=company, contact=contact, edit_id=contact_id)
        flash("Đã cập nhật người liên hệ.", "success")
        return redirect(url_for("companies.detail", company_id=company_id))
    return render_template("add_contact.html", company=company, contact=contact, edit_id=contact_id)


@contacts_bp.route("/companies/<string:company_id>/contacts/<string:contact_id>/status", methods=["POST"])
@staff_required
def update_status(company_id, contact_id):
    """Update contact status with note"""
    note = (request.form.get("note") or "").strip()
    next_url = request.form.get("next", "")

    def _redirect_back():
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("companies.detail", company_id=company_id))

    if not note:
        flash("Đổi trạng thái liên hệ bắt buộc phải nhập ghi chú lý do.", "error")
        return _redirect_back()
    try:
        _call_authed(
            db_data.update_contact_status, company_id, contact_id,
            request.form.get("status", ""), note,
        )
        flash("Đã cập nhật trạng thái liên hệ.", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    return _redirect_back()


@contacts_bp.route("/companies/<string:company_id>/contacts/<string:contact_id>/delete", methods=["POST"])
@staff_required
def delete(company_id, contact_id):
    """Soft delete contact"""
    note = (request.form.get("note") or "").strip()
    if not note:
        flash("Xoá người liên hệ bắt buộc phải nhập ghi chú lý do.", "error")
        return redirect(url_for("companies.detail", company_id=company_id))
    try:
        _call_authed(db_data.delete_contact, company_id, contact_id, note)
        flash("Đã xoá người liên hệ.", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    return redirect(url_for("companies.detail", company_id=company_id))


@contacts_bp.route("/companies/<string:company_id>/contacts/<string:contact_id>/hard-delete", methods=["POST"])
@staff_required
def hard_delete(company_id, contact_id):
    """Hard delete contact (permanent)"""
    try:
        _call_authed(db_data.hard_delete_contact, company_id, contact_id)
        flash("Đã xoá hẳn người liên hệ (không thể khôi phục).", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    return redirect(url_for("companies.detail", company_id=company_id))


@contacts_bp.route("/companies/<string:company_id>/contacts/<string:contact_id>/assign", methods=["POST"])
@staff_required
def assign(company_id, contact_id):
    """Assign/unassign staff member to contact"""
    try:
        _call_authed(
            db_data.assign_contact, company_id, contact_id,
            request.form.get("assigned_ss_user", ""),
            request.form.get("note", ""),
        )
        flash("Đã cập nhật người phụ trách.", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    next_url = request.form.get("next", "")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("companies.detail", company_id=company_id))
