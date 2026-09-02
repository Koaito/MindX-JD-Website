"""Jobs blueprint - job listing, detail, and CRUD operations"""

import math
from types import SimpleNamespace

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

import backend_auth
import crawler_client as db_data
from backend_auth import BackendAuthError
from constants import (
    CITIES_VN,
    INDUSTRIES,
    JOB_STATUSES,
    JOBS_PER_PAGE,
    LOCATIONS,
    SALARY_PERIODS,
    SALARY_TYPES,
    WORK_TYPES,
)
from crawler_client import CrawlerAPIError
from helpers import _auth_tokens_from_session, _call_authed, _paginate_args
from utils.decorators import _wants_json, staff_required

# Import trực tiếp (không phải import trễ) — add_hub.py KHÔNG import
# ngược lại từ jobs.py nên không có vòng lặp import, khác trường hợp
# crawl.py/crawl_maintenance.py (xem comment ở đó). Dùng để nhánh lỗi
# jobs.add() render lại ĐÚNG shell "Thêm mới" (08/2026, xem lịch sử
# trao đổi "phương án A+") thay vì trang add_job.html đứng riêng.
from blueprints.add_hub import _add_hub_context

jobs_bp = Blueprint("jobs", __name__)


def _resolve_company_id(form):
    """Resolve company_id from form (existing or create new)"""
    mode = form.get("company_mode", "existing")
    if mode == "new":
        company_name = (form.get("new_company_name") or "").strip()
        if not company_name:
            raise CrawlerAPIError("Vui lòng nhập tên công ty mới.")
        company_form = {
            "company": company_name,
            "tax_id": form.get("new_company_tax_id", ""),
            "website": form.get("new_company_website", ""),
            "industry": form.get("new_company_industry", ""),
            "city": form.get("new_company_city", ""),
        }
        company = _call_authed(db_data.create_company, company_form)
        return company["id"]
    company_id = (form.get("company_id") or "").strip()
    if not company_id:
        raise CrawlerAPIError("Vui lòng chọn công ty.")
    return company_id


@jobs_bp.route("/")
@jobs_bp.route("/jobs")
def index():
    q = request.args.get("q", "").strip()
    industry = request.args.get("industry", "")
    level = request.args.get("level", "")
    location = request.args.get("location", "")
    status = request.args.get("status", "")
    page, per_page = _paginate_args(JOBS_PER_PAGE)

    if status == "ALL":
        status_filter = ""
    elif status:
        status_filter = status
    else:
        status_filter = "Đang tuyển"

    try:
        total_jobs = db_data.count_jobs(q=q, industry=industry, level=level, location=location, status=status_filter)
        total_pages = max(1, math.ceil(total_jobs / per_page))
        page = min(page, total_pages)
        jobs = db_data.list_jobs(
            q=q, industry=industry, level=level, location=location, status=status_filter,
            limit=per_page, offset=(page - 1) * per_page,
        )
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        jobs, total_jobs, total_pages, page = [], 0, 1, 1

    return render_template(
        "index.html", jobs=jobs, industries=INDUSTRIES, levels=db_data.get_level_codes(),
        locations=LOCATIONS, statuses=JOB_STATUSES,
        filters={"q": q, "industry": industry, "level": level, "location": location, "status": status},
        pagination_filters={k: v for k, v in
                             {"q": q, "industry": industry, "level": level,
                              "location": location, "status": status}.items() if v},
        total_jobs=total_jobs, page=page, total_pages=total_pages, per_page=per_page,
    )


@jobs_bp.route("/jobs/<string:job_id>")
def detail(job_id):
    try:
        job = db_data.get_job(job_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("jobs.index"))
    if not job:
        abort(404)
    job = dict(job)
    try:
        job["is_duplicate_candidate"] = db_data.is_duplicate_candidate(job)
    except CrawlerAPIError:
        job["is_duplicate_candidate"] = False

    applicants = None
    savers = None
    already_applied = False
    if current_user.is_authenticated:
        access_token, _ = _auth_tokens_from_session()
        if current_user.is_staff:
            try:
                raw_applicants = backend_auth.list_job_applicants(access_token, job["id"])
            except BackendAuthError as exc:
                flash(str(exc), "error")
                raw_applicants = []
            applicants = [
                SimpleNamespace(
                    application_id=a["application_id"],
                    job_id=a["job_id"],
                    note=a.get("note"),
                    applied_at=a["applied_at"],
                    student=SimpleNamespace(full_name=a["full_name"], email=a["email"], phone=None),
                )
                for a in raw_applicants
            ]
            try:
                raw_savers = backend_auth.list_job_savers(access_token, job["id"])
            except BackendAuthError as exc:
                flash(str(exc), "error")
                raw_savers = []
            savers = [
                SimpleNamespace(
                    saved_job_id=s["saved_job_id"],
                    job_id=s["job_id"],
                    created_at=s["created_at"],
                    student=SimpleNamespace(full_name=s["full_name"], email=s["email"], phone=s.get("phone")),
                )
                for s in raw_savers
            ]
        else:
            try:
                my_apps = backend_auth.list_my_applications(access_token)
                already_applied = any(a["job_id"] == job["id"] for a in my_apps)
            except BackendAuthError:
                already_applied = False
    return render_template("job_detail.html", job=job, applicants=applicants, savers=savers,
                            already_applied=already_applied, statuses=JOB_STATUSES)


@jobs_bp.route("/jobs/add", methods=["GET", "POST"])
@staff_required
def add():
    """Thêm job mới. ĐÃ ĐỔI (08/2026, xem lịch sử trao đổi "phương án
    A+"): GET giờ redirect sang /them-moi?tab=job (trang gộp 3 tab,
    link sidebar mới trỏ thẳng vào đó) — route này CHỈ còn xử lý POST.
    Nhánh lỗi render lại add_hub.html (giữ tab-bar + dữ liệu đã nhập)
    qua _add_hub_context() thay vì add_job.html đứng riêng như trước.
    Nhánh thành công KHÔNG đổi — vẫn redirect(jobs.index) như cũ."""
    if request.method == "GET":
        return redirect(url_for("add_hub.index", tab="job"))
    try:
        company_id = _resolve_company_id(request.form)
        job = _call_authed(db_data.create_job, request.form, company_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return render_template("add_hub.html", **_add_hub_context(active_tab="job", job_form=request.form))
    flash(f"Đã thêm job \"{job['position']}\" tại {job['company']}.", "success")
    return redirect(url_for("jobs.index"))


@jobs_bp.route("/jobs/<string:job_id>/edit", methods=["GET", "POST"])
@staff_required
def edit(job_id):
    job = db_data.get_job(job_id)
    if not job:
        abort(404)
    if request.method == "POST":
        try:
            updated = _call_authed(db_data.update_job, job_id, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_job.html", industries=INDUSTRIES, levels=db_data.get_level_codes(),
                                    locations=LOCATIONS, statuses=JOB_STATUSES,
                                    work_types=WORK_TYPES, salary_types=SALARY_TYPES, salary_periods=SALARY_PERIODS,
                                    job=job, edit_id=job_id)
        flash(f"Đã cập nhật job \"{updated['position']}\".", "success")
        return redirect(url_for("jobs.detail", job_id=job_id))
    return render_template("add_job.html", industries=INDUSTRIES, levels=db_data.get_level_codes(),
                            locations=LOCATIONS, statuses=JOB_STATUSES,
                            work_types=WORK_TYPES, salary_types=SALARY_TYPES, salary_periods=SALARY_PERIODS,
                            job=job, edit_id=job_id)


@jobs_bp.route("/jobs/<string:job_id>/status", methods=["POST"])
@staff_required
def update_status(job_id):
    """Đổi trạng thái 1 job (dropdown ở trang chi tiết job — form thường,
    reload cả trang) HOẶC gọi qua AJAX (fetch, header X-Requested-With)
    từ nơi khác không muốn rời trang hiện tại.

    THÊM 09/2026 (xem lịch sử trao đổi "job nghi trùng lặp — thêm nút
    thao tác được"): bảng "Job nghi trùng lặp" ở tab "Tình trạng dữ
    liệu" (_status_tab.html) giờ có nút "Đóng job này" ngay tại chỗ,
    gọi ĐÚNG route này qua fetch() thay vì <form> thường — bấm xong
    muốn XOÁ RIÊNG dòng đó khỏi bảng (JS tự làm), KHÔNG redirect sang
    trang chi tiết job như hành vi gốc (sẽ rời mất tab đang xem, mất
    ngữ cảnh các nhóm trùng khác). is_ajax nhánh này trả JSON gọn
    {"ok": true, "status": ...}/{"error": "..."}, KHÔNG đổi hành vi
    nhánh form thường (vẫn flash + redirect y hệt trước giờ)."""
    job = db_data.get_job(job_id)
    if not job:
        if _wants_json():
            return jsonify({"error": "Không tìm thấy job."}), 404
        abort(404)
    new_status = request.form.get("status", job["status"])
    try:
        _call_authed(
            db_data.update_job_status, job_id, new_status,
            request.form.get("activity_note", ""),
        )
    except CrawlerAPIError as exc:
        if _wants_json():
            return jsonify({"error": str(exc)}), 400
        flash(str(exc), "error")
        return redirect(url_for("jobs.detail", job_id=job_id))

    if _wants_json():
        return jsonify({"ok": True, "job_id": job_id, "status": new_status})
    flash("Đã cập nhật trạng thái job.", "success")
    return redirect(url_for("jobs.detail", job_id=job_id))


@jobs_bp.route("/jobs/<string:job_id>/delete", methods=["POST"])
@staff_required
def delete(job_id):
    """Soft delete - close job"""
    job = db_data.get_job(job_id)
    if not job:
        abort(404)
    try:
        _call_authed(db_data.update_job_status, job_id, "CLOSED", request.form.get("activity_note", ""))
        flash("Đã đóng job (không xoá dữ liệu — job đóng vẫn xem được, chỉ ẩn khỏi tìm kiếm mặc định).", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("jobs.detail", job_id=job_id))
    return redirect(url_for("jobs.index"))
