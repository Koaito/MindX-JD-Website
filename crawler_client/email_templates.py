"""Domain Email templates (mẫu email liên hệ doanh nghiệp) — CRUD thật,
persist ở backend (bảng email_templates), thay cho 6 mẫu HARDCODE cứng
trước đây trong public/app.js (biến EMAIL_TEMPLATES, xem lịch sử trao
đổi "chia phần danh sách contact thành 2 phần: danh sách + quản lý mẫu
email, giống bên export/import").

Route backend: /email-templates (xem api/routers/email_templates.py
repo Koaito/scrap-jd) — TOÀN BỘ route yêu cầu đã đăng nhập (require_role
ss_team/admin), khác enums/stats vốn không cần token, nên MỌI hàm ở đây
đều nhận access_token làm tham số đầu, theo đúng pattern contacts.py/
companies.py (KHÔNG giống enums.py get_enums() không cần token).

XOÁ HẲN (hard delete, không soft-delete) — khác company/contact.
CREATE không bắt buộc note, UPDATE/DELETE bắt buộc note nếu có field
thực sự đổi giá trị (xem docstring router backend) — app.py/blueprint
LUÔN gửi note; nếu rỗng, backend tự bỏ qua yêu cầu bắt buộc khi patch
không đổi gì thật sự.
"""

from .base import _request

CONTACT_STATUS_CHOICES = ("UNCONTACTED", "EMAIL_SENT", "RESPONDED", "IN_PARTNERSHIP")


def _normalize_template(raw: dict) -> dict | None:
    if raw is None:
        return None
    return {
        "id": raw.get("template_id"),
        "title": raw.get("title") or "",
        "description": raw.get("description") or "",
        "body": raw.get("body") or "",
        "recommended_for": raw.get("recommended_for") or [],
        "display_order": raw.get("display_order", 0),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "created_by": raw.get("created_by"),
        "updated_by": raw.get("updated_by"),
    }


def list_email_templates(access_token):
    """GET /email-templates — danh sách đầy đủ, đã sắp theo display_order
    (backend tự sort, xem db/email_templates.py::list_email_templates).
    Dùng cho CẢ popup chọn mẫu (nút "✉ Mẫu email") LẪN trang quản lý mẫu
    (tab "Quản lý mẫu email" trong /contacts) — 1 nguồn dữ liệu duy nhất,
    không còn tách riêng EMAIL_TEMPLATES hardcode ở app.js.
    """
    rows = _request("GET", "/email-templates", access_token) or []
    return [_normalize_template(r) for r in rows]


def get_email_template(access_token, template_id):
    """GET /email-templates/{id} — dùng khi mở form Sửa (nạp sẵn dữ liệu
    cũ). Trả None nếu không tồn tại (đã xoá/id sai) — caller tự abort(404)."""
    raw = _request("GET", f"/email-templates/{template_id}", access_token)
    return _normalize_template(raw)


def create_email_template(access_token, form):
    """POST /email-templates — tạo mẫu mới. `form` là request.form (hoặc
    dict tương đương) từ _email_template_form.html.

    recommended_for: form gửi lên dạng nhiều checkbox cùng tên
    "recommended_for" — dùng form.getlist("recommended_for") ở phía
    blueprint TRƯỚC khi gọi hàm này (giữ hàm này không phụ thuộc kiểu
    object cụ thể của Flask request.form, chỉ nhận dict/mapping thường)."""
    payload = {
        "title": (form.get("title") or "").strip(),
        "description": (form.get("description") or "").strip() or None,
        "body": form.get("body") or "",
        "recommended_for": form.get("recommended_for") or [],
        "display_order": int(form.get("display_order") or 0),
        "note": (form.get("note") or "").strip() or None,
    }
    raw = _request("POST", "/email-templates", access_token, json=payload)
    return _normalize_template(raw)


def update_email_template(access_token, template_id, form):
    """PATCH /email-templates/{id} — sửa mẫu. Gửi đủ 5 field ghi được
    (title/description/body/recommended_for/display_order) — KHÔNG chỉ
    gửi field đổi, vì form HTML luôn render đủ toàn bộ field (khác vài
    API PATCH khác trong backend có thể patch từng phần rời rạc qua
    AJAX) nên gửi nguyên trạng thái form hiện tại là đúng ý người dùng
    (giống pattern update_contact()/update_company() hiện có).

    note: BẮT BUỘC nhập trên UI (form luôn có ô note) — backend tự kiểm
    tra có field nào thực sự đổi giá trị không, patch rỗng/trùng thì
    không chặn dù note để trống."""
    payload = {
        "title": (form.get("title") or "").strip(),
        "description": (form.get("description") or "").strip() or None,
        "body": form.get("body") or "",
        "recommended_for": form.get("recommended_for") or [],
        "display_order": int(form.get("display_order") or 0),
        "note": (form.get("note") or "").strip() or None,
    }
    raw = _request("PATCH", f"/email-templates/{template_id}", access_token, json=payload)
    return _normalize_template(raw)


def delete_email_template(access_token, template_id, note):
    """DELETE /email-templates/{id} — XOÁ HẲN (không soft-delete, KHÁC
    delete_contact()/delete_company()). note BẮT BUỘC khác rỗng, backend
    trả 422 nếu thiếu — chặn sớm ở đây luôn để lỗi hiện tiếng Việt rõ
    ràng thay vì để backend tự raise (dù backend cũng đã validate)."""
    note = (note or "").strip()
    if not note:
        from .base import CrawlerAPIError
        raise CrawlerAPIError("Xoá mẫu email bắt buộc phải nhập ghi chú lý do.", status_code=422)
    _request("DELETE", f"/email-templates/{template_id}", access_token, json={"note": note})


def get_placeholder_help(access_token):
    """GET /email-templates/placeholder-help — bảng chú giải 5 placeholder
    cố định ({{LOI_CHAO}}, {{TEN_CONG_TY}}...), hiển thị trong form thêm/
    sửa mẫu để staff biết cách điền đúng. Trả dict rỗng nếu lỗi (không
    chặn form hiển thị chỉ vì thiếu phần chú giải phụ này)."""
    raw = _request("GET", "/email-templates/placeholder-help", access_token)
    return (raw or {}).get("placeholders", {})
