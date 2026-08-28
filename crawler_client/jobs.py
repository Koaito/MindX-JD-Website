"""Domain Job — list/get/create/update JD, chuẩn hoá field backend -> field
template đang dùng."""

from .base import _request
from .data_health import count_missing_fields

# Field nào tính vào thống kê "thiếu dữ liệu" ở tab Tình trạng dữ liệu
# (blueprints/crawl_status.py) — chỉ chọn field NỘI DUNG (job content
# thật sự cần cho học viên đọc/ứng tuyển), KHÔNG đưa vào field crawl
# metadata (source, jd_link, date_collected...) hay field luôn có sẵn
# do backend set mặc định (industry/level/location/work_type — crawl
# tự gán, status luôn có OPEN/CLOSED). Có thể bớt/thêm field sau này —
# chỉ cần sửa list này, không đụng logic đếm (count_missing_fields ở
# data_health.py).
#
# "salary" ĐÃ BỎ khỏi thống kê (08/2026, xem lịch sử trao đổi) — sau khi
# fix include_content, số liệu thật cho thấy 71% job "thiếu lương" chỉ
# vì phần lớn job crawl vốn dĩ ghi "Thỏa thuận" (không có salary_min/max
# cụ thể) — đây là TRẠNG THÁI HỢP LỆ của tin tuyển dụng thật (nhiều công
# ty cố tình không công khai mức lương), không phải lỗi/thiếu dữ liệu
# cần team đi bổ sung như 5 field còn lại. Giữ nguyên predicate cũ ở
# đây (comment) phòng khi sau này cần bật lại, tách riêng khỏi nhóm
# "thiếu thật sự" thay vì xoá hẳn:
#   lambda j: not j.get("salary_min") and not j.get("salary_max")
JOB_HEALTH_FIELDS = [
    ("skills", "Kỹ năng"),
    ("requirements", "Yêu cầu công việc"),
    ("benefits", "Phúc lợi"),
    ("description", "Mô tả công việc"),
    ("deadline", "Hạn nộp"),
]


def job_field_health(jobs):
    """Đếm số job thiếu (rỗng) từng field trong JOB_HEALTH_FIELDS.

    Nhận sẵn list job đã _normalize_job() — cùng nguyên tắc
    company_field_health() (companies.py): nơi gọi (crawl_status.py) tự
    quyết định lấy job từ đâu, hàm này không tự fetch. Logic đếm thật
    sự dùng CHUNG count_missing_fields() (data_health.py) với company.
    """
    return count_missing_fields(jobs, JOB_HEALTH_FIELDS)

# ---------------------------------------------------------------------------
# Bảng ánh xạ VN <-> mã backend — form/hiển thị dùng tiếng Việt, request gửi
# lên backend dùng đúng enum backend yêu cầu.
# ---------------------------------------------------------------------------

JOB_STATUS_MAP = {"OPEN": "Đang tuyển", "CLOSED": "Đã đóng"}
JOB_STATUS_MAP_REV = {v: k for k, v in JOB_STATUS_MAP.items()}

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

def list_jobs(q="", industry="", level="", location="", status="", created_by="",
               limit=200, offset=0, include_content=False):
    """include_content (thêm 08/2026, xem lịch sử trao đổi bug "tab Tình
    trạng dữ liệu báo sai 100% job thiếu nội dung"): mặc định False,
    GIỮ NGUYÊN hành vi cũ — backend GET /jobs không trả parsed_content,
    payload nhẹ, đủ dùng cho mọi nơi chỉ cần tên/lương/company (dashboard,
    danh sách job, staff-activity...). Truyền True CHỈ khi thật sự cần
    đọc skills/requirements/benefits/description ngay ở list (hiện chỉ
    crawl_status.py dùng, xem job_field_health()) — backend SELECT thêm
    cột parsed_content (JSONB dài) khi param này = true, xem
    api/routers/jobs.py::list_jobs() bên scrap-jd-api."""
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
    if include_content:
        params["include_content"] = "true"
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
# GET /companies (xem _MAX_COMPANIES_PAGE ở companies.py) — gọi
# list_jobs(limit=1000) thẳng sẽ bị 422 "Input should be less than or
# equal to 200". Dùng hàm này ở bất kỳ đâu cần TOÀN BỘ job một lần (vd
# tính thống kê trên dashboard theo tháng — cần biết deadline/
# date_collected của từng job, không phải chỉ 1 con số total) thay vì
# bịa 1 con số limit lớn hơn 200.
_MAX_JOBS_PAGE = 200
_ALL_JOBS_SAFETY_CAP = 5000  # chặn vòng lặp vô hạn nếu backend trả total sai


def list_all_jobs(q="", industry="", level="", location="", status="", created_by="",
                   include_content=False):
    """Lấy TOÀN BỘ job khớp filter bằng cách tự phân trang theo đúng
    limit tối đa backend cho phép (200/lần), gộp lại thành 1 list — dùng
    khi cần dữ liệu chi tiết (không chỉ đếm) của mọi job, ví dụ nhóm job
    theo tháng deadline/date_collected cho dashboard, hoặc "mọi job 1
    staff đã tự nhập tay" cho trang /staff-activity (created_by=uid).

    include_content: mặc định False — hầu hết nơi gọi hàm này (dashboard,
    companies, staff-activity) không cần skills/requirements/benefits/
    description, chỉ truyền True ở nơi THẬT SỰ cần đọc nội dung JD ngay
    lúc list (hiện chỉ crawl_status.py, xem list_jobs() ở trên và
    job_field_health()) — tránh kéo parsed_content (JSONB dài) không
    cần thiết cho các nơi khác, dù giờ backend đã hỗ trợ."""
    total = count_jobs(q=q, industry=industry, level=level, location=location,
                        status=status, created_by=created_by)
    all_items: list = []
    offset = 0
    while offset < total and offset < _ALL_JOBS_SAFETY_CAP:
        page = list_jobs(q=q, industry=industry, level=level, location=location,
                          status=status, created_by=created_by, limit=_MAX_JOBS_PAGE,
                          offset=offset, include_content=include_content)
        if not page:
            break
        all_items.extend(page)
        offset += _MAX_JOBS_PAGE
    return all_items


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
        # docstring base.py, mục "AUDIT LOG NOTE").
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
