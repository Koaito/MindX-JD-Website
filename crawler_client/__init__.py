"""
Client gọi API backend "Scrap JD" (repo Koaito/scrap-jd, deploy trên Render)
để đọc/ghi Job, Company, Company Contact — THAY THẾ hoàn toàn cho data.py cũ
(vốn gọi Supabase).

LỊCH SỬ: trước đây là 1 file crawler_client.py duy nhất (1420 dòng, ~50
hàm, "God module" thứ 2 sau db.py bên backend — trộn job/company/contact/
audit_log/import-export/enum). Đã tách theo domain (xem từng file con:
base.py, enums.py, stats.py, jobs.py, companies.py, contacts.py,
audit_logs.py, import_export.py) để dễ tìm, dễ sửa, giảm conflict khi
nhiều người cùng sửa. File này CHỈ re-export lại toàn bộ tên cũ (kể cả
biến/hằng module-level như _enums_cache, _LEVEL_CODES_FALLBACK, các
*_MAP/*_MAP_REV) để KHÔNG phải sửa bất kỳ chỗ nào đang
`import crawler_client as db_data` rồi gọi `db_data.xxx` ở nơi khác
trong repo — API bên ngoài giữ nguyên 100%, chỉ tổ chức lại bên trong.

⚠️ LƯU Ý CHO TEST: test nội bộ package này (tests/test_crawler_client.py)
patch trực tiếp `crawler_client.enums._request` / `crawler_client.enums.
get_enums` (KHÔNG phải `crawler_client._request`/`crawler_client.
get_enums` ở re-export dưới đây) — vì get_level_codes() gọi get_enums(),
và get_enums() gọi _request() bằng tên cục bộ NGAY TRONG enums.py, không
đi qua package __init__ này ở call time. Patch tại re-export chỉ có tác
dụng cho code NGOÀI package gọi `crawler_client.get_enums(...)` qua
package attribute (vd blueprints/*.py qua `db_data.get_level_codes()`),
không ảnh hưởng lời gọi NỘI BỘ giữa 2 hàm cùng nằm trong enums.py.
"""

from .base import CrawlerAPIError, CRAWLER_API_KEY, CRAWLER_API_URL, REQUEST_TIMEOUT, _headers, _request
from .enums import (
    _ENUMS_CACHE_TTL_SECONDS,
    _LEVEL_CODES_FALLBACK,
    _enums_cache,
    get_enums,
    get_level_codes,
)
from .stats import get_stats, get_engagement_stats
from .jobs import (
    JOB_STATUS_MAP,
    JOB_STATUS_MAP_REV,
    WORK_TYPE_MAP,
    WORK_TYPE_MAP_REV,
    SALARY_TYPE_MAP,
    SALARY_TYPE_MAP_REV,
    SALARY_PERIOD_MAP,
    SALARY_PERIOD_MAP_REV,
    _to_int,
    _fmt_salary,
    _normalize_job,
    _build_parsed_content,
    _MAX_JOBS_PAGE,
    _ALL_JOBS_SAFETY_CAP,
    list_jobs,
    count_jobs,
    list_all_jobs,
    is_duplicate_candidate,
    get_job,
    create_job,
    update_job,
    update_job_status,
)
from .companies import (
    PARTNERSHIP_POTENTIAL_MAP,
    PARTNERSHIP_POTENTIAL_MAP_REV,
    _normalize_company,
    _company_payload,
    _MAX_COMPANIES_PAGE,
    _ALL_COMPANIES_SAFETY_CAP,
    list_companies,
    list_all_companies,
    count_companies,
    list_company_cities,
    get_company,
    create_company,
    update_company,
    delete_company,
)
from .contacts import (
    CONTACT_STATUS_MAP,
    CONTACT_STATUS_MAP_REV,
    _normalize_contact,
    list_all_contacts,
    list_contacts,
    get_contact,
    create_contact,
    update_contact,
    update_contact_status,
    assign_contact,
    delete_contact,
    hard_delete_contact,
)
from .audit_logs import (
    ACTION_TYPE_MAP,
    ENTITY_TYPE_MAP,
    _normalize_audit_log,
    list_audit_logs,
    update_audit_log_note,
)
from .crawl import (
    CRAWL_STAT_LABELS,
    CRAWL_STATUS_LABELS,
    CRAWL_STATUS_BADGE,
    _normalize_crawl_run,
    get_sources,
    trigger_crawl,
    get_crawl_status,
    list_crawl_runs,
    get_crawl_logs,
)
from .import_export import (
    IMPORT_EXPORT_ENTITY_TYPES,
    IMPORT_EXPORT_ENTITY_LABELS,
    CONFLICT_STATUS_LABELS,
    export_entity,
    export_preview,
    _normalize_preview_row,
    _normalize_preview_summary,
    _format_import_errors_detail,
    import_preview,
    get_import_preview,
    get_company_suggestions,
    verify_field,
    resolve_company,
    import_confirm,
)

__all__ = [
    "CrawlerAPIError",
    "CRAWLER_API_KEY",
    "CRAWLER_API_URL",
    "REQUEST_TIMEOUT",
    "get_enums",
    "get_level_codes",
    "get_stats",
    "get_engagement_stats",
    "JOB_STATUS_MAP",
    "JOB_STATUS_MAP_REV",
    "WORK_TYPE_MAP",
    "WORK_TYPE_MAP_REV",
    "SALARY_TYPE_MAP",
    "SALARY_TYPE_MAP_REV",
    "SALARY_PERIOD_MAP",
    "SALARY_PERIOD_MAP_REV",
    "list_jobs",
    "count_jobs",
    "list_all_jobs",
    "is_duplicate_candidate",
    "get_job",
    "create_job",
    "update_job",
    "update_job_status",
    "PARTNERSHIP_POTENTIAL_MAP",
    "PARTNERSHIP_POTENTIAL_MAP_REV",
    "list_companies",
    "list_all_companies",
    "count_companies",
    "list_company_cities",
    "get_company",
    "create_company",
    "update_company",
    "delete_company",
    "CONTACT_STATUS_MAP",
    "CONTACT_STATUS_MAP_REV",
    "list_all_contacts",
    "list_contacts",
    "get_contact",
    "create_contact",
    "update_contact",
    "update_contact_status",
    "assign_contact",
    "delete_contact",
    "hard_delete_contact",
    "ACTION_TYPE_MAP",
    "ENTITY_TYPE_MAP",
    "list_audit_logs",
    "update_audit_log_note",
    "CRAWL_STAT_LABELS",
    "CRAWL_STATUS_LABELS",
    "CRAWL_STATUS_BADGE",
    "get_sources",
    "trigger_crawl",
    "get_crawl_status",
    "list_crawl_runs",
    "get_crawl_logs",
    "IMPORT_EXPORT_ENTITY_TYPES",
    "IMPORT_EXPORT_ENTITY_LABELS",
    "CONFLICT_STATUS_LABELS",
    "export_entity",
    "export_preview",
    "import_preview",
    "get_import_preview",
    "get_company_suggestions",
    "verify_field",
    "resolve_company",
    "import_confirm",
]
