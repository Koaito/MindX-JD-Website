"""
Lõi HTTP dùng chung cho mọi domain trong package crawler_client/ — nói
chuyện trực tiếp với API backend "Scrap JD" (repo Koaito/scrap-jd, deploy
trên Render). Mọi file domain khác (jobs.py, companies.py, contacts.py,
audit_logs.py, import_export.py, enums.py, stats.py) import _request/
_headers/CrawlerAPIError từ đây, KHÔNG tự gọi requests trực tiếp (trừ 2
chỗ có lý do rõ ràng cần đọc response nhị phân/đa dạng hơn dict JSON —
export_entity() và import_preview() trong import_export.py — 2 hàm đó tự
`import requests` riêng và dùng lại CRAWLER_API_URL/_headers/REQUEST_TIMEOUT
từ module này).

LỊCH SỬ: trước đây toàn bộ 1420 dòng ở đây nằm chung 1 file crawler_client.py
duy nhất, trộn 6 domain không liên quan (job, company, contact, audit_log,
import/export, enum) — "God module" thứ 2 sau db.py bên backend, cùng 1
loại rủi ro: sửa 1 domain phải kéo cả file vào context, khó tìm hàm giữa
~50 cái cùng tên kiểu create_x/update_x. Tách theo domain (mirror đúng
cách đã tách db/ bên backend) để dễ tìm, dễ sửa, giảm conflict khi nhiều
người cùng sửa.

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
    xem delete_company() ở companies.py), KHÔNG xoá thật, và BẮT BUỘC kèm
    note giải thích lý do (audit log, xem khối comment "AUDIT LOG NOTE"
    ở jobs.py/companies.py/contacts.py).
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
nhận thêm 1 tham số `note` — nội dung ghi vào audit_logs.note,
KHÔNG PHẢI ss_team_notes (note nội bộ hiển thị ngay trên JD, đã có sẵn
từ trước, field backend riêng `ss_team_notes`). Vì 2 khái niệm dễ nhầm
tên, form HTML dùng tên input RIÊNG `activity_note` cho note audit log
(khác `note` cũ vẫn giữ nguyên cho ss_team_notes) — xem app.py đọc
`request.form.get("activity_note")` khi gọi các hàm liên quan.

note BẮT BUỘC (backend trả 422 nếu thiếu, xem CompanyDeleteRequest/
ContactDeleteRequest/CompanyContactUpdate/ContactAssignUpdate ở
api/schemas.py backend) cho: xoá company, sửa contact, xoá contact,
gán contact. TUỲ CHỌN (None hợp lệ) cho: sửa/xoá JD, sửa company, tạo
contact.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

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
