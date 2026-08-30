"""Companies blueprint - company listing and CRUD operations"""

import math

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

import crawler_client as db_data
from crawler_client import CrawlerAPIError
from utils.decorators import staff_required
from constants import COMPANIES_PER_PAGE, PARTNERSHIP_POTENTIALS, CITIES_VN, CONTACT_STATUSES
from helpers import _auth_tokens_from_session, _call_authed, _paginate_args, _io_pool as _pool
from potential_score import suggest_partnership_potential, suggest_partnership_potential_from_signals

companies_bp = Blueprint("companies", __name__)


@companies_bp.route("/companies")
@staff_required
def index():
    q = request.args.get("q", "").strip()
    city = request.args.get("city", "")
    page, per_page = _paginate_args(COMPANIES_PER_PAGE)

    # Song song hoá 3 lệnh gọi backend ĐỘC LẬP NHAU (thêm 08/2026, xem
    # lịch sử trao đổi "companies chậm 4s vì gọi tuần tự") — cities,
    # count, list KHÔNG phụ thuộc kết quả của nhau, trước đây gọi lần
    # lượt (tổng thời gian = tổng 3 round-trip), giờ bắn cùng lúc bằng
    # ThreadPoolExecutor (tổng thời gian ≈ round-trip CHẬM NHẤT trong 3
    # cái, không phải tổng cộng). An toàn tuyệt đối — cả 3 đều là GET
    # thuần, không có side-effect, không tranh chấp trạng thái với
    # nhau. requests (dùng trong crawler_client/base.py) tự nhả GIL lúc
    # I/O chờ mạng, nên threading vẫn tăng tốc thật dù có GIL.
    try:
        cities_future = _pool.submit(db_data.list_company_cities)
        count_future = _pool.submit(db_data.count_companies, q=q, city=city)
        list_future = _pool.submit(
            db_data.list_companies, q=q, city=city, limit=per_page, offset=(page - 1) * per_page,
        )
        cities = cities_future.result()
        total_companies = count_future.result()
        companies = list_future.result()
        total_pages = max(1, math.ceil(total_companies / per_page))
        if page > total_pages:
            page = total_pages
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies, cities, total_companies, total_pages, page = [], [], 0, 1, 1

    # Gợi ý tiềm năng hợp tác NGAY TRÊN DANH SÁCH (thêm 08/2026) — trước
    # đây suggestion chỉ tính ở trang /companies/<id>/edit vì cần
    # company.jobs + contacts (GET /companies list KHÔNG kèm jobs, xem
    # _normalize_company()).
    #
    # ĐÃ ĐỔI (08/2026, xem lịch sử trao đổi "fix gốc — thêm endpoint SQL
    # GROUP BY"): trước đây dùng list_all_jobs()/list_all_contacts() —
    # kéo TOÀN BỘ job/contact trong DB về Flask rồi tự group bằng
    # Python, tốn round-trip TỈ LỆ THUẬN với tổng số job/contact toàn
    # hệ thống (list_all_jobs() tự phân trang 200 job/lần — DB càng
    # nhiều job, trang /companies càng chậm, kể cả khi trang chỉ hiện
    # per_page=20 công ty). Giờ dùng get_partnership_signals(company_ids)
    # — CHỈ hỏi backend đúng company_id của per_page công ty đang hiển
    # thị, backend tự GROUP BY trong Postgres (có index company_id),
    # trả sẵn 3 boolean/company — chi phí trang này không còn phụ thuộc
    # tổng số job/contact trong DB nữa, chỉ phụ thuộc per_page (cố
    # định, không lớn dần theo thời gian như cách cũ). Không chặn trang
    # nếu lỗi — chỉ đơn giản là chip "Tiềm năng" không có tooltip hover.
    if companies:
        try:
            signals = db_data.get_partnership_signals([c["id"] for c in companies])
        except CrawlerAPIError:
            signals = {}

        for c in companies:
            suggestion = suggest_partnership_potential_from_signals(c, signals.get(c["id"], {}))
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
    đủ. Dùng db_data.update_company_potential() (payload tối giản, chỉ
    partnership_potential + note) thay vì db_data.update_company() (bắt
    buộc kèm company_name).

    note KHÔNG bắt buộc (khác update_status() bên contacts.py — note ở
    đó bắt buộc vì backend chặn cứng cho contact_status), nhưng vẫn có ô
    nhập trên UI và được gửi lên nếu staff có ghi, giống hệt hành vi note
    ở trang Sửa công ty đầy đủ (add_company.html)."""
    next_url = request.form.get("next", "")

    def _redirect_back():
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("companies.index"))

    try:
        _call_authed(
            db_data.update_company_potential, company_id,
            request.form.get("partnership_potential", ""),
            request.form.get("activity_note", ""),
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
