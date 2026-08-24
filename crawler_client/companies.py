"""Domain Company — list/get/create/update/delete công ty, chuẩn hoá field
backend -> field template đang dùng."""

from .base import _request
from .jobs import _normalize_job

# Đánh giá tiềm năng hợp tác của company — staff tự chấm tay qua UI add/edit
# company (xem sql/migration_add_partnership_potential.sql). UNVERIFIED =
# "chưa đánh giá" (mặc định), KHÔNG phải "tiềm năng thấp" — cố ý đặt tên
# tiếng Việt khác hẳn "Thấp" để staff không nhầm 2 khái niệm này.
PARTNERSHIP_POTENTIAL_MAP = {"HIGH": "Cao", "MEDIUM": "Trung bình",
                              "LOW": "Thấp", "UNVERIFIED": "Chưa đánh giá"}
PARTNERSHIP_POTENTIAL_MAP_REV = {v: k for k, v in PARTNERSHIP_POTENTIAL_MAP.items()}


def _normalize_company(raw: dict) -> dict | None:
    if raw is None:
        return None
    jobs = [_normalize_job(j) for j in raw.get("jobs", [])] if raw.get("jobs") is not None else None
    return {
        "id": raw.get("company_id"),
        "company": raw.get("company_name") or "",
        "tax_id": raw.get("tax_id") or "",
        "website": raw.get("website") or "",
        "industry": raw.get("industry") or "",
        "company_size": raw.get("company_size") or "",
        "address": raw.get("address") or "",
        "city": raw.get("province_name") or "",
        "fanpage": raw.get("fanpage_url") or "",
        "linkedin_company": raw.get("linkedin_url") or "",
        "partnership_potential": PARTNERSHIP_POTENTIAL_MAP.get(
            raw.get("partnership_potential") or "UNVERIFIED",
            raw.get("partnership_potential") or "UNVERIFIED",
        ),
        "date_collected": raw.get("created_at"),
        "jobs": jobs,
        # is_active (thêm 08/2026) — false = công ty đã bị xoá mềm qua
        # DELETE /companies/{id} (xem delete_company() bên dưới). GET
        # /companies mặc định KHÔNG trả company này (backend tự lọc,
        # xem list_companies() phía dưới không truyền include_inactive).
        "is_active": raw.get("is_active", True),
        # created_by/updated_by — cùng ý nghĩa với jobs._normalize_job(),
        # xem comment ở đó. NULL với company crawl tự động.
        "created_by": raw.get("created_by"),
        "updated_by": raw.get("updated_by"),
    }


def list_companies(q="", city="", created_by="", limit=200, offset=0):
    params = {"limit": limit, "offset": offset}
    if q:
        params["keyword"] = q
    if city:
        params["province"] = city
    if created_by:
        # Lọc công ty do 1 thành viên ss_team/admin cụ thể TỰ THÊM TAY
        # (thêm 08/2026, trang /staff-activity) — company crawl tự động
        # có created_by NULL nên không bao giờ khớp filter này.
        params["created_by"] = created_by
    data = _request("GET", "/companies", params=params) or {}
    items = data.get("items", data if isinstance(data, list) else [])
    return [_normalize_company(c) for c in items]


# Backend GET /companies giới hạn limit tối đa 200/lần gọi (api/routers/
# companies.py: Query(50, ge=1, le=200)) — gọi list_companies(limit=500)
# thẳng sẽ bị 422 "Input should be less than or equal to 200". Dùng hàm
# này ở bất kỳ đâu cần TOÀN BỘ danh sách công ty một lần (vd đổ vào
# dropdown chọn công ty) thay vì bịa 1 con số limit lớn hơn 200.
_MAX_COMPANIES_PAGE = 200
_ALL_COMPANIES_SAFETY_CAP = 5000  # chặn vòng lặp vô hạn nếu backend trả total sai


def list_all_companies(created_by=""):
    """Lấy TOÀN BỘ công ty bằng cách tự phân trang theo đúng limit tối đa
    backend cho phép (200/lần), gộp lại thành 1 list.

    created_by mặc định rỗng (không lọc) — hành vi gốc không đổi cho
    mọi lời gọi cũ (list_all_companies() không tham số vẫn trả về TOÀN
    BỘ công ty, dùng cho dropdown chọn công ty — cần thấy hết). Truyền
    created_by=uid khi cần biến thể có lọc, vd "mọi công ty 1 staff đã
    tự thêm tay" cho trang /staff-activity — cùng 1 hàm, không tách
    riêng hàm mới để tránh trùng lặp logic phân trang."""
    total = count_companies(created_by=created_by)
    all_items: list = []
    offset = 0
    while offset < total and offset < _ALL_COMPANIES_SAFETY_CAP:
        page = list_companies(created_by=created_by, limit=_MAX_COMPANIES_PAGE, offset=offset)
        if not page:
            break
        all_items.extend(page)
        offset += _MAX_COMPANIES_PAGE
    return all_items


def count_companies(q="", city="", created_by=""):
    """Dùng field `total` backend trả sẵn — xem giải thích ở jobs.count_jobs().
    Nhận đúng bộ filter như list_companies() để khớp danh sách đang lọc."""
    params = {"limit": 1}
    if q:
        params["keyword"] = q
    if city:
        params["province"] = city
    if created_by:
        params["created_by"] = created_by
    data = _request("GET", "/companies", params=params) or {}
    return data.get("total", 0)


def list_company_cities():
    """Cần liệt kê MỌI company để gom danh sách thành phố — backend giới
    hạn tối đa 200 record/lần (limit<=200), nên lặp trang (offset) thay
    vì gửi 1 lần limit=1000 (sẽ bị backend từ chối 422)."""
    cities = set()
    offset = 0
    while True:
        batch = list_companies(limit=200, offset=offset)
        if not batch:
            break
        cities.update(c["city"] for c in batch if c["city"])
        if len(batch) < 200:
            break
        offset += 200
    return sorted(cities)


def get_company(company_id):
    """Trả kèm jobs (CompanyDetailOut) — dùng cho trang chi tiết công ty."""
    raw = _request("GET", f"/companies/{company_id}")
    return _normalize_company(raw)


def _company_payload(form):
    return {
        "company_name": form["company"].strip(),
        "tax_id": (form.get("tax_id") or "").strip() or None,
        "website": (form.get("website") or "").strip() or None,
        "industry": (form.get("industry") or "").strip() or None,
        "company_size": (form.get("company_size") or "").strip() or None,
        "address": (form.get("address") or "").strip() or None,
        "province_name": (form.get("city") or "").strip() or None,
        "fanpage_url": (form.get("fanpage") or "").strip() or None,
        "linkedin_url": (form.get("linkedin_company") or "").strip() or None,
        "partnership_potential": PARTNERSHIP_POTENTIAL_MAP_REV.get(
            form.get("partnership_potential", ""), form.get("partnership_potential") or None,
        ),
    }


def create_company(access_token, form) -> dict:
    """Idempotent theo tax_id (backend tự xử lý) — gọi lại với tax_id đã
    có sẵn sẽ trả về company cũ đã được vá thêm thông tin, không tạo trùng."""
    raw = _request("POST", "/companies", access_token=access_token, json=_company_payload(form))
    return _normalize_company(raw)


def update_company(access_token, company_id, form) -> dict:
    # note audit log — TUỲ CHỌN (xem docstring base.py, mục "AUDIT LOG
    # NOTE") — CHỈ thêm ở update, KHÔNG thêm ở create_company() phía
    # trên (CREATE_COMPANY không nhận note, tạo company không phải hành
    # vi cần giải thích lý do).
    payload = {**_company_payload(form), "note": (form.get("activity_note") or "").strip() or None}
    raw = _request("PATCH", f"/companies/{company_id}", access_token=access_token, json=payload)
    return _normalize_company(raw)


def delete_company(access_token, company_id, note):
    """DELETE /companies/{company_id} (thêm 08/2026) — xoá MỀM
    (is_active=false), KHÔNG xoá thật (JD/HR contact cũ vẫn giữ nguyên,
    chỉ ẩn company khỏi GET /companies mặc định).

    note BẮT BUỘC — backend trả 422 ngay nếu thiếu/rỗng (xem
    CompanyDeleteRequest ở api/schemas.py backend), KHÔNG xoá gì cả."""
    _request("DELETE", f"/companies/{company_id}", access_token=access_token, json={"note": note})
