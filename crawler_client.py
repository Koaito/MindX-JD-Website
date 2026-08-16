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
  - company KHÔNG có DELETE — chỉ tạo (POST, idempotent theo tax_id) và
    sửa (PATCH, thêm 08/2026).
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

JOB_STATUS_MAP = {"OPEN": "Đang tuyển", "EXPIRED": "Hết hạn", "CLOSED": "Đã đóng"}
JOB_STATUS_MAP_REV = {v: k for k, v in JOB_STATUS_MAP.items()}

LEVEL_CODES = ["Intern", "Fresher", "Junior", "Middle", "Senior", "Lead", "Manager"]

WORK_TYPE_MAP = {"FULL_TIME": "Toàn thời gian", "PART_TIME": "Bán thời gian",
                  "INTERNSHIP": "Thực tập", "OTHER": "Khác"}
WORK_TYPE_MAP_REV = {v: k for k, v in WORK_TYPE_MAP.items()}

SALARY_TYPE_MAP = {"RANGE": "Khoảng lương", "EXACT": "Mức cố định", "UPTO": "Lên đến",
                    "STARTING_FROM": "Từ", "NEGOTIABLE": "Thỏa thuận", "UNPAID": "Không lương"}
SALARY_TYPE_MAP_REV = {v: k for k, v in SALARY_TYPE_MAP.items()}

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
    if not smin and not smax:
        return stype or "Thỏa thuận"
    if smin and smax:
        return f"{smin:,.0f} - {smax:,.0f} {currency} ({stype})".strip()
    return f"{(smin or smax):,.0f} {currency} ({stype})".strip()


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
        "currency": raw.get("currency") or "VNĐ",
        "benefits": parsed.get("perks") or "",
        "deadline": raw.get("deadline"),
        "jd_link": raw.get("source_url") or "",
        "date_collected": raw.get("created_at"),
        "status": JOB_STATUS_MAP.get(raw.get("job_status") or "", raw.get("job_status") or ""),
        "status_raw": raw.get("job_status") or "OPEN",
        "note": raw.get("ss_team_notes") or "",
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
    }


def _normalize_contact(raw: dict) -> dict | None:
    if raw is None:
        return None
    return {
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
    }


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

def list_jobs(q="", industry="", level="", location="", status="", limit=200, offset=0):
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
    data = _request("GET", "/jobs", params=params) or {}
    items = data.get("items", data if isinstance(data, list) else [])
    return [_normalize_job(j) for j in items]


def count_jobs(q="", industry="", level="", location="", status=""):
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
    data = _request("GET", "/jobs", params=params) or {}
    return data.get("total", 0)


def get_stats() -> dict:
    """GET /stats — tổng job, tổng công ty, tổng đơn ứng tuyển (total_applications,
    thêm 08/2026)... Chỉ cần API key, không cần access_token. Dùng cho dashboard."""
    return _request("GET", "/stats") or {}


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
        "deadline": form.get("deadline") or None,
        "ss_team_notes": (form.get("note") or "").strip() or None,
    }
    parsed = _build_parsed_content(form)
    if parsed:
        payload["parsed_content"] = parsed
    raw = _request("PATCH", f"/jobs/{job_id}", access_token=access_token, json=payload)
    return _normalize_job(raw)


def update_job_status(access_token, job_id, status_vn):
    """status_vn: nhãn tiếng Việt (vd 'Đã đóng') hoặc mã backend thẳng
    (vd 'CLOSED') — tự nhận diện qua JOB_STATUS_MAP_REV."""
    code = JOB_STATUS_MAP_REV.get(status_vn, status_vn)
    raw = _request("PATCH", f"/jobs/{job_id}", access_token=access_token, json={"job_status": code})
    return _normalize_job(raw)


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

def list_companies(q="", city="", limit=200, offset=0):
    params = {"limit": limit, "offset": offset}
    if q:
        params["keyword"] = q
    if city:
        params["province"] = city
    data = _request("GET", "/companies", params=params) or {}
    items = data.get("items", data if isinstance(data, list) else [])
    return [_normalize_company(c) for c in items]


def count_companies(q="", city=""):
    """Dùng field `total` backend trả sẵn — xem giải thích ở count_jobs().
    Nhận đúng bộ filter như list_companies() để khớp danh sách đang lọc."""
    params = {"limit": 1}
    if q:
        params["keyword"] = q
    if city:
        params["province"] = city
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
    raw = _request("PATCH", f"/companies/{company_id}", access_token=access_token, json=_company_payload(form))
    return _normalize_company(raw)


# ---------------------------------------------------------------------------
# Company contacts (người liên hệ HR) — bảng CON của company, route riêng
# ---------------------------------------------------------------------------

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
    }
    raw = _request("POST", f"/companies/{company_id}/contacts", access_token=access_token, json=payload)
    return _normalize_contact(raw)


def update_contact(access_token, company_id, contact_id, form) -> dict:
    payload = {
        "contact_name": (form.get("contact_name") or "").strip() or None,
        "job_title": (form.get("title") or "").strip() or None,
        "work_email": (form.get("email") or "").strip() or None,
        "social_link": (form.get("contact_link") or "").strip() or None,
        "phone_number": (form.get("phone") or "").strip() or None,
    }
    raw = _request("PATCH", f"/companies/{company_id}/contacts/{contact_id}", access_token=access_token, json=payload)
    return _normalize_contact(raw)


def update_contact_status(access_token, company_id, contact_id, status_vn):
    code = CONTACT_STATUS_MAP_REV.get(status_vn, status_vn)
    raw = _request(
        "PATCH", f"/companies/{company_id}/contacts/{contact_id}",
        access_token=access_token, json={"contact_status": code},
    )
    return _normalize_contact(raw)


def delete_contact(access_token, company_id, contact_id):
    """Xoá MỀM phía backend (is_active=false) — không phải xoá thật."""
    _request("DELETE", f"/companies/{company_id}/contacts/{contact_id}", access_token=access_token)


def hard_delete_contact(access_token, company_id, contact_id):
    """Xoá THẬT (mới 08/2026) — chỉ dùng làm bước 2, backend chặn 409
    nếu contact CHƯA soft-delete trước (xem thiết kế 2 bước ở lịch sử
    trao đổi), hoặc 409 nếu contact đang có job_contact_links (đã từng
    gắn với job cụ thể — xoá sẽ mất lịch sử liên hệ theo job đó).
    CrawlerAPIError từ 2 case 409 này có message đủ rõ để flash thẳng
    cho staff, không cần app.py tự diễn giải thêm."""
    _request("DELETE", f"/companies/{company_id}/contacts/{contact_id}/hard", access_token=access_token)
