"""Domain Company — list/get/create/update/delete công ty, chuẩn hoá field
backend -> field template đang dùng."""

from .base import _request
from .jobs import _normalize_job
from .data_health import count_missing_fields

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


def get_partnership_signals(company_ids):
    """GET /companies/partnership-signals — thay thế list_all_jobs() +
    list_all_contacts() (kéo TOÀN BỘ job/contact về Flask rồi tự group
    bằng Python) từng dùng ở blueprints/companies.py::index() để tính
    gợi ý "Tiềm năng hợp tác" (potential_score.suggest_partnership_potential())
    ngay trên bảng danh sách công ty (thêm 08/2026, xem lịch sử trao đổi
    "companies chậm 4s vì round-trip tuần tự tỉ lệ thuận với số job").

    Backend tự tính sẵn bằng SQL GROUP BY (xem
    db.get_partnership_signals() bên scrap-jd-api) — KHÔNG còn round-
    trip nào tỉ lệ thuận với tổng số job/contact trong hệ thống, chỉ 1
    lệnh gọi duy nhất bất kể DB có bao nhiêu job.

    company_ids: list company_id CẦN tín hiệu (thường là đúng
    per_page công ty đang hiển thị trên 1 trang, KHÔNG phải toàn bộ DB)
    — bắt buộc truyền, rỗng thì backend trả {} luôn (xem
    db.get_partnership_signals(), không gọi API nếu danh sách rỗng, đỡ
    1 lệnh gọi thừa khi trang không có company nào — vd kết quả tìm
    kiếm rỗng).

    Trả dict {company_id: {"has_open_entry_job": bool,
    "matches_target_industry": bool, "has_responded": bool}} — company
    không có trong dict coi như cả 3 đều False (không có job/contact
    nào khớp tiêu chí), nơi gọi tự .get(id, {}) khi build gợi ý."""
    if not company_ids:
        return {}
    # requests hỗ trợ list trong params -> tự lặp lại thành
    # ?company_id=a&company_id=b (đúng cú pháp FastAPI Query(list[str])
    # mong đợi ở router, xem api/routers/companies.py), không cần tự
    # nối chuỗi tay.
    data = _request("GET", "/companies/partnership-signals", params={"company_id": company_ids}) or {}
    return data


def get_company_data_health(access_token):
    """GET /companies/data-health — thay thế cho việc crawl_status.py
    từng phải gọi list_all_companies() + list_all_contacts() rồi tự đếm
    field rỗng bằng Python (company_field_health()/
    count_companies_without_contact() ở companies.py này). Backend tự
    tính bằng SQL (xem db.get_company_data_health() bên scrap-jd-api).

    CẦN access_token (khác get_partnership_signals() ở trên, chỉ cần
    API_KEY) — backend route này require_role("ss_team") vì phải JOIN
    qua company_contacts (thông tin liên hệ nhạy cảm), cùng lý do mọi
    hàm ở contacts.py đều cần access_token.

    Trả thẳng dict backend trả về, ĐÃ ĐÚNG shape crawl_status.py cần:
    company_health_rows/company_health_total/company_no_contact_missing/
    company_no_contact_total."""
    return _request("GET", "/companies/data-health", access_token=access_token) or {
        "company_health_rows": [], "company_health_total": 0,
        "company_no_contact_missing": 0, "company_no_contact_total": 0,
    }


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


# Field nào tính vào thống kê "thiếu dữ liệu" ở tab Tình trạng dữ liệu
# (blueprints/crawl_status.py) — company_name/id KHÔNG đưa vào vì luôn
# có sẵn (backend bắt buộc lúc tạo company), không có ý nghĩa thống kê.
# Thứ tự ở đây = thứ tự hiển thị trên UI (xem lịch sử trao đổi 08/2026).
COMPANY_HEALTH_FIELDS = [
    ("tax_id", "Mã số thuế"),
    ("website", "Website"),
    ("industry", "Ngành"),
    ("address", "Địa chỉ"),
    ("company_size", "Quy mô"),
    ("fanpage", "Fanpage"),
    ("linkedin_company", "LinkedIn"),
]


def company_field_health(companies):
    """Đếm số company thiếu (rỗng) từng field trong COMPANY_HEALTH_FIELDS.

    Nhận sẵn list company đã _normalize_company() (KHÔNG tự gọi
    list_all_companies() ở đây) — để nơi gọi (crawl_status.py) tự quyết
    định lấy company từ đâu/khi nào, giống cách dashboard.py truyền
    `companies`/`jobs` vào các hàm _companies_*/_jd_* thay vì mỗi hàm tự
    fetch riêng — tránh gọi API lặp lại nhiều lần cho cùng 1 lần render
    trang.

    Logic đếm thật sự nằm ở count_missing_fields() (data_health.py) —
    dùng CHUNG với job_field_health() (jobs.py), xem docstring ở đó.
    """
    return count_missing_fields(companies, COMPANY_HEALTH_FIELDS)


def count_companies_without_contact(companies, contacts):
    """Đếm company ĐANG ACTIVE chưa có bất kỳ contact (người liên hệ HR)
    nào trong bảng contacts — quan trọng vì company không có contact thì
    team SS không có cách nào chủ động liên hệ hợp tác tuyển dụng, dù
    company đó có bao nhiêu job đăng lên cũng vậy (thêm 08/2026, tab
    Tình trạng dữ liệu, xem lịch sử trao đổi).

    Nhận sẵn list company đã _normalize_company() VÀ list contact đã
    _normalize_contact() (list_all_contacts(), có company_id trên mỗi
    contact) — cùng nguyên tắc company_field_health(): nơi gọi
    (crawl_status.py) tự fetch, hàm này chỉ tính on-the-fly, không gọi
    API. Chỉ tính contact ĐANG ACTIVE (is_active — contact đã xoá mềm
    không tính là "đã có người liên hệ").

    Trả (missing: int, total: int) — total = số company active (bỏ
    company đã xoá mềm, is_active=False, giống cách company_health_rows
    đang tính), missing = số company trong đó có company_id không xuất
    hiện ở bất kỳ contact active nào."""
    active_companies = [c for c in companies if c.get("is_active", True)]
    company_ids_with_contact = {
        c.get("company_id") for c in contacts if c.get("is_active", True)
    }
    missing = sum(
        1 for c in active_companies if c.get("id") not in company_ids_with_contact
    )
    return missing, len(active_companies)


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


def update_company_potential(access_token, company_id, potential, note=None) -> dict:
    """PATCH /companies/{id} CHỈ với field partnership_potential (+ note
    audit log tuỳ chọn) — dùng cho thao tác sửa nhanh "Tiềm năng" ngay
    trên bảng danh sách công ty (thêm 08/2026, xem lịch sử trao đổi),
    KHÔNG dùng update_company()/_company_payload() ở trên vì hàm đó bắt
    buộc form["company"] (tên công ty) nên sẽ KeyError nếu chỉ có mỗi
    tiềm năng.

    Backend PATCH /companies/{id} vốn đã hỗ trợ partial update thật sự
    (field không có mặt trong body thì giữ nguyên, xem patch_company_profile()
    ở backend) — nên gửi payload tối giản 1-2 field này là đủ, không cần
    kèm các field khác của company.

    note KHÔNG bắt buộc (khác update_contact_status() — đổi trạng thái
    contact bị backend chặn cứng nếu thiếu note, còn partnership_potential
    thì không) — vẫn nhận note để lưu lý do vào Lịch sử thao tác (audit
    log) nếu staff có ghi, giống hệt cách update_company() ở trên làm."""
    payload = {
        "partnership_potential": PARTNERSHIP_POTENTIAL_MAP_REV.get(potential, potential),
        "note": (note or "").strip() or None,
    }
    raw = _request("PATCH", f"/companies/{company_id}", access_token=access_token, json=payload)
    return _normalize_company(raw)


def delete_company(access_token, company_id, note):
    """DELETE /companies/{company_id} (thêm 08/2026) — xoá MỀM
    (is_active=false), KHÔNG xoá thật (JD/HR contact cũ vẫn giữ nguyên,
    chỉ ẩn company khỏi GET /companies mặc định).

    note BẮT BUỘC — backend trả 422 ngay nếu thiếu/rỗng (xem
    CompanyDeleteRequest ở api/schemas.py backend), KHÔNG xoá gì cả."""
    _request("DELETE", f"/companies/{company_id}", access_token=access_token, json={"note": note})
