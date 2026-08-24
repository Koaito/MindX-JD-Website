"""Domain Company contacts (người liên hệ HR) — bảng CON của company,
route riêng /companies/{company_id}/contacts."""

from .base import _request

CONTACT_STATUS_MAP = {"UNCONTACTED": "Chưa liên hệ", "EMAIL_SENT": "Đã gửi email",
                       "RESPONDED": "Đã phản hồi", "IN_PARTNERSHIP": "Đang hợp tác"}
CONTACT_STATUS_MAP_REV = {v: k for k, v in CONTACT_STATUS_MAP.items()}


def _normalize_contact(raw: dict) -> dict | None:
    if raw is None:
        return None
    result = {
        "id": raw.get("contact_id"),
        "company_id": raw.get("company_id"),
        "contact_name": raw.get("contact_name") or "",
        "title": raw.get("job_title") or "",
        "email": raw.get("work_email") or "",
        "contact_link": raw.get("social_link") or "",
        "phone": raw.get("phone_number") or "",
        "source": raw.get("found_source") or "",
        "date_collected": raw.get("collected_date"),
        "last_contacted": raw.get("last_contacted_date"),
        "status": CONTACT_STATUS_MAP.get(raw.get("contact_status") or "", raw.get("contact_status") or ""),
        "status_raw": raw.get("contact_status") or "UNCONTACTED",
        "is_active": raw.get("is_active", True),
        # created_by — ai tự thêm contact này (xem jobs._normalize_job()
        # cho ý nghĩa chung). assigned_ss_user — ai đang PHỤ TRÁCH contact
        # này (khác created_by, có thể là người khác — xem
        # assign_contact() bên dưới), NULL nếu chưa gán ai.
        "created_by": raw.get("created_by"),
        "updated_by": raw.get("updated_by"),
        "assigned_ss_user": raw.get("assigned_ss_user"),
    }
    # company_name chỉ có mặt khi raw đến từ GET /contacts (danh sách gộp
    # mọi công ty, xem list_all_contacts() bên dưới) — GET
    # /companies/{company_id}/contacts (list_contacts()) không trả field
    # này vì company_id đã biết sẵn từ path.
    if "company_name" in raw:
        result["company_name"] = raw.get("company_name") or ""
    return result


def list_all_contacts(access_token, *, status_raw="", company_id="", search="",
                       created_by="", assigned_ss_user=""):
    """GET /contacts — danh sách contact GỘP TẤT CẢ công ty (khác
    list_contacts() bên dưới chỉ trả theo 1 company_id), kèm company_name.
    Dùng cho trang "Danh sách contact" tổng hợp (route /contacts,
    contacts_index() trong app.py) và trang /staff-activity/<id>.

    Mặc định CHỈ trả contact đang active (include_inactive=False) — khác
    list_contacts() (luôn include_inactive=True) vì trang tổng hợp này là
    view "đang cần làm việc", không phải nơi coi lịch sử đã xoá mềm; muốn
    xem lại contact đã xoá vẫn vào đúng company_detail.html như cũ.

    status_raw: mã tiếng Anh (vd 'UNCONTACTED'), KHÔNG phải nhãn tiếng
    Việt hiển thị trên UI — app.py tự tra CONTACT_STATUS_MAP_REV trước
    khi gọi hàm này, giống pattern update_contact_status().

    created_by / assigned_ss_user (thêm 08/2026, trang /staff-activity):
    2 filter ĐỘC LẬP nhau — created_by = ai TẠO contact, assigned_ss_user
    = ai đang PHỤ TRÁCH contact (có thể là người khác created_by). Không
    có response `total` (route backend không phân trang, xem
    api/routers/contacts.py::list_all_contacts) — dùng len() nếu cần đếm,
    chấp nhận được vì kết quả đã lọc theo 1 người nên luôn nhỏ.
    """
    params = {}
    if status_raw:
        params["contact_status"] = status_raw
    if company_id:
        params["company_id"] = company_id
    if search:
        params["search"] = search
    if created_by:
        params["created_by"] = created_by
    if assigned_ss_user:
        params["assigned_ss_user"] = assigned_ss_user
    raw = _request("GET", "/contacts", access_token=access_token, params=params) or []
    return [_normalize_contact(c) for c in raw]


def list_contacts(access_token, company_id):
    """include_inactive=True (mới 08/2026) — lấy CẢ contact đã soft-delete
    (is_active=false), không chỉ contact đang active. Trước đây gọi mặc
    định include_inactive=False -> contact đã xoá mềm biến mất hoàn
    toàn khỏi UI dù DB vẫn giữ, staff không có cách nào xem lại / xoá
    cứng chúng. Template (company_detail.html) tự tách 2 nhóm dựa vào
    field is_active trong dict trả về."""
    raw = _request(
        "GET", f"/companies/{company_id}/contacts",
        access_token=access_token, params={"include_inactive": "true"},
    ) or []
    return [_normalize_contact(c) for c in raw]


def get_contact(access_token, company_id, contact_id):
    contacts = list_contacts(access_token, company_id)
    for c in contacts:
        if c["id"] == contact_id:
            return c
    return None


def create_contact(access_token, company_id, form) -> dict:
    payload = {
        "contact_name": form["contact_name"].strip(),
        "job_title": (form.get("title") or "").strip() or None,
        "work_email": (form.get("email") or "").strip() or None,
        "social_link": (form.get("contact_link") or "").strip() or None,
        "phone_number": (form.get("phone") or "").strip() or None,
        "found_source": (form.get("source") or "").strip() or None,
        # assigned_ss_user (thêm 08/2026) — gán người phụ trách NGAY lúc
        # tạo, optional (form không có ô này thì bỏ trống -> NULL, gán
        # sau qua assign_contact()/route /assign như thường lệ).
        "assigned_ss_user": (form.get("assigned_ss_user") or "").strip() or None,
        # note audit log — TUỲ CHỌN (xem docstring base.py, mục "AUDIT
        # LOG NOTE") — tạo contact không bắt buộc giải thích lý do.
        "note": (form.get("activity_note") or "").strip() or None,
    }
    raw = _request("POST", f"/companies/{company_id}/contacts", access_token=access_token, json=payload)
    return _normalize_contact(raw)


def update_contact(access_token, company_id, contact_id, form, note) -> dict:
    """note BẮT BUỘC (thêm 08/2026) NẾU thực sự có field nào đổi giá
    trị — backend tự tính diff và trả 422 nếu thiếu, xem docstring
    CompanyContactUpdate.note ở api/schemas.py backend. Truyền None/""
    vẫn hợp lệ cho lượt gọi KHÔNG đổi field nào (backend bỏ qua yêu cầu
    note khi không có thay đổi thật)."""
    payload = {
        "contact_name": (form.get("contact_name") or "").strip() or None,
        "job_title": (form.get("title") or "").strip() or None,
        "work_email": (form.get("email") or "").strip() or None,
        "social_link": (form.get("contact_link") or "").strip() or None,
        "phone_number": (form.get("phone") or "").strip() or None,
        # BUG FIX (08/2026): field "source" (Nguồn tìm thấy) bị thiếu ở
        # đây từ đầu — create_contact() có gửi field này (map sang
        # found_source) nhưng update_contact() thì không, nên sửa ô
        # "Nguồn tìm thấy" ở form Sửa người liên hệ luôn báo lưu thành
        # công (PATCH vẫn chạy OK với 5 field còn lại) nhưng riêng field
        # này không bao giờ tới được backend -> không lưu, không log.
        # (Backend cũng thiếu found_source ở CompanyContactUpdate/
        # update_company_contact() — đã sửa riêng ở repo scrap-jd-api.)
        "found_source": (form.get("source") or "").strip() or None,
        "note": (note or "").strip() or None,
    }
    raw = _request("PATCH", f"/companies/{company_id}/contacts/{contact_id}", access_token=access_token, json=payload)
    return _normalize_contact(raw)


def update_contact_status(access_token, company_id, contact_id, status_vn, note):
    """note BẮT BUỘC (sửa 08/2026 — fix bug mất note khi đổi trạng thái
    contact) NẾU status thực sự đổi giá trị — backend tự tính diff và
    trả 422 nếu thiếu, giống pattern update_contact()/assign_contact().
    Trước đây hàm này KHÔNG có tham số note trong chữ ký hàm nên dù UI
    có ô nhập note thì cũng không có chỗ để truyền xuống backend, khiến
    MỌI request đổi trạng thái contact luôn bị backend từ chối 422."""
    code = CONTACT_STATUS_MAP_REV.get(status_vn, status_vn)
    raw = _request(
        "PATCH", f"/companies/{company_id}/contacts/{contact_id}",
        access_token=access_token,
        json={"contact_status": code, "note": (note or "").strip() or None},
    )
    return _normalize_contact(raw)


def assign_contact(access_token, company_id, contact_id, assigned_ss_user, note=None):
    """PATCH /companies/{company_id}/contacts/{contact_id}/assign (thêm
    08/2026) — gán (hoặc BỎ gán khi assigned_ss_user rỗng/None) người
    phụ trách 1 contact. Route RIÊNG khỏi update_contact_status() ở trên
    vì backend cần phân biệt "field không gửi lên" (giữ nguyên) với
    "gửi lên NULL tường minh" (bỏ gán) — xem ContactAssignUpdate trong
    api/schemas.py và docstring assign_contact() ở db.py backend.

    assigned_ss_user: ss_user_id (UUID) của thành viên ss_team/admin, hoặc
    "" / None để bỏ gán — cả 2 đều gửi JSON null lên backend.

    note (thêm 08/2026): BẮT BUỘC NẾU lượt gán này thực sự ĐỔI người
    phụ trách so với hiện tại (gán mới/đổi người/bỏ gán) — backend tự
    so sánh, trả 422 nếu thiếu. Nếu chọn lại đúng người đang phụ trách
    (không đổi gì) thì note không bắt buộc."""
    raw = _request(
        "PATCH", f"/companies/{company_id}/contacts/{contact_id}/assign",
        access_token=access_token,
        json={"assigned_ss_user": assigned_ss_user or None, "note": (note or "").strip() or None},
    )
    return _normalize_contact(raw)


def delete_contact(access_token, company_id, contact_id, note):
    """Xoá MỀM phía backend (is_active=false) — không phải xoá thật.

    note BẮT BUỘC (thêm 08/2026) — backend trả 422 ngay nếu thiếu/rỗng
    (xem ContactDeleteRequest ở api/schemas.py backend), KHÔNG xoá gì."""
    _request("DELETE", f"/companies/{company_id}/contacts/{contact_id}", access_token=access_token, json={"note": note})


def hard_delete_contact(access_token, company_id, contact_id):
    """Xoá THẬT (mới 08/2026) — chỉ dùng làm bước 2, backend chặn 409
    nếu contact CHƯA soft-delete trước (xem thiết kế 2 bước ở lịch sử
    trao đổi), hoặc 409 nếu contact đang có job_contact_links (đã từng
    gắn với job cụ thể — xoá sẽ mất lịch sử liên hệ theo job đó).
    CrawlerAPIError từ 2 case 409 này có message đủ rõ để flash thẳng
    cho staff, không cần app.py tự diễn giải thêm."""
    _request("DELETE", f"/companies/{company_id}/contacts/{contact_id}/hard", access_token=access_token)
