"""
Client gọi API backend "Scrap JD" (repo Koaito/scrap-jd, deploy trên Render)
để đọc/ghi Job, Company, Company Contact — THAY THẾ hoàn toàn cho data.py cũ
(vốn gọi Supabase). Viết lại 08/2026 cho khớp ĐÚNG contract backend thật
(trước đó là bản đoán, gọi PUT/DELETE không tồn tại — xem lịch sử trao đổi).

⚠️ KHÁC bản cũ ở NHỮNG ĐIỂM SAU (bắt buộc phải biết khi đọc code này):
  - Mọi request GHI (POST/PATCH/DELETE) cần thêm Authorization: Bearer
    <access_token> — lấy từ session qua app.py (_auth_tokens_from_session()),
    KHÔNG tự quản lý token ở đây. Auto-refresh khi token hết hạn cũng nằm
    ở app.py (xem _call_authed()), KHÔNG nằm ở module này — module này chỉ
    raise CrawlerAPIError(status_code=401) khi hết hạn, để app.py tự quyết
    định refresh rồi gọi lại.
  - job/company/contact CHỈ có PATCH (sửa từng phần) — KHÔNG có PUT.
  - job KHÔNG có DELETE thật — "xóa" = PATCH job_status=CLOSED.
  - company có DELETE (thêm 08/2026) — nhưng là XOÁ MỀM (is_active=false,
    xem delete_company() bên dưới), KHÔNG xoá thật, và BẮT BUỘC kèm note
    giải thích lý do (audit log, xem khối comment "AUDIT LOG NOTE" bên dưới).
  - "Contact" (người liên hệ HR) là bảng CON của company, route riêng
    /companies/{company_id}/contacts — KHÔNG còn gộp chung với company
    như bản cũ (bản cũ coi "contact" = "company", sai hoàn toàn).
  - company KHÔNG có field CRM (fit_level/owner/hires_intern/products/
    common_positions) — đã quyết định BỎ các field này khỏi UI (xem lịch
    sử trao đổi, mục "3, 4 để sau") vì backend không có cột lưu, không
    phải thiếu sót ở module này.
  - Job tạo thủ công giờ CÓ mô tả đầy đủ qua parsed_content
    (job_description/requirements/perks/required_skills) — trước đây
    field này chỉ job crawl mới có.

Mọi field trả về từ backend được CHUẨN HÓA (map) sang tên field mà
template đang dùng (job.company, job.position...), giữ nguyên tinh thần
bản cũ để đỡ phải sửa lại toàn bộ giao diện hiển thị (chỉ sửa phần
form nhập liệu — nơi field/enum thực sự đổi).

AUDIT LOG NOTE (thêm 08/2026, xem sql/migration_add_audit_logs.sql +
db.ACTION_LOG_RULES ở backend): các hàm sửa/xoá JD, company, HR contact
bên dưới nhận thêm 1 tham số `note` — nội dung ghi vào audit_logs.note,
KHÔNG PHẢI ss_team_notes (note nội bộ hiển thị ngay trên JD, đã có sẵn
từ trước, field backend riêng `ss_team_notes`). Vì 2 khái niệm dễ nhầm
tên, form HTML dùng tên input RIÊNG `activity_note` cho note audit log
(khác `note` cũ vẫn giữ nguyên cho ss_team_notes) — xem app.py đọc
`request.form.get("activity_note")` khi gọi các hàm dưới đây.

note BẮT BUỘC (backend trả 422 nếu thiếu, xem CompanyDeleteRequest/
ContactDeleteRequest/CompanyContactUpdate/ContactAssignUpdate ở
api/schemas.py backend) cho: xoá company, sửa contact, xoá contact,
gán contact. TUỲ CHỌN (None hợp lệ) cho: sửa/xoá JD, sửa company, tạo
contact.
"""

import os
import requests

CRAWLER_API_URL = os.environ.get("CRAWLER_API_URL", "https://scrap-jd-api.onrender.com").rstrip("/")
CRAWLER_API_KEY = os.environ.get("CRAWLER_API_KEY")

REQUEST_TIMEOUT = 20  # giây — Render free tier có thể "ngủ", lần gọi đầu có thể chậm


class CrawlerAPIError(Exception):
    """Lỗi khi gọi backend — message đã ở dạng tiếng Việt để flash cho user.

    status_code: giữ lại mã lỗi HTTP gốc — app.py dùng để phân biệt 401
    (access token hết hạn -> nên tự refresh rồi thử lại) với các lỗi
    khác (400/404/409 -> hiện thẳng cho user, không thử lại)."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _headers(access_token: str | None = None) -> dict:
    if not CRAWLER_API_KEY:
        raise CrawlerAPIError(
            "Server chưa cấu hình CRAWLER_API_KEY (biến môi trường trong .env) "
            "nên không thể gọi backend."
        )
    headers = {"X-API-Key": CRAWLER_API_KEY}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _request(method, path, access_token=None, **kwargs):
    url = f"{CRAWLER_API_URL}{path}"
    try:
        res = requests.request(
            method, url, headers=_headers(access_token), timeout=REQUEST_TIMEOUT, **kwargs
        )
    except requests.exceptions.RequestException as exc:
        raise CrawlerAPIError(f"Không kết nối được tới backend ({url}): {exc}") from exc

    if res.status_code == 404:
        return None

    if res.ok:
        if res.status_code == 204 or not res.content:
            return {}
        return res.json()

    try:
        detail = res.json().get("detail", "") or ""
    except Exception:
        detail = res.text[:300]

    if res.status_code == 401:
        # KHÔNG raise message "hết hạn" cứng ở đây — có thể là do chưa
        # đăng nhập (access_token=None) hoặc token thật sự hết hạn, app.py
        # tự phân biệt qua việc có access_token truyền vào hay không.
        raise CrawlerAPIError(detail or "Chưa đăng nhập hoặc phiên đã hết hạn.", status_code=401)
    if res.status_code == 403:
        raise CrawlerAPIError(detail or "Tài khoản không có quyền thực hiện thao tác này.", status_code=403)
    if res.status_code == 409:
        raise CrawlerAPIError(detail or "Dữ liệu bị trùng.", status_code=409)
    if res.status_code == 422:
        raise CrawlerAPIError(f"Dữ liệu gửi lên không hợp lệ: {detail}", status_code=422)

    raise CrawlerAPIError(f"Backend lỗi {res.status_code} khi {method} {path}: {detail}", status_code=res.status_code)


# ---------------------------------------------------------------------------
# Bảng ánh xạ VN <-> mã backend — form/hiển thị dùng tiếng Việt, request gửi
# lên backend dùng đúng enum backend yêu cầu.
# ---------------------------------------------------------------------------

JOB_STATUS_MAP = {"OPEN": "Đang tuyển", "CLOSED": "Đã đóng"}
JOB_STATUS_MAP_REV = {v: k for k, v in JOB_STATUS_MAP.items()}

# Khớp 1:1 với LEVEL_CODE_VALUES (constants.py backend) — dùng làm nguồn
# tĩnh cho dropdown "chọn lại level" ở bước Import (_dm_import.html,
# 08/2026), truyền qua template context ở blueprints/data_management.py.
# Nếu backend đổi danh sách này (thêm/bớt level) phải tự sửa tay ở đây
# theo (khác GET /enums vốn tự động đồng bộ — xem docstring get_enums()
# ở api/routers/meta.py backend — nhưng route đó cần thêm 1 lượt gọi
# AJAX riêng lúc mở tab import, trong khi list 7 giá trị này gần như
# không đổi nên tạm chấp nhận hardcode để đỡ round-trip mạng).
LEVEL_CODES = ["Intern", "Fresher", "Junior", "Middle", "Senior", "Lead", "Manager"]

WORK_TYPE_MAP = {"FULL_TIME": "Toàn thời gian", "PART_TIME": "Bán thời gian",
                  "INTERNSHIP": "Thực tập", "OTHER": "Khác"}
WORK_TYPE_MAP_REV = {v: k for k, v in WORK_TYPE_MAP.items()}

SALARY_TYPE_MAP = {"RANGE": "Khoảng lương", "EXACT": "Mức cố định", "UPTO": "Lên đến",
                    "STARTING_FROM": "Từ", "NEGOTIABLE": "Thỏa thuận", "UNPAID": "Không lương"}
SALARY_TYPE_MAP_REV = {v: k for k, v in SALARY_TYPE_MAP.items()}

# salary_period (thêm 08/2026, xem sql/migration_add_salary_period.sql
# + README.md mục "Bug đã sửa: lương '/năm' bị hiểu nhầm thành
# lương/tháng"): chu kỳ trả lương của salary_min/salary_max. Trước đây
# form KHÔNG có ô này -> mọi job nhập tay lương NĂM qua web bị backend
# mặc định hiểu nhầm là lương/tháng (sai lệch 12 lần), y hệt bug từng
# gặp ở job crawl. "MONTH" là default cả ở đây lẫn ở backend, khớp hành
# vi trước khi có field này (không làm lệch job cũ).
SALARY_PERIOD_MAP = {"MONTH": "Tháng", "YEAR": "Năm"}
SALARY_PERIOD_MAP_REV = {v: k for k, v in SALARY_PERIOD_MAP.items()}

CONTACT_STATUS_MAP = {"UNCONTACTED": "Chưa liên hệ", "EMAIL_SENT": "Đã gửi email",
                       "RESPONDED": "Đã phản hồi", "IN_PARTNERSHIP": "Đang hợp tác"}
CONTACT_STATUS_MAP_REV = {v: k for k, v in CONTACT_STATUS_MAP.items()}

# Đánh giá tiềm năng hợp tác của company — staff tự chấm tay qua UI add/edit
# company (xem sql/migration_add_partnership_potential.sql). UNVERIFIED =
# "chưa đánh giá" (mặc định), KHÔNG phải "tiềm năng thấp" — cố ý đặt tên
# tiếng Việt khác hẳn "Thấp" để staff không nhầm 2 khái niệm này.
PARTNERSHIP_POTENTIAL_MAP = {"HIGH": "Cao", "MEDIUM": "Trung bình",
                              "LOW": "Thấp", "UNVERIFIED": "Chưa đánh giá"}
PARTNERSHIP_POTENTIAL_MAP_REV = {v: k for k, v in PARTNERSHIP_POTENTIAL_MAP.items()}


def _to_int(value):
    try:
        return int(str(value).replace(",", "").strip()) if str(value).strip() else None
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Chuẩn hóa (mapping) field backend -> field template đang dùng
# ---------------------------------------------------------------------------

def _fmt_salary(raw: dict) -> str:
    smin, smax = raw.get("salary_min"), raw.get("salary_max")
    stype = SALARY_TYPE_MAP.get(raw.get("salary_type") or "", raw.get("salary_type") or "")
    currency = raw.get("currency") or "VNĐ"
    # Chỉ gắn "/ Năm" khi period = YEAR — period = MONTH (mặc định, đa số
    # job) KHÔNG hiện "/ Tháng" để đỡ rối, khớp cách các trang tuyển dụng
    # (TopCV, VietnamWorks...) vẫn hay bỏ ngỏ "/tháng" nhưng LUÔN ghi rõ
    # "/năm" vì đó là trường hợp cần lưu ý (xem README bug salary_period).
    period_suffix = " / Năm" if (raw.get("salary_period") or "MONTH") == "YEAR" else ""
    if not smin and not smax:
        return stype or "Thỏa thuận"
    if smin and smax:
        return f"{smin:,.0f} - {smax:,.0f} {currency}{period_suffix} ({stype})".strip()
    return f"{(smin or smax):,.0f} {currency}{period_suffix} ({stype})".strip()


def _normalize_job(raw: dict) -> dict | None:
    if raw is None:
        return None
    parsed = raw.get("parsed_content") or {}
    skills = parsed.get("required_skills") or []
    return {
        "id": raw.get("job_id"),
        "company": raw.get("company_name") or "",
        "company_id": raw.get("company_id"),
        "position": raw.get("job_title") or "",
        "industry": raw.get("matching_industry") or "",
        "level": raw.get("level_code") or "",
        "location": raw.get("province_name") or "",
        "work_type": WORK_TYPE_MAP.get(raw.get("work_type") or "", raw.get("work_type") or ""),
        "work_type_raw": raw.get("work_type") or "",
        "description": parsed.get("job_description") or "",
        "requirements": parsed.get("requirements") or "",
        "skills": ", ".join(skills) if skills else "",
        "salary": _fmt_salary(raw),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "salary_type": SALARY_TYPE_MAP.get(raw.get("salary_type") or "", raw.get("salary_type") or ""),
        "salary_type_raw": raw.get("salary_type") or "NEGOTIABLE",
        "salary_period": SALARY_PERIOD_MAP.get(raw.get("salary_period") or "MONTH", raw.get("salary_period") or "MONTH"),
        "salary_period_raw": raw.get("salary_period") or "MONTH",
        "currency": raw.get("currency") or "VNĐ",
        "benefits": parsed.get("perks") or "",
        "deadline": raw.get("deadline"),
        "jd_link": raw.get("source_url") or "",
        "source": raw.get("source_name") or "",
        "date_collected": raw.get("created_at"),
        "status": JOB_STATUS_MAP.get(raw.get("job_status") or "", raw.get("job_status") or ""),
        "status_raw": raw.get("job_status") or "OPEN",
        "note": raw.get("ss_team_notes") or "",
        # created_by/updated_by (thêm 08/2026, trang /staff-activity) — ai
        # tự nhập tay job này qua web. NULL với job crawl tự động (chỉ
        # job POST /jobs thủ công mới có, xem api/routers/jobs.py). Giữ
        # nguyên UUID string hoặc None, KHÔNG có bảng map hiển thị vì
        # đây là id, template tự tra tên qua danh sách staff khi cần.
        "created_by": raw.get("created_by"),
        "updated_by": raw.get("updated_by"),
    }


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
        # created_by/updated_by — cùng ý nghĩa với _normalize_job(), xem
        # comment ở đó. NULL với company crawl tự động.
        "created_by": raw.get("created_by"),
        "updated_by": raw.get("updated_by"),
    }


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
        # created_by — ai tự thêm contact này (xem _normalize_job() cho
        # ý nghĩa chung). assigned_ss_user — ai đang PHỤ TRÁCH contact
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


def _build_parsed_content(form) -> dict:
    parsed = {}
    if (form.get("description") or "").strip():
        parsed["job_description"] = form["description"].strip()
    if (form.get("requirements") or "").strip():
        parsed["requirements"] = form["requirements"].strip()
    if (form.get("benefits") or "").strip():
        parsed["perks"] = form["benefits"].strip()
    skills = [s.strip() for s in (form.get("skills") or "").split(",") if s.strip()]
    if skills:
        parsed["required_skills"] = skills
    return parsed


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def list_jobs(q="", industry="", level="", location="", status="", created_by="", limit=200, offset=0):
    params = {"limit": limit, "offset": offset}
    if q:
        params["keyword"] = q
    if industry:
        params["industry"] = industry
    if level:
        params["level"] = level
    if location:
        params["province"] = location
    if status:
        params["status"] = JOB_STATUS_MAP_REV.get(status, status)
    if created_by:
        # Lọc job do 1 thành viên ss_team/admin cụ thể TỰ NHẬP TAY (thêm
        # 08/2026, trang /staff-activity) — job crawl tự động có
        # created_by NULL nên không bao giờ khớp filter này, xem
        # api/routers/jobs.py::list_jobs().
        params["created_by"] = created_by
    data = _request("GET", "/jobs", params=params) or {}
    items = data.get("items", data if isinstance(data, list) else [])
    return [_normalize_job(j) for j in items]


def count_jobs(q="", industry="", level="", location="", status="", created_by=""):
    """Dùng field `total` backend trả sẵn trong response phân trang —
    KHÔNG cố lấy limit=1000 rồi đếm len() (backend chặn limit tối đa
    200, gửi 1000 sẽ bị 422 'Input should be less than or equal to 200').
    Nhận đúng bộ filter như list_jobs() để `total` khớp với danh sách
    đang lọc (dùng cho phân trang) chứ không phải tổng toàn bộ DB."""
    params = {"limit": 1}
    if q:
        params["keyword"] = q
    if industry:
        params["industry"] = industry
    if level:
        params["level"] = level
    if location:
        params["province"] = location
    if status:
        params["status"] = JOB_STATUS_MAP_REV.get(status, status)
    if created_by:
        params["created_by"] = created_by
    data = _request("GET", "/jobs", params=params) or {}
    return data.get("total", 0)


# Backend GET /jobs giới hạn limit tối đa 200/lần gọi, cùng kiểu với
# GET /companies (xem _MAX_COMPANIES_PAGE ở list_all_companies() bên
# dưới) — gọi list_jobs(limit=1000) thẳng sẽ bị 422 "Input should be
# less than or equal to 200". Dùng hàm này ở bất kỳ đâu cần TOÀN BỘ
# job một lần (vd tính thống kê trên dashboard theo tháng — cần biết
# deadline/date_collected của từng job, không phải chỉ 1 con số total)
# thay vì bịa 1 con số limit lớn hơn 200.
_MAX_JOBS_PAGE = 200
_ALL_JOBS_SAFETY_CAP = 5000  # chặn vòng lặp vô hạn nếu backend trả total sai


def list_all_jobs(q="", industry="", level="", location="", status="", created_by=""):
    """Lấy TOÀN BỘ job khớp filter bằng cách tự phân trang theo đúng
    limit tối đa backend cho phép (200/lần), gộp lại thành 1 list — dùng
    khi cần dữ liệu chi tiết (không chỉ đếm) của mọi job, ví dụ nhóm job
    theo tháng deadline/date_collected cho dashboard, hoặc "mọi job 1
    staff đã tự nhập tay" cho trang /staff-activity (created_by=uid)."""
    total = count_jobs(q=q, industry=industry, level=level, location=location,
                        status=status, created_by=created_by)
    all_items: list = []
    offset = 0
    while offset < total and offset < _ALL_JOBS_SAFETY_CAP:
        page = list_jobs(q=q, industry=industry, level=level, location=location,
                          status=status, created_by=created_by, limit=_MAX_JOBS_PAGE, offset=offset)
        if not page:
            break
        all_items.extend(page)
        offset += _MAX_JOBS_PAGE
    return all_items


def get_stats() -> dict:
    """GET /stats — tổng job, tổng công ty, tổng đơn ứng tuyển (total_applications,
    thêm 08/2026)... Chỉ cần API key, không cần access_token. Dùng cho dashboard."""
    return _request("GET", "/stats") or {}


def get_engagement_stats() -> dict:
    """GET /stats/engagement (thêm 08/2026, cùng lúc dashboard 4 tab) —
    trả {"jobs": [...], "monthly": {...}}:
    - jobs: MỌI job đang OPEN kèm application_count/saved_count gộp sẵn
      (dùng lọc "JD sắp hết hạn chưa ai quan tâm" / "JD ế" phía
      dashboard() mà không phải gọi N+1 request cho từng job).
    - monthly: tổng ứng tuyển/lưu job THÁNG NÀY vs THÁNG TRƯỚC, dùng
      tính % chênh lệch cho tab "Báo cáo tháng".
    Chỉ cần API key, không cần access_token — giống get_stats()."""
    return _request("GET", "/stats/engagement") or {}


def is_duplicate_candidate(job: dict) -> bool:
    matches = list_jobs(q=job["company"], limit=50)
    return any(
        j["company"] == job["company"] and j["position"] == job["position"] and j["id"] != job["id"]
        for j in matches
    )


def get_job(job_id):
    raw = _request("GET", f"/jobs/{job_id}")
    return _normalize_job(raw)


def create_job(access_token, form, company_id) -> dict:
    payload = {
        "job_title": form["position"].strip(),
        "company_id": company_id,
        "matching_industry": (form.get("industry") or "").strip() or None,
        "level_code": (form.get("level") or "").strip() or None,
        "province_name": (form.get("location") or "").strip() or None,
        "work_type": WORK_TYPE_MAP_REV.get(form.get("work_type", ""), form.get("work_type") or None),
        "currency": (form.get("currency") or "VNĐ").strip(),
        "salary_min": _to_int(form.get("salary_min")),
        "salary_max": _to_int(form.get("salary_max")),
        "salary_type": SALARY_TYPE_MAP_REV.get(form.get("salary_type", ""), form.get("salary_type") or "NEGOTIABLE"),
        "salary_period": SALARY_PERIOD_MAP_REV.get(form.get("salary_period", ""), form.get("salary_period") or "MONTH"),
        "deadline": form.get("deadline") or None,
    }
    parsed = _build_parsed_content(form)
    if parsed:
        payload["parsed_content"] = parsed
    raw = _request("POST", "/jobs", access_token=access_token, json=payload)
    return _normalize_job(raw)


def update_job(access_token, job_id, form) -> dict:
    payload = {
        "job_title": form["position"].strip(),
        "matching_industry": (form.get("industry") or "").strip() or None,
        "level_code": (form.get("level") or "").strip() or None,
        "province_name": (form.get("location") or "").strip() or None,
        "work_type": WORK_TYPE_MAP_REV.get(form.get("work_type", ""), form.get("work_type") or None),
        "currency": (form.get("currency") or "VNĐ").strip(),
        "salary_min": _to_int(form.get("salary_min")),
        "salary_max": _to_int(form.get("salary_max")),
        "salary_type": SALARY_TYPE_MAP_REV.get(form.get("salary_type", ""), form.get("salary_type") or "NEGOTIABLE"),
        "salary_period": SALARY_PERIOD_MAP_REV.get(form.get("salary_period", ""), form.get("salary_period") or "MONTH"),
        "deadline": form.get("deadline") or None,
        "ss_team_notes": (form.get("note") or "").strip() or None,
        # note audit log — TUỲ CHỌN, KHÁC ss_team_notes ở trên (xem
        # docstring đầu file, mục "AUDIT LOG NOTE").
        "note": (form.get("activity_note") or "").strip() or None,
    }
    parsed = _build_parsed_content(form)
    if parsed:
        payload["parsed_content"] = parsed
    raw = _request("PATCH", f"/jobs/{job_id}", access_token=access_token, json=payload)
    return _normalize_job(raw)


def update_job_status(access_token, job_id, status_vn, note=None):
    """status_vn: nhãn tiếng Việt (vd 'Đã đóng') hoặc mã backend thẳng
    (vd 'CLOSED') — tự nhận diện qua JOB_STATUS_MAP_REV.

    note (thêm 08/2026): TUỲ CHỌN — nếu status đổi thành CLOSED, backend
    tự ghi log này thành DELETE_JOB thay vì UPDATE_JOB (xem
    api/routers/jobs.py::patch_job ở backend), note ở đây là lý do đóng/
    đổi trạng thái job, không liên quan ss_team_notes."""
    code = JOB_STATUS_MAP_REV.get(status_vn, status_vn)
    payload = {"job_status": code, "note": (note or "").strip() or None}
    raw = _request("PATCH", f"/jobs/{job_id}", access_token=access_token, json=payload)
    return _normalize_job(raw)


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

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
    """Dùng field `total` backend trả sẵn — xem giải thích ở count_jobs().
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
    # note audit log — TUỲ CHỌN (xem docstring đầu file, mục "AUDIT LOG
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


# ---------------------------------------------------------------------------
# Company contacts (người liên hệ HR) — bảng CON của company, route riêng
# ---------------------------------------------------------------------------

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
        # note audit log — TUỲ CHỌN (xem docstring đầu file, mục "AUDIT
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


# ---------------------------------------------------------------------------
# Audit logs — "Lịch sử thao tác" (thêm 08/2026, xem
# sql/migration_add_audit_logs.sql phía backend). 2 view auto/manual
# trên CÙNG 1 endpoint GET /audit-logs, khác nhau ở query param `view`
# — KHÔNG phải 2 route riêng, mirror đúng thiết kế backend.
# ---------------------------------------------------------------------------

ACTION_TYPE_MAP = {
    "CREATE_JOB": "Thêm JD", "UPDATE_JOB": "Sửa JD", "DELETE_JOB": "Xoá JD",
    "CREATE_COMPANY": "Thêm công ty", "UPDATE_COMPANY": "Sửa công ty", "DELETE_COMPANY": "Xoá công ty",
    "CREATE_CONTACT": "Thêm người liên hệ", "UPDATE_CONTACT": "Sửa người liên hệ",
    "DELETE_CONTACT": "Xoá người liên hệ", "ASSIGN_CONTACT": "Gán người phụ trách",
    "APPLY_JOB": "Ứng viên nộp CV", "WITHDRAW_JOB_APPLICATION": "Ứng viên huỷ ứng tuyển",
}
ENTITY_TYPE_MAP = {"JOB": "JD", "COMPANY": "Công ty", "CONTACT": "Người liên hệ", "APPLICATION": "Đơn ứng tuyển"}


def _normalize_audit_log(raw: dict) -> dict:
    return {
        "id": raw.get("log_id"),
        "actor_id": raw.get("actor_id"),
        # actor_name None -> "Hệ thống (tự động)" thay vì để trống —
        # actor_id NULL nghĩa là thao tác tự động, KHÔNG phải lỗi thiếu
        # dữ liệu (xem docstring db.log_action() phía backend).
        "actor_name": raw.get("actor_name") or "Hệ thống (tự động)",
        "action_type": raw.get("action_type") or "",
        "action_label": ACTION_TYPE_MAP.get(raw.get("action_type"), raw.get("action_type") or ""),
        "entity_type": raw.get("entity_type") or "",
        "entity_label_type": ENTITY_TYPE_MAP.get(raw.get("entity_type"), raw.get("entity_type") or ""),
        "entity_id": raw.get("entity_id"),
        "entity_label": raw.get("entity_label") or "",
        "company_id": raw.get("company_id"),
        "company_name": raw.get("company_name") or "",
        "changes": raw.get("changes") or {},
        "is_manual_log": raw.get("is_manual_log", False),
        "note_required": raw.get("note_required", False),
        "note": raw.get("note") or "",
        "note_updated_by": raw.get("note_updated_by"),
        "note_updated_at": raw.get("note_updated_at"),
        "created_at": raw.get("created_at"),
    }


def list_audit_logs(access_token, *, view="auto", entity_type="", company_id="", actor_id="",
                     action_type="", pending_note=None, limit=50, offset=0) -> dict:
    """GET /audit-logs — trả {"items": [...], "total": int}.

    BẮT BUỘC truyền access_token thật — route backend yêu cầu
    require_role("ss_team") qua chính JWT trong Authorization header
    (KHÔNG chỉ check API key như GET /jobs, /companies công khai), xem
    api/deps.py::require_role backend. Gọi qua _call_authed() ở app.py
    để tự refresh nếu access_token hết hạn giữa chừng, giống mọi hàm
    cần access_token khác trong file này."""
    params = {"view": view, "limit": limit, "offset": offset}
    if entity_type:
        params["entity_type"] = entity_type
    if company_id:
        params["company_id"] = company_id
    if actor_id:
        params["actor_id"] = actor_id
    if action_type:
        params["action_type"] = action_type
    if pending_note is not None:
        params["pending_note"] = "true" if pending_note else "false"
    data = _request("GET", "/audit-logs", access_token=access_token, params=params) or {}
    items = [_normalize_audit_log(r) for r in data.get("items", [])]
    return {"items": items, "total": data.get("total", 0)}


def update_audit_log_note(access_token, log_id, note) -> dict:
    """PATCH /audit-logs/{log_id}/note — CHỈ actor GỐC của log (người
    thực hiện thao tác đó) mới gọi được, backend trả 403 nếu người
    khác gọi (xem api/routers/audit_logs.py::update_note backend) —
    app.py nên ẨN nút sửa note nếu current_user khác actor_id, nhưng
    vẫn phải bắt CrawlerAPIError(403) ở đây phòng người dùng cố tình
    gọi thẳng URL."""
    raw = _request("PATCH", f"/audit-logs/{log_id}/note", access_token=access_token, json={"note": note})
    return _normalize_audit_log(raw)


# ---------------------------------------------------------------------------
# Import / Export (trang /data-management)
#
# ⚠️ Router backend api/routers/import_export.py CHƯA được code ở phía
# backend tại thời điểm viết module này (chỉ mới chốt DESIGN qua trao
# đổi, xem lịch sử — 6 endpoint dưới đây là CONTRACT đã thống nhất,
# không phải code đã verify chạy thật). Khi backend triển khai xong,
# nếu path/field lệch so với dưới đây thì sửa LẠI CHÍNH module này,
# không cần đụng app.py/template (mọi chỗ khác chỉ gọi qua các hàm này).
#
# ENTITY_TYPE dùng trong path: "job" | "company" | "contact" (chữ
# thường, số ít — khác ENTITY_TYPE_MAP ở trên vốn dùng cho audit log,
# key "JOB"/"COMPANY"/"CONTACT" chữ hoa; 2 map KHÔNG dùng lẫn nhau).
# ---------------------------------------------------------------------------

IMPORT_EXPORT_ENTITY_TYPES = ["job", "company", "contact"]
IMPORT_EXPORT_ENTITY_LABELS = {"job": "JD", "company": "Công ty", "contact": "Người liên hệ HR"}

# Nhãn hiển thị cho conflict_status trả về từ conflict_detector backend
# (xem preview row "conflict_status" bên dưới) — 4 trạng thái thật sự trả
# về bởi api/services/preview_manager.py + conflict_detector.py (đã đối
# chiếu lại với backend 08/2026, KHÁC với bản nháp contract cũ 3 trạng
# thái "new"/"conflict"/"conflict_inactive" từng viết ở đây trước khi
# backend triển khai xong):
#   - "no_conflict": không trùng, tạo mới bình thường
#   - "conflict": trùng với bản ghi ĐANG active (cho chọn Skip/Update/Create)
#   - "conflict_inactive": trùng với bản ghi INACTIVE/CLOSED/EXPIRED (cảnh
#     báo riêng, hỏi có ghi đè + kích hoạt lại không)
#   - "pending_company_resolution": (chỉ Job/Contact) company_name trong
#     file chưa map thẳng ra được company_id, cần staff tự chọn
CONFLICT_STATUS_LABELS = {
    "no_conflict": "Dòng mới",
    "conflict": "Trùng dữ liệu",
    "conflict_inactive": "Trùng — bản ghi đã ngừng hoạt động",
    "pending_company_resolution": "Cần chọn công ty",
}


def export_entity(access_token, entity_type, file_format="xlsx"):
    """GET /export/{entity_type} — trả file nhị phân (CSV hoặc XLSX).

    Khác mọi hàm khác trong file này: trả về (content_bytes, filename,
    content_type) thay vì dict đã chuẩn hoá, vì đây là file tải xuống
    thẳng cho user (app.py dùng send_file/Response), không phải data
    hiển thị trên UI. Raise CrawlerAPIError nếu backend lỗi — app.py tự
    bắt và flash, KHÔNG trả file rỗng để tránh user tải nhầm file hỏng."""
    url = f"{CRAWLER_API_URL}/export/{entity_type}"
    try:
        res = requests.get(
            url, headers=_headers(access_token), params={"format": file_format},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise CrawlerAPIError(f"Không kết nối được tới backend ({url}): {exc}") from exc

    if not res.ok:
        try:
            detail = res.json().get("detail", "") or ""
        except Exception:
            detail = res.text[:300]
        raise CrawlerAPIError(f"Xuất file thất bại ({res.status_code}): {detail}", status_code=res.status_code)

    content_type = res.headers.get("Content-Type", "application/octet-stream")
    # Backend nên trả Content-Disposition kèm filename gợi ý; nếu thiếu,
    # tự đặt tên theo đúng convention Requirement 1.9 (đã chốt) làm dự
    # phòng — KHÔNG để app.py phải tự đoán tên file.
    disposition = res.headers.get("Content-Disposition", "")
    filename = None
    if "filename=" in disposition:
        filename = disposition.split("filename=")[-1].strip('"; ')
    if not filename:
        ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = "xlsx" if file_format == "xlsx" else "csv"
        filename = f"{entity_type}_export_{ts}.{ext}"
    return res.content, filename, content_type


def _normalize_preview_row(raw: dict, id_field: str | None = None) -> dict:
    # Backend (api/services/preview_manager.py::build_preview) trả field
    # "existing_record" (không tách existing_data/existing_id riêng) và
    # "company_resolution": {"status": "resolved"|"needs_resolution",
    # "company_id", "company_is_active", "suggestions": [...]}  (không
    # phải "needs_company_resolve"/"resolved_company_id" phẳng như bản
    # nháp contract cũ) — đối chiếu lại 08/2026, sửa cho khớp thật.
    # needs_field_fix/field_errors (thêm 08/2026 — xem preview_manager.py
    # docstring): field lỗi type/required/business-rule KHÔNG còn chặn
    # nguyên file ở bước upload nữa (trừ required_column_missing, vẫn
    # reject cứng ở import_preview() bên dưới) — pass-through nguyên 2
    # field này để _dm_import.html render ô sửa tại chỗ trên bảng
    # preview, KHÔNG transform gì thêm (widget_type/options đã tính sẵn
    # ở backend, xem entity_specs.field_widget_type/field_options).
    #
    # id_field: tên cột PK thật của entity (vd "job_id") — LẤY TỪ
    # summary.id_field mà backend trả về (xem EntitySpec.id_field,
    # api/services/entity_specs.py backend + _normalize_preview_summary()
    # bên dưới, nơi gọi hàm này), KHÔNG tự đoán bằng map hardcode
    # entity_type -> tên cột id ở tầng gọi (bản cũ ở đây từng có 1 dict
    # {"job": "job_id", "company": "company_id", "contact": "contact_id"}
    # ngay trong hàm — dễ quên cập nhật khi thêm entity mới, vì nó không
    # nằm cạnh IMPORT_EXPORT_ENTITY_TYPES/CONFLICT_STATUS_LABELS là chỗ
    # người sửa code tự nhiên nghĩ tới. Giờ backend là nguồn sự thật duy
    # nhất cho tên cột id, module này chỉ đọc lại).
    company_resolution = raw.get("company_resolution") or {}
    status = raw.get("conflict_status") or "no_conflict"
    existing_record = raw.get("existing_record")
    return {
        "row_index": raw.get("row_index"),
        "data": raw.get("data") or {},
        "conflict_status": status,
        "conflict_status_label": CONFLICT_STATUS_LABELS.get(status, status),
        "existing_data": existing_record,
        "existing_id": (existing_record.get(id_field) if id_field else None) if existing_record else None,
        "needs_company_resolve": status == "pending_company_resolution",
        "resolved_company_id": company_resolution.get("company_id"),
        "resolved_company_name": company_resolution.get("company_name"),
        "company_suggestions": company_resolution.get("suggestions") or [],
        # needs_level_resolve/level_code_raw (chỉ Job, 08/2026 — xem
        # preview_manager.py::build_preview): TRỤC ĐỘC LẬP với
        # conflict_status/needs_company_resolve ở trên — 1 dòng "no_conflict"
        # vẫn có thể cần chọn lại level (level_code trong file không khớp
        # 1 trong 7 giá trị hợp lệ dù đã chuẩn hoá hoa/thường), nên KHÔNG
        # gộp vào conflict_status_label như 1 trạng thái riêng.
        "needs_level_resolve": bool(raw.get("needs_level_resolve")),
        "level_code_raw": raw.get("level_code_raw"),
        "needs_field_fix": bool(raw.get("needs_field_fix")),
        # field_errors: {field_name: {"rule","message","raw_value",
        # "widget_type","options"}} — {} nếu needs_field_fix=false. Giữ
        # nguyên key/shape backend trả, _dm_import.html đọc thẳng field
        # này (widget_type quyết định select/input type=date/input số/
        # input chữ, options chỉ có giá trị khi widget_type=="enum").
        "field_errors": raw.get("field_errors") or {},
        "errors": [],
    }


def _normalize_preview_summary(raw: dict) -> dict:
    # Backend (ImportUploadResponse, api/schemas.py) lồng các số đếm
    # trong "summary" — KHÔNG ở top-level — và dùng tên field khác:
    # total_rows / new_records / conflicts / conflicts_inactive /
    # pending_company_resolution / id_field (xem preview_manager.py::
    # build_preview). Bản cũ ở đây đọc raw.get("total_rows"/"new_count"/
    # ...) thẳng ở top-level -> luôn miss, luôn fallback 0 (bug đã xác
    # nhận 08/2026).
    summary = raw.get("summary") or {}
    entity_type = raw.get("entity_type")
    id_field = summary.get("id_field")
    rows = [_normalize_preview_row(r, id_field=id_field) for r in raw.get("rows", [])]
    return {
        "preview_id": raw.get("preview_id"),
        "entity_type": entity_type,
        "id_field": id_field,
        "total_rows": summary.get("total_rows", 0),
        "new_count": summary.get("new_records", 0),
        "conflict_count": summary.get("conflicts", 0),
        "conflict_inactive_count": summary.get("conflicts_inactive", 0),
        "error_count": summary.get("errors", 0),
        "needs_company_resolve_count": summary.get("pending_company_resolution", 0),
        "needs_level_resolve_count": summary.get("pending_level_resolution", 0),
        # pending_field_fix_count (thêm 08/2026, xem preview_manager.py):
        # tổng số dòng có needs_field_fix=true trong preview này — dùng
        # để hiện ô thống kê "Cần sửa dữ liệu" trên _dm_import.html giống
        # cách needs_company_resolve_count/needs_level_resolve_count đã
        # hiện (chỉ hiện ô khi > 0, xem template).
        "needs_field_fix_count": summary.get("pending_field_fix", 0),
        "expires_at": raw.get("expires_at"),
        "rows": rows,
    }


def _format_import_errors_detail(detail) -> str:
    """Backend (api/routers/import_export.py::import_preview) là DUY NHẤT
    chỗ trả HTTPException.detail dạng OBJECT thay vì string trong toàn bộ
    backend (đã grep 'detail={' khắp api/routers/, chỉ có đúng 1 kết quả)
    — mọi route khác luôn trả detail dạng string thuần, các hàm khác
    trong file này (đọc res.json().get("detail","") rồi dùng thẳng) vẫn
    đúng, KHÔNG cần đổi.

    Shape thật của detail khi file có dòng validate lỗi (422):
        {"message": "File có dòng không hợp lệ...",
         "errors": [{"row_number": int, "field_name": str, "rule": str,
                      "message": str}, ...]}

    BUG (08/2026, phát hiện qua ảnh chụp màn hình staff báo lỗi import
    contact): import_preview() cũ gán thẳng
    `detail = res.json().get("detail", "")` (ra 1 dict) rồi nhét vào
    f-string `f"File không hợp lệ: {detail}"` — Python f-string gọi
    str(dict) trên 1 dict lồng list-of-dict -> in NGUYÊN literal Python
    (`{'message': ..., 'errors': [{'row_number': 4, ...}]}`) thẳng ra
    flash message cho staff xem, không ai đọc nổi — dù nội dung lỗi bên
    trong (mỗi error["message"]) thật ra đã viết sẵn dạng câu tiếng Việt
    dễ hiểu ("Dòng 4, cột 'work_email': email không hợp lệ ...").

    Hàm này tách riêng để format lại: nối error["message"] (ĐÃ viết sẵn
    dễ đọc, không cần tự dựng câu từ row_number/field_name/rule) mỗi lỗi
    1 dòng, giới hạn hiện tối đa 20 dòng đầu (file cho phép tới 5.000
    dòng — lỗi hàng loạt kiểu sai nguyên 1 cột thì in hết ra vô ích, tràn
    màn hình) + báo còn bao nhiêu lỗi khác nếu vượt quá. Nếu detail không
    phải dict (route khác, hoặc backend đổi shape) -> trả thẳng str(detail)
    làm fallback an toàn, không throw."""
    if not isinstance(detail, dict):
        return str(detail)
    message = detail.get("message") or "File có dòng không hợp lệ."
    errors = detail.get("errors") or []
    if not errors:
        return message
    MAX_SHOWN = 20
    lines = [message]
    for err in errors[:MAX_SHOWN]:
        err_message = err.get("message")
        if err_message:
            lines.append(f"- {err_message}")
        else:
            # Fallback nếu backend đổi shape sau này, thiếu sẵn "message"
            # cho 1 error entry — vẫn dựng được câu tối thiểu từ 3 field
            # còn lại thay vì bỏ trống dòng đó.
            row = err.get("row_number", "?")
            field = err.get("field_name", "?")
            rule = err.get("rule", "?")
            lines.append(f"- Dòng {row}, cột '{field}' (rule={rule}): không hợp lệ")
    if len(errors) > MAX_SHOWN:
        lines.append(f"... và {len(errors) - MAX_SHOWN} dòng lỗi khác.")
    return "\n".join(lines)


def import_preview(access_token, entity_type, file_storage):
    """POST /import/{entity_type}/preview — upload file (multipart), trả
    preview_id + summary (đếm dòng mới/conflict/lỗi) + toàn bộ rows để
    FE render bảng (bảng có thể tới 5000 dòng theo giới hạn file_parser
    backend — phân trang do JS phía template tự làm, KHÔNG phân trang
    ở tầng gọi API này).

    file_storage: werkzeug.datastructures.FileStorage (từ
    request.files["file"] trong route Flask) — đọc thẳng .stream/.filename,
    KHÔNG cần lưu ra đĩa trước."""
    url = f"{CRAWLER_API_URL}/import/{entity_type}/preview"
    files = {"file": (file_storage.filename, file_storage.stream, file_storage.mimetype)}
    try:
        res = requests.post(url, headers=_headers(access_token), files=files, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        raise CrawlerAPIError(f"Không kết nối được tới backend ({url}): {exc}") from exc

    if res.ok:
        return _normalize_preview_summary(res.json())

    try:
        detail = res.json().get("detail", "") or ""
    except Exception:
        detail = res.text[:300]
    if res.status_code == 401:
        raise CrawlerAPIError(detail or "Chưa đăng nhập hoặc phiên đã hết hạn.", status_code=401)
    if res.status_code == 403:
        raise CrawlerAPIError(detail or "Tài khoản không có quyền thực hiện thao tác này.", status_code=403)
    if res.status_code == 422:
        raise CrawlerAPIError(f"File không hợp lệ: {_format_import_errors_detail(detail)}", status_code=422)
    raise CrawlerAPIError(f"Backend lỗi {res.status_code} khi đọc preview: {detail}", status_code=res.status_code)


def get_import_preview(access_token, entity_type, preview_id):
    """GET /import/{entity_type}/preview/{preview_id} — lấy lại preview đã
    tạo (vd sau khi reload trang, hoặc load lại để render bảng phân
    trang phía JS mà không cần re-upload file). Trả None nếu preview đã
    hết hạn (TTL 1h) hoặc không thuộc user hiện tại — backend trả 404
    cho cả 2 case này để không lộ preview_id của người khác tồn tại hay
    không (_request() có sẵn coi 404 = None)."""
    raw = _request("GET", f"/import/{entity_type}/preview/{preview_id}", access_token=access_token)
    return _normalize_preview_summary(raw) if raw is not None else None


def get_company_suggestions(access_token, entity_type, preview_id, row_index):
    """GET /import/{entity_type}/preview/{preview_id}/company-suggestions?row_index=
    — danh sách công ty gợi ý (fuzzy match) cho 1 dòng cụ thể cần resolve
    company (xem company_resolver.py backend). Trả list
    [{"company_id", "company_name", "tax_id", "score"}, ...], KHÔNG tự
    chọn hộ — staff bấm chọn tay trên UI.

    BUG FIX (08/2026): backend trả về OBJECT {"suggestions": [...]}
    (CompanySuggestionsResponse — xem api/schemas.py), KHÔNG PHẢI list
    trần. Code cũ gán thẳng raw = _request(...) rồi `for s in raw` —
    lặp qua CÁC KEY của dict (chỉ có đúng 1 key "suggestions" — 1
    chuỗi), rồi gọi s.get("company_id") trên chuỗi đó -> AttributeError
    ('str' object has no attribute 'get'), Flask không bắt được lỗi
    này (không phải CrawlerAPIError) -> trả về trang lỗi 500 dạng HTML.
    Trình duyệt cố parse HTML đó thành JSON (res.json() ở
    _dm_import.html) -> thất bại -> rơi vào .catch() và hiện đúng cái
    alert "Lỗi kết nối khi tải danh sách công ty gợi ý ... (HTTP 500)"
    mà bạn thấy khi bấm "Chọn công ty..." ở bước Import.

    Field cũng bị sai tên: backend trả "similarity" (0-1), code cũ đọc
    "score" (không tồn tại) -> luôn None -> UI luôn thiếu phần "độ khớp
    x%" dù request có chạy được."""
    raw = _request(
        "GET", f"/import/{entity_type}/preview/{preview_id}/company-suggestions",
        access_token=access_token, params={"row_index": row_index},
    ) or {}
    suggestions = raw.get("suggestions") or []
    return [
        {
            "company_id": s.get("company_id"),
            "company_name": s.get("company_name") or "",
            "tax_id": s.get("tax_id") or "",
            "score": s.get("similarity"),
        }
        for s in suggestions
    ]


def import_confirm(access_token, entity_type, preview_id, resolutions, import_note):
    """POST /import/{entity_type}/confirm — chạy import thật trong 1
    transaction, ghi đúng 1 dòng audit_logs tổng hợp kèm import_note.

    Đối chiếu lại với backend thật 08/2026 (api/schemas.py::
    ImportConfirmRequest/RowResolution + api/services/import_executor.py)
    — KHÁC hoàn toàn bản nháp contract cũ từng viết ở đây:

    resolutions ở ĐÂY (tham số truyền vào hàm) vẫn là list các dict, MỖI
    DÒNG preview cần resolve gửi lên 1 phần tử:
        {
          "row_index": int,
          "action": "create" | "update" | "skip" | "reactivate",
          "selected_company_id": str | None,  # chỉ khi needs_company_resolve
          "level_code": str | None,  # chỉ khi needs_level_resolve (Job)
          "field_fixes": dict[str, str] | None,  # chỉ khi needs_field_fix
        }
    (giữ format list này ở tầng gọi vì _dm_import.html JS build ra sẵn
    dạng này) — nhưng payload GỬI LÊN BACKEND phải convert sang đúng
    contract thật:
        resolutions: {str(row_index): {"action": "skip"|"create"|"update",
                       "company_id": str|None,
                       "confirm_reactivate": bool,
                       "level_code": str|None,
                       "field_fixes": dict[str, str]|None}}
    (dict keyed theo row_index dạng CHUỖI, field tên "company_id" chứ
    không phải "selected_company_id", và action "reactivate" ở tầng gọi
    phải được dịch thành action="update" + confirm_reactivate=True vì
    backend không có action="reactivate" — xem RowResolution docstring,
    bug đã từng khiến flow ghi đè + kích hoạt lại không bao giờ chạy).
    Backend dùng model_config = ConfigDict(extra="forbid") nên field lạ
    (vd "create_new_company") sẽ khiến CẢ REQUEST bị Pydantic reject
    422, không phải bị âm thầm bỏ qua — không được gửi field thừa.

    "field_fixes" (thêm 08/2026, xem RowResolution.field_fixes +
    import_executor.py::_apply_field_fixes): BẮT BUỘC chứa đủ mọi field
    còn trong needs_field_fix/field_errors của dòng đó nếu action khác
    "skip" — backend re-validate lại giá trị staff sửa (không tin ngầm
    FE), raise lỗi rõ ràng (422) nếu thiếu/còn sai sau khi sửa. Chỉ gửi
    field này khi có giá trị, giống company_id/level_code ở trên — dòng
    không needs_field_fix thì field_fixes luôn None, không gửi key rỗng
    thừa lên backend.

    "level_code" (08/2026, xem RowResolution + import_executor.py::
    execute_import backend): BẮT BUỘC nếu dòng needs_level_resolve=true
    (Job, level_code trong file không khớp 1 trong 7 giá trị hợp lệ dù
    đã chuẩn hoá hoa/thường — xem preview_manager.py) VÀ action khác
    "skip" — check này chạy TRƯỚC NHÁNH conflict_status trong
    import_executor.py, nên áp dụng cho MỌI status kể cả "no_conflict"
    (khác company_id, vốn chỉ liên quan status="pending_company_
    resolution"). Chỉ gửi field này khi có giá trị (giống company_id) —
    _dm_import.html JS chặn submit (disable nút xác nhận) nếu dòng cần
    resolve level mà chưa chọn, nên tới được đây thì level_code coi như
    đã hợp lệ hoặc dòng đó có action="skip".

    Dòng "no_conflict"/"new" thường KHÔNG cần có trong resolutions — backend
    (import_executor.execute_import) LUÔN tạo mới dòng no_conflict bất
    kể resolution có gì hay không (Requirement 6.3) — TRỪ dòng vừa
    "no_conflict" vừa needs_level_resolve=true, bắt buộc phải có
    resolution kèm level_code (xem trên), nên tầng gọi (_dm_import.html)
    KHÔNG được lược các dòng này ra dù conflict_status="no_conflict".

    import_note: BẮT BUỘC, khác rỗng — app.py chặn submit nếu rỗng
    TRƯỚC khi gọi hàm này, nhưng vẫn để backend là nguồn xác thực cuối
    (422 nếu thiếu) phòng gọi thẳng. Backend nhận field tên "note", không
    phải "import_note" (ImportConfirmRequest.note).

    Trả {"created": int, "updated": int, "skipped": int}; backend
    (ImportConfirmResult) KHÔNG có field "reactivated" riêng — action
    reactivate được tính gộp vào "updated" (xem import_executor.py:
    _apply_conflict_action, action="update" luôn summary.updated += 1
    kể cả khi reactivate=True), nên field "reactivated" ở dict trả về
    của hàm này giữ lại = 0 cố định chỉ để khỏi phải sửa lại chỗ gọi
    hiển thị flash message, KHÔNG phản ánh số liệu thật — nếu cần đếm
    riêng, phải sửa backend trả thêm field này.
    preview bị XOÁ ở backend sau khi confirm thành công (không gọi lại
    được preview_id này nữa)."""
    resolutions_map = {}
    for entry in resolutions:
        row_index = entry.get("row_index")
        if row_index is None:
            continue
        action = entry.get("action") or "skip"
        confirm_reactivate = False
        if action == "reactivate":
            action = "update"
            confirm_reactivate = True
        resolved = {"action": action, "confirm_reactivate": confirm_reactivate}
        company_id = entry.get("selected_company_id")
        if company_id:
            resolved["company_id"] = company_id
        level_code = entry.get("level_code")
        if level_code:
            resolved["level_code"] = level_code
        field_fixes = entry.get("field_fixes")
        if field_fixes:
            resolved["field_fixes"] = field_fixes
        resolutions_map[str(row_index)] = resolved

    payload = {"preview_id": preview_id, "resolutions": resolutions_map, "note": import_note}
    raw = _request(
        "POST", f"/import/{entity_type}/confirm", access_token=access_token, json=payload,
    ) or {}
    return {
        "created": raw.get("created", 0),
        "updated": raw.get("updated", 0),
        "skipped": raw.get("skipped", 0),
        "reactivated": 0,  # backend chưa trả field này riêng — xem docstring
        "errors": raw.get("errors") or [],
    }
