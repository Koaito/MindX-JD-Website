"""Dashboard blueprint - team SS homepage with insights"""

from datetime import date, datetime
from flask import Blueprint, render_template, flash, request

import crawler_client as db_data
from crawler_client import CrawlerAPIError
import backend_auth
from backend_auth import BackendAuthError
from utils.decorators import staff_required
from constants import INDUSTRIES, JOB_STATUSES
from helpers import _auth_tokens_from_session, _parse_any_date, _jobs_by_month

dashboard_bp = Blueprint("dashboard", __name__)


# Dashboard helper functions (đặc thù riêng cho dashboard — không dùng ở
# blueprint nào khác nên vẫn để tại đây, không đưa vào helpers.py chung)
def _merge_engagement_into_jobs(jobs, engagement_jobs):
    by_id = {e.get("job_id"): e for e in engagement_jobs or []}
    for job in jobs:
        eng = by_id.get(job.get("id"))
        job["application_count"] = eng.get("application_count") if eng else None
        job["saved_count"] = eng.get("saved_count") if eng else None


def _jd_needing_push(jobs, days_min=7, days_max=14):
    today = datetime.now().date()
    result = []
    for job in jobs:
        if job.get("status_raw") != "OPEN":
            continue
        if job.get("application_count") is None:
            continue
        if job["application_count"] or job["saved_count"]:
            continue
        d = _parse_any_date(job.get("deadline"))
        if d is None:
            continue
        days_left = (d - today).days
        if days_min <= days_left <= days_max:
            result.append({**job, "days_left": days_left})
    result.sort(key=lambda j: j["days_left"])
    return result


def _jd_stale(jobs, min_age_days=30):
    today = datetime.now().date()
    result = []
    for job in jobs:
        if job.get("status_raw") != "OPEN":
            continue
        if job.get("application_count") is None:
            continue
        if job["application_count"] or job["saved_count"]:
            continue
        d = _parse_any_date(job.get("date_collected"))
        if d is None:
            continue
        age_days = (today - d).days
        if age_days >= min_age_days:
            result.append({**job, "age_days": age_days})
    result.sort(key=lambda j: -j["age_days"])
    return result


def _top_skills(jobs, days_recent=30, top_n=10):
    today = datetime.now().date()
    counts = {}
    for job in jobs:
        d = _parse_any_date(job.get("date_collected"))
        if d is None or (today - d).days > days_recent:
            continue
        for raw_skill in (job.get("skills") or "").split(","):
            skill = raw_skill.strip()
            if skill:
                counts[skill] = counts.get(skill, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:top_n]


def _salary_ranges_by_industry_level(jobs):
    groups = {}
    for job in jobs:
        if (job.get("currency") or "VNĐ") != "VNĐ":
            continue
        if (job.get("salary_period_raw") or "MONTH") != "MONTH":
            continue
        lo, hi = job.get("salary_min"), job.get("salary_max")
        if not lo and not hi:
            continue
        key = (job.get("industry") or "Khác", job.get("level") or "Khác")
        g = groups.setdefault(key, {"mins": [], "maxs": []})
        if lo:
            g["mins"].append(lo)
        if hi:
            g["maxs"].append(hi)
    rows = []
    for (industry, level), vals in groups.items():
        avg_min = sum(vals["mins"]) / len(vals["mins"]) if vals["mins"] else None
        avg_max = sum(vals["maxs"]) / len(vals["maxs"]) if vals["maxs"] else None
        rows.append({
            "industry": industry, "level": level,
            "avg_min": avg_min, "avg_max": avg_max,
            "sample_size": len(vals["mins"]) or len(vals["maxs"]),
        })
    rows.sort(key=lambda r: -(r["avg_max"] or r["avg_min"] or 0))
    for r in rows:
        r["avg_min_fmt"] = f"{r['avg_min']:,.0f}" if r["avg_min"] else None
        r["avg_max_fmt"] = f"{r['avg_max']:,.0f}" if r["avg_max"] else None
    return rows


def _companies_high_potential_no_contact(companies, contacts, quiet_days=60):
    today = datetime.now().date()
    contacts_by_company = {}
    for ct in contacts:
        contacts_by_company.setdefault(ct.get("company_id"), []).append(ct)

    result = []
    for c in companies:
        if c.get("partnership_potential") != "Cao":
            continue
        company_contacts = contacts_by_company.get(c.get("id"), [])
        if not company_contacts:
            result.append({**c, "reason": "Chưa có contact nào", "last_contacted": None})
            continue
        last_dates = [_parse_any_date(ct.get("last_contacted")) for ct in company_contacts]
        if any(d is not None and (today - d).days < quiet_days for d in last_dates):
            continue
        most_recent = max((d for d in last_dates if d), default=None)
        result.append({
            **c,
            "reason": "Contact đã nguội" if most_recent else "Có contact nhưng chưa từng liên hệ",
            "last_contacted": most_recent,
        })
    result.sort(key=lambda c: c["last_contacted"] or date.min)
    return result


# Lựa chọn số ngày hợp lệ cho ô chọn trên dashboard (thêm 08/2026) — cố
# định 1 danh sách nhỏ thay vì cho nhập số tự do, tránh staff gõ giá trị
# vô lý (0, âm, quá lớn) làm bảng rỗng/vô nghĩa. 14 là mặc định đã chốt.
FOLLOWUP_DAYS_OPTIONS = [7, 14, 30]
FOLLOWUP_DAYS_DEFAULT = 14


def _followup_days_arg():
    """Đọc ?followup_days=N từ query string, chỉ chấp nhận giá trị nằm
    trong FOLLOWUP_DAYS_OPTIONS — giá trị lạ/thiếu thì fallback về mặc
    định thay vì lỗi 500 hoặc chấp nhận số bất kỳ."""
    try:
        value = int(request.args.get("followup_days", FOLLOWUP_DAYS_DEFAULT))
    except (TypeError, ValueError):
        return FOLLOWUP_DAYS_DEFAULT
    return value if value in FOLLOWUP_DAYS_OPTIONS else FOLLOWUP_DAYS_DEFAULT


def _contacts_needing_followup(contacts, quiet_days=14):
    """Contact "đang mở" (chưa IN_PARTNERSHIP) mà im lặng ≥ quiet_days —
    tính từ last_contacted, hoặc date_collected nếu CHƯA từng liên hệ lần
    nào (last_contacted rỗng). Không phân biệt UNCONTACTED/EMAIL_SENT/
    RESPONDED — coi mọi trạng thái chưa chốt hợp tác là "còn cần đẩy tiếp"
    (thống nhất 08/2026, xem thảo luận #3 — khác _companies_high_potential_
    no_contact() ở trên vốn chỉ xét công ty Cao và ngưỡng 60 ngày).

    Tính on-the-fly mỗi lần load dashboard, giống các hàm _jd_*/_companies_*
    khác trong file này — không lưu thêm cột DB nào, không cần migration.
    contact chưa từng có date_collected lẫn last_contacted (dữ liệu thiếu)
    thì bỏ qua, không tính là quá hạn để tránh báo nhầm hàng loạt.
    """
    today = datetime.now().date()
    result = []
    for c in contacts:
        if (c.get("status_raw") or "") == "IN_PARTNERSHIP":
            continue
        if not c.get("is_active", True):
            continue
        last = _parse_any_date(c.get("last_contacted")) or _parse_any_date(c.get("date_collected"))
        if last is None:
            continue
        quiet_for = (today - last).days
        if quiet_for >= quiet_days:
            result.append({**c, "quiet_days": quiet_for, "last_contacted_date": last,
                            "never_contacted": not c.get("last_contacted")})
    result.sort(key=lambda c: -c["quiet_days"])
    return result


def _companies_job_activity(jobs, companies, expanding_days=30, expanding_min_jobs=2, quiet_days=75):
    today = datetime.now().date()
    jobs_by_company = {}
    for j in jobs:
        d = _parse_any_date(j.get("date_collected"))
        if d is None or not j.get("company_id"):
            continue
        jobs_by_company.setdefault(j["company_id"], []).append(d)

    companies_idx = {c["id"]: c for c in companies}
    expanding, quiet = [], []
    for company_id, dates in jobs_by_company.items():
        company = companies_idx.get(company_id)
        if not company:
            continue
        recent_count = sum(1 for d in dates if (today - d).days <= expanding_days)
        if recent_count >= expanding_min_jobs:
            expanding.append({**company, "recent_job_count": recent_count})
        latest = max(dates)
        quiet_for = (today - latest).days
        if quiet_for >= quiet_days:
            quiet.append({**company, "quiet_days": quiet_for, "last_job_date": latest})

    expanding.sort(key=lambda c: -c["recent_job_count"])
    quiet.sort(key=lambda c: -c["quiet_days"])
    return expanding, quiet


def _pct_change(current, previous):
    if not previous:
        return None
    return round((current - previous) / previous * 100)


def _monthly_recap(jobs, companies, engagement_monthly):
    today = datetime.now().date()
    this_y, this_m = today.year, today.month
    last_y, last_m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)

    def _in_month(raw_date, y, m):
        d = _parse_any_date(raw_date)
        return d is not None and d.year == y and d.month == m

    jobs_this_month = [j for j in jobs if _in_month(j.get("date_collected"), this_y, this_m)]
    jobs_last_month = [j for j in jobs if _in_month(j.get("date_collected"), last_y, last_m)]
    jobs_expired_this_month = [
        j for j in jobs
        if _in_month(j.get("deadline"), this_y, this_m) and _parse_any_date(j.get("deadline")) < today
    ]
    companies_this_month = [c for c in companies if _in_month(c.get("date_collected"), this_y, this_m)]
    companies_last_month = [c for c in companies if _in_month(c.get("date_collected"), last_y, last_m)]

    industry_this = {}
    for j in jobs_this_month:
        ind = j.get("industry") or "Khác"
        industry_this[ind] = industry_this.get(ind, 0) + 1
    industry_last = {}
    for j in jobs_last_month:
        ind = j.get("industry") or "Khác"
        industry_last[ind] = industry_last.get(ind, 0) + 1
    top_industries = [
        {"industry": ind, "count": cnt, "pct_change": _pct_change(cnt, industry_last.get(ind, 0))}
        for ind, cnt in sorted(industry_this.items(), key=lambda kv: -kv[1])[:3]
    ]

    company_job_count = {}
    for j in jobs_this_month:
        cid = j.get("company_id")
        if cid:
            company_job_count[cid] = company_job_count.get(cid, 0) + 1
    companies_idx = {c["id"]: c for c in companies}
    top_companies = [
        {"company": companies_idx.get(cid, {}).get("company", "—"), "company_id": cid, "count": cnt}
        for cid, cnt in sorted(company_job_count.items(), key=lambda kv: -kv[1])[:5]
    ]

    monthly = engagement_monthly or {}
    applications = monthly.get("applications") or {}
    saved_jobs = monthly.get("saved_jobs") or {}

    return {
        "jobs_new": len(jobs_this_month),
        "jobs_new_pct": _pct_change(len(jobs_this_month), len(jobs_last_month)),
        "jobs_expired": len(jobs_expired_this_month),
        "companies_new": len(companies_this_month),
        "companies_new_pct": _pct_change(len(companies_this_month), len(companies_last_month)),
        "top_industries": top_industries,
        "top_companies": top_companies,
        "applications_this_month": applications.get("this_month", 0),
        "applications_pct": _pct_change(applications.get("this_month", 0), applications.get("last_month", 0)),
        "saved_jobs_this_month": saved_jobs.get("this_month", 0),
        "saved_jobs_pct": _pct_change(saved_jobs.get("this_month", 0), saved_jobs.get("last_month", 0)),
    }


@dashboard_bp.route("/dashboard")
@staff_required
def index():
    try:
        jobs = db_data.list_all_jobs()
        companies = db_data.list_all_companies()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        jobs, companies = [], []

    jobs_by_industry = {ind: sum(1 for j in jobs if j["industry"] == ind) for ind in INDUSTRIES}
    # gọi trực tiếp get_level_codes() (không dùng LEVELS tĩnh từ constants)
    # để mỗi request đều lấy đúng danh sách level_code mới nhất trong cache
    # TTL 5 phút — nếu backend đổi enum, dashboard nhận được trong tối đa
    # 5 phút mà không cần restart server.
    jobs_by_level = {lv: sum(1 for j in jobs if j["level"] == lv) for lv in db_data.get_level_codes()}
    jobs_by_status = {st: sum(1 for j in jobs if j["status"] == st) for st in JOB_STATUSES}
    jobs_by_location = {}
    for j in jobs:
        jobs_by_location[j["location"]] = jobs_by_location.get(j["location"], 0) + 1

    monthly_labels, monthly_new = _jobs_by_month(jobs, "date_collected", months_back=6)
    _, monthly_expired = _jobs_by_month(jobs, "deadline", months_back=6, only_past=True)

    companies_by_city = {}
    for c in companies:
        companies_by_city[c["city"]] = companies_by_city.get(c["city"], 0) + 1

    total_students = None
    access_token, _ = _auth_tokens_from_session()
    if access_token:
        try:
            users = backend_auth.list_users(access_token)
            total_students = sum(1 for u in users if u.get("role") == "user")
        except BackendAuthError:
            pass
    
    total_applications = None
    total_saved_jobs = None
    try:
        stats = db_data.get_stats()
        total_applications = stats.get("total_applications")
        total_saved_jobs = stats.get("total_saved_jobs")
    except CrawlerAPIError:
        pass

    try:
        engagement = db_data.get_engagement_stats()
    except CrawlerAPIError:
        engagement = {}
    _merge_engagement_into_jobs(jobs, engagement.get("jobs", []))

    try:
        all_contacts = db_data.list_all_contacts(access_token) if access_token else []
    except CrawlerAPIError:
        all_contacts = []

    jd_needing_push = _jd_needing_push(jobs)
    jd_stale = _jd_stale(jobs)
    top_skills = _top_skills(jobs)
    salary_ranges = _salary_ranges_by_industry_level(jobs)

    companies_no_contact = _companies_high_potential_no_contact(companies, all_contacts)
    followup_days = _followup_days_arg()
    contacts_needing_followup = _contacts_needing_followup(all_contacts, quiet_days=followup_days)
    companies_expanding, companies_quiet = _companies_job_activity(jobs, companies)

    monthly_recap = _monthly_recap(jobs, companies, engagement.get("monthly"))

    return render_template(
        "dashboard.html",
        total_jobs=len(jobs), total_contacts=len(companies),
        total_students=total_students, total_applications=total_applications,
        total_saved_jobs=total_saved_jobs,
        jobs_by_industry=jobs_by_industry, jobs_by_level=jobs_by_level,
        jobs_by_status=jobs_by_status, jobs_by_location=jobs_by_location,
        contacts_by_city=companies_by_city,
        monthly_labels=monthly_labels,
        monthly_new=monthly_new,
        monthly_expired=monthly_expired,
        jd_needing_push=jd_needing_push,
        jd_stale=jd_stale,
        top_skills=top_skills,
        salary_ranges=salary_ranges,
        companies_no_contact=companies_no_contact,
        contacts_needing_followup=contacts_needing_followup,
        followup_days=followup_days,
        followup_days_options=FOLLOWUP_DAYS_OPTIONS,
        companies_expanding=companies_expanding,
        companies_quiet=companies_quiet,
        recap=monthly_recap,
    )
