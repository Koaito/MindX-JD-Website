"""
Client gọi hệ đăng nhập TỪNG NGƯỜI (JWT + refresh token) của backend
scrap-jd. Từ bản này (08/2026), đây là NƠI DUY NHẤT để xác thực người
dùng của web mindx-jobs — cả học viên lẫn team SS đều đăng nhập qua
đây, KHÔNG còn Supabase Auth nữa (xem lịch sử trao đổi: bỏ Supabase vì
lo ngại bảo mật khi phải giữ service_role key ở phía Flask).

Bảng ss_team_members phía backend giờ chứa MỌI tài khoản (không riêng
team SS như tên bảng gợi ý) — 3 role user < ss_team < admin, trong đó
'user' chính là học viên. Tên bảng sẽ được backend đổi lại sau, không
ảnh hưởng gì tới cách gọi API ở module này.

Dùng CHUNG 2 biến môi trường với crawler_client.py (cùng 1 backend):
  CRAWLER_API_URL — URL backend đã deploy (Render).
  CRAWLER_API_KEY — X-API-Key bắt buộc cho MỌI request tới backend, kể
                     cả 3 route public (register/verify-email/resend-
                     verification) — gửi kèm không hại gì dù backend
                     không bắt buộc ở 3 route đó, cho đơn giản code.

Mọi hàm ở đây raise BackendAuthError khi có lỗi — message đã ở dạng
tiếng Việt, sẵn sàng flash cho user.
"""

import os

import requests

CRAWLER_API_URL = os.environ.get("CRAWLER_API_URL", "https://scrap-jd-api.onrender.com").rstrip("/")
CRAWLER_API_KEY = os.environ.get("CRAWLER_API_KEY")

REQUEST_TIMEOUT = 20  # giây — Render free tier có thể "ngủ", lần gọi đầu có thể chậm


class BackendAuthError(Exception):
    """Lỗi khi gọi hệ JWT của backend — message tiếng Việt để flash cho user.

    wrong_credentials=True CHỈ set khi /auth/login trả 401 (sai email
    hoặc mật khẩu) — dùng để phân biệt với các lỗi 401 khác (access
    token hết hạn khi gọi route cần đăng nhập) mà KHÔNG nên hiển thị
    cùng 1 message "sai email/mật khẩu" gây hiểu nhầm.
    """

    def __init__(self, message: str, status_code: int | None = None, wrong_credentials: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.wrong_credentials = wrong_credentials

    @property
    def email_not_verified(self) -> bool:
        """True nếu lỗi này là do tài khoản chưa bấm link xác thực email
        (login() backend trả 403 kèm câu này) — app.py dùng để hiện nút
        'Gửi lại email xác thực' thay vì chỉ báo lỗi suông."""
        return self.status_code == 403 and "xác thực" in str(self).lower()


def _headers(access_token: str | None = None) -> dict:
    if not CRAWLER_API_KEY:
        raise BackendAuthError(
            "Server chưa cấu hình CRAWLER_API_KEY (biến môi trường trong .env) "
            "nên không thể gọi backend."
        )
    headers = {"X-API-Key": CRAWLER_API_KEY}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _request(method: str, path: str, access_token: str | None = None, **kwargs):
    url = f"{CRAWLER_API_URL}{path}"
    try:
        res = requests.request(
            method, url, headers=_headers(access_token), timeout=REQUEST_TIMEOUT, **kwargs
        )
    except requests.exceptions.RequestException as exc:
        raise BackendAuthError(f"Không kết nối được tới backend ({url}): {exc}") from exc

    if res.status_code in (200, 201, 204):
        return {} if not res.content else res.json()

    # Cố lấy field "detail" (FastAPI trả lỗi dạng {"detail": "..."})
    try:
        detail = res.json().get("detail", "") or ""
    except Exception:
        detail = res.text[:300]

    if res.status_code == 401 and path == "/auth/login":
        raise BackendAuthError(detail or "Email hoặc mật khẩu không đúng.", status_code=401, wrong_credentials=True)

    if res.status_code == 401:
        raise BackendAuthError(
            detail or "Phiên đăng nhập backend đã hết hạn — vui lòng đăng nhập lại.",
            status_code=401,
        )
    if res.status_code == 403:
        raise BackendAuthError(detail or "Tài khoản không có quyền hoặc đã bị khoá.", status_code=403)
    if res.status_code == 404:
        raise BackendAuthError(detail or "Không tìm thấy.", status_code=404)

    raise BackendAuthError(
        f"Backend lỗi {res.status_code} khi {method} {path}: {detail}", status_code=res.status_code
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login(email: str, password: str) -> dict:
    """POST /auth/login. Trả {access_token, refresh_token, must_change_password}."""
    return _request("POST", "/auth/login", json={"email": email, "password": password})


def refresh(refresh_token: str) -> dict:
    """POST /auth/refresh — xoay vòng, trả CẶP token mới (access + refresh)."""
    return _request("POST", "/auth/refresh", json={"refresh_token": refresh_token})


def get_me(access_token: str) -> dict:
    """GET /auth/me — thông tin user hiện tại (full_name, email, role, must_change_password...)."""
    return _request("GET", "/auth/me", access_token=access_token)


def update_profile(access_token: str, full_name: str, phone: str | None = None,
                    track: str | None = None) -> dict:
    """PATCH /auth/me (thêm 08/2026, xem trang cá nhân — blueprints/profile.py).
    Tự sửa full_name/phone/track của CHÍNH tài khoản đang đăng nhập.

    KHÁC change_password() ngay bên dưới (route riêng, không đụng mật
    khẩu) và KHÁC mọi hàm admin sửa user khác (crawler_client/*.py,
    dùng access token của ADMIN gọi PATCH /auth/users/{id}/...) — hàm
    này CHỈ sửa được đúng user đang cầm access_token, không nhận
    ss_user_id vì route backend tự suy ra "chính mình" từ JWT.

    phone/track backend sẽ tự ép về None nếu tài khoản là staff (xem
    docstring route PATCH /auth/me phía backend) — truyền lên vô hại
    với staff, chỉ đơn giản bị bỏ qua."""
    payload = {"full_name": full_name, "phone": phone, "track": track}
    return _request("PATCH", "/auth/me", access_token=access_token, json=payload)


def change_password(access_token: str, new_password: str, old_password: str | None = None) -> dict:
    """POST /auth/change-password. old_password có thể bỏ trống nếu tài
    khoản đang must_change_password=True (mật khẩu tạm admin cấp)."""
    payload = {"new_password": new_password}
    if old_password:
        payload["old_password"] = old_password
    return _request("POST", "/auth/change-password", access_token=access_token, json=payload)


def logout(refresh_token: str) -> None:
    """POST /auth/logout — thu hồi refresh token phía backend. Không raise
    nếu lỗi (đăng xuất luôn coi là thành công phía frontend, tránh kẹt
    user không thoát được session vì backend tạm lỗi)."""
    try:
        _request("POST", "/auth/logout", json={"refresh_token": refresh_token})
    except BackendAuthError:
        pass


def list_users(access_token: str) -> list:
    """GET /auth/users (đòi role ss_team trở lên) — danh sách MỌI tài
    khoản (cả role='user'=học viên lẫn ss_team/admin). Dùng cho: đếm số
    học viên ở dashboard, tra thông tin học viên đã ứng tuyển 1 job."""
    return _request("GET", "/auth/users", access_token=access_token)


def create_user(access_token: str, full_name: str, email: str, role: str = "ss_team") -> dict:
    """POST /auth/users (CHỈ admin gọi được, backend tự chặn 403 nếu
    không phải admin). Mật khẩu TẠM do backend tự sinh, trả về ĐÚNG 1
    LẦN trong response này ở field temp_password — không có cách nào
    lấy lại sau, phải admin tự đưa cho người dùng ngay lúc này."""
    return _request(
        "POST", "/auth/users", access_token=access_token,
        json={"full_name": full_name, "email": email, "role": role},
    )


def update_user_role(access_token: str, ss_user_id: str, role: str) -> dict:
    """PATCH /auth/users/{id}/role (CHỈ admin gọi được). Backend tự chặn
    admin tự đổi role chính mình (400) — không cần lặp lại check này ở
    đây, chỉ cần flash thẳng message backend trả về nếu có."""
    return _request(
        "PATCH", f"/auth/users/{ss_user_id}/role", access_token=access_token,
        json={"role": role},
    )


def update_user_active_status(access_token: str, ss_user_id: str, is_active: bool) -> dict:
    """PATCH /auth/users/{id}/active-status (CHỈ admin gọi được). Khoá
    VĨNH VIỄN 1 tài khoản (is_active=false) — KHÁC khoá tạm thời do sai
    mật khẩu (locked_until, tự hết hạn). Backend tự chặn admin tự khoá
    chính mình (400), không cần lặp lại check này ở đây."""
    return _request(
        "PATCH", f"/auth/users/{ss_user_id}/active-status", access_token=access_token,
        json={"is_active": is_active},
    )


# ---------------------------------------------------------------------------
# /me/... — ứng tuyển & lưu job của CHÍNH học viên đang đăng nhập
# + GET /jobs/{id}/applications, GET /jobs/{id}/saved-jobs (staff xem ai
#   đã ứng tuyển/lưu 1 job — chiều "1 job có ai")
# + GET /auth/users/{id}/applications, GET /auth/users/{id}/saved-jobs
#   (staff xem 1 học viên đã ứng tuyển/lưu job nào — chiều ngược lại,
#   "1 học viên có gì", thêm 08/2026 cho trang /student-activity)
#
# Đặt ở ĐÂY (không phải crawler_client.py) vì mọi route này đều bắt buộc
# Authorization: Bearer <access_token> — crawler_client.py hiện chỉ gửi
# X-API-Key, không gửi JWT (crawler_client.py thuộc phạm vi việc khác
# đang sửa job/company/contact, không đụng vào để tránh xung đột khi
# merge). ss_user_id KHÔNG cần truyền cho /me/* — backend tự lấy từ
# chính JWT; CÓ truyền cho 2 route staff-only cuối (staff xem NGƯỜI
# KHÁC, không phải chính mình).
# ---------------------------------------------------------------------------

def apply_to_job(access_token: str, job_id: str, note: str = "",
                 cv_file_bytes: bytes = None, cv_filename: str = "cv.pdf") -> dict:
    """POST /me/applications với multipart/form-data để upload CV.
    Backend tự chặn nếu job không ở trạng thái OPEN (400) hoặc đã
    ứng tuyển rồi (409). CV file bắt buộc (PDF, max 5MB)."""
    url = f"{CRAWLER_API_URL}/me/applications"
    headers = _headers(access_token)
    headers.pop("Content-Type", None)  # Để requests tự sinh boundary cho multipart

    data = {"job_id": job_id}
    if note:
        data["note"] = note

    files = {
        "cv_file": (cv_filename, cv_file_bytes, "application/pdf"),
    }

    try:
        res = requests.post(url, headers=headers, data=data, files=files, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        raise BackendAuthError(f"Không kết nối được tới backend: {exc}") from exc

    if res.status_code in (200, 201):
        return res.json()

    try:
        detail = res.json().get("detail", "")
    except Exception:
        detail = res.text[:300]

    if res.status_code == 409:
        raise BackendAuthError("Bạn đã ứng tuyển job này rồi.", status_code=409)

    raise BackendAuthError(detail or f"Lỗi khi nộp hồ sơ ({res.status_code})", status_code=res.status_code)


def list_my_applications(access_token: str) -> list:
    """GET /me/applications — trả sẵn job_title/company_name/job_status,
    không cần gọi thêm GET /jobs/{id} cho từng cái để lấy tên job."""
    return _request("GET", "/me/applications", access_token=access_token)


def withdraw_application(access_token: str, job_id: str, note: str = "") -> None:
    """DELETE /me/applications/{job_id} — huỷ đơn ứng tuyển của chính mình.
    note (không bắt buộc): lý do huỷ, học viên tự ghi ở modal huỷ ứng
    tuyển — gửi qua query param (không phải body, DELETE có body dễ bị
    một số proxy/middleware bỏ qua) — backend lưu vào audit_logs.note
    của WITHDRAW_JOB_APPLICATION, xem api/routers/me.py::withdraw_application."""
    params = {"note": note} if note else None
    _request("DELETE", f"/me/applications/{job_id}", access_token=access_token, params=params)


def get_cv_signed_url(access_token: str, application_id: str) -> str:
    """Staff lấy Signed URL từ backend để tải CV của học viên.
    Chỉ staff (role ss_team) mới có quyền gọi endpoint này."""
    data = _request("GET", f"/me/applications/{application_id}/cv-url", access_token=access_token)
    return data.get("signed_url", "")


def save_job(access_token: str, job_id: str) -> dict:
    """POST /me/saved-jobs. 409 nếu đã lưu rồi (dùng để toggle lưu/bỏ
    lưu ở app.py: thử lưu trước, dính 409 thì gọi unsave_job)."""
    return _request("POST", "/me/saved-jobs", access_token=access_token, json={"job_id": job_id})


def list_my_saved_jobs(access_token: str) -> list:
    return _request("GET", "/me/saved-jobs", access_token=access_token)


def unsave_job(access_token: str, job_id: str) -> None:
    _request("DELETE", f"/me/saved-jobs/{job_id}", access_token=access_token)


def list_job_applicants(access_token: str, job_id: str) -> list:
    """GET /jobs/{id}/applications (đòi role ss_team+) — staff xem ai đã
    ứng tuyển 1 job, kèm sẵn full_name/email người ứng tuyển."""
    return _request("GET", f"/jobs/{job_id}/applications", access_token=access_token)


def list_job_savers(access_token: str, job_id: str) -> list:
    """Thêm 08/2026 — GET /jobs/{id}/saved-jobs (đòi role ss_team+),
    mirror ĐÚNG list_job_applicants() ở trên nhưng cho chiều 'lưu'
    (bookmark) thay vì 'ứng tuyển'. Dùng ở job_detail.html, cạnh khối
    'Học viên đã ứng tuyển' đã có sẵn — xem app.py::job_detail()."""
    return _request("GET", f"/jobs/{job_id}/saved-jobs", access_token=access_token)


def list_applications_of_user(access_token: str, ss_user_id: str) -> list:
    """Thêm 08/2026 — GET /auth/users/{id}/applications (đòi role
    ss_team+), chiều "1 học viên đã ứng tuyển job nào" (khác
    list_my_applications(), dùng cho CHÍNH học viên xem đơn của mình).
    Trả cùng field như list_my_applications() (job_title/job_status/
    company_name...) vì cùng response_model JobApplicationOut ở backend
    — dùng cho trang /student-activity/<id> (xem app.py)."""
    return _request("GET", f"/auth/users/{ss_user_id}/applications", access_token=access_token)


def list_saved_jobs_of_user(access_token: str, ss_user_id: str) -> list:
    """Thêm 08/2026 — GET /auth/users/{id}/saved-jobs (đòi role
    ss_team+), mirror ĐÚNG list_applications_of_user() ở trên nhưng cho
    chiều 'lưu'. Trước đây saved_jobs cố ý riêng tư 100%, không route
    nào cho staff xem theo học viên — xem lịch sử trao đổi + comment ở
    backend db.list_saved_jobs_for_job() để biết lý do đảo ngược."""
    return _request("GET", f"/auth/users/{ss_user_id}/saved-jobs", access_token=access_token)


# ---------------------------------------------------------------------------
# Đăng ký công khai (học viên) — public_router, KHÔNG cần JWT
# ---------------------------------------------------------------------------

def register(full_name: str, email: str, password: str, phone: str = "", track: str = "") -> dict:
    """POST /auth/register — luôn tạo role='user' (= học viên ở web này).
    Trả về {ss_user_id, email, message} — KHÔNG có token, vì tài khoản
    phải xác thực email (bấm link trong mail) trước khi login được.

    phone/track: backend đã có cột lưu (migration_add_phone_track.sql,
    08/2026, đã chạy trên Postgres production) — gửi thẳng vào payload
    nếu có giá trị, backend lưu và trả lại đầy đủ ở GET /auth/me,
    GET /jobs/{id}/applications."""
    payload = {"full_name": full_name, "email": email, "password": password}
    if phone:
        payload["phone"] = phone
    if track:
        payload["track"] = track
    return _request("POST", "/auth/register", json=payload)


def resend_verification(email: str) -> dict:
    """POST /auth/resend-verification — xin gửi lại link xác thực (token
    cũ hết hạn sau 24h hoặc email bị thất lạc)."""
    return _request("POST", "/auth/resend-verification", json={"email": email})


def forgot_password(email: str) -> dict:
    """POST /auth/forgot-password — xin link đặt lại mật khẩu. Backend
    LUÔN trả cùng 1 message chung chung dù email có tồn tại hay không
    (chống dò email) — hàm này KHÔNG bao giờ raise vì email sai/không
    tồn tại, chỉ raise nếu bản thân request lỗi (mất mạng, backend sập).
    Trả {"message": "..."} — flash thẳng message này cho user."""
    return _request("POST", "/auth/forgot-password", json={"email": email})


def reset_password(token: str, new_password: str) -> dict:
    """POST /auth/reset-password — đặt mật khẩu mới bằng token nhận từ
    email. Raise BackendAuthError (status_code=400) nếu token sai/đã
    dùng/hết hạn — message tiếng Việt từ backend đã đủ rõ để flash
    thẳng, không cần phân biệt thêm ở đây (khác wrong_credentials của
    login()) vì chỉ có 1 lý do 400 duy nhất ở route này."""
    return _request("POST", "/auth/reset-password", json={"token": token, "new_password": new_password})


# ---------------------------------------------------------------------------
# Nhắn tin học viên ↔ SS / SS ↔ SS (thêm 08/2026) — xem
# backend-scrap-jd-nhan-tin.md cho kế hoạch đầy đủ (data model, state
# machine, bảo mật). Đặt ở ĐÂY (không phải crawler_client.py) vì cùng lý
# do mọi hàm khác trong file này — router /messages/... của backend bắt
# buộc Authorization: Bearer <access_token>, không chỉ X-API-Key.
# Dùng ở blueprints/messages.py.
# ---------------------------------------------------------------------------

def list_conversations(access_token: str) -> list:
    """GET /messages/conversations — hội thoại ĐÃ CÓ ít nhất 1 tin nhắn
    (backend suy trực tiếp từ bảng messages, xem db/messages.py::
    list_conversations), kèm last_message_preview/last_message_at/
    unread_count/relationship_status (None nếu là cặp SS-SS, không qua
    state machine chat_relationships)."""
    return _request("GET", "/messages/conversations", access_token=access_token)


def list_pending_requests(access_token: str) -> list:
    """GET /messages/pending-requests — CHỈ SS/admin gọi được (backend tự
    403 nếu không phải). Học viên đang 'pending' nhưng CHƯA từng nhắn
    (relationship có nhưng bảng messages chưa có dòng nào) nên KHÔNG nằm
    trong list_conversations() ở trên — đây là mục "Yêu cầu đang chờ"
    riêng cho SS."""
    return _request("GET", "/messages/pending-requests", access_token=access_token)


def get_unread_count(access_token: str) -> int:
    """GET /messages/unread-count — dùng cho: (a) badge sidebar poll
    20-30s (xem public/app.js, blueprints/messages.py::unread_count_json),
    (b) context_processor inject_unread_message_count (app.py) hiện số
    ngay lúc tải trang lần đầu, trước khi JS kịp poll lần nào."""
    data = _request("GET", "/messages/unread-count", access_token=access_token)
    return data.get("count", 0)


def search_people(access_token: str, q: str) -> list:
    """GET /messages/search-people?q=... — CHỈ trả id/full_name/role,
    KHÔNG email/phone (backend tự lọc theo role người tìm: học viên chỉ
    thấy ss_team/admin, SS/admin thấy mọi role — xem
    backend-scrap-jd-nhan-tin.md §4). q rỗng thì không gọi API, tránh
    round-trip thừa cho trang tìm người lúc mới mở (chưa gõ gì)."""
    if not q:
        return []
    return _request("GET", "/messages/search-people", access_token=access_token, params={"q": q})


def get_message_history(access_token: str, partner_id: str, before_id: int | None = None, limit: int = 50) -> list:
    """GET /messages/with/{partner_id} — lịch sử đầy đủ, MỚI NHẤT TRƯỚC
    (backend ORDER BY id DESC — caller tự đảo lại nếu cần hiển thị cũ->
    mới, xem blueprints/messages.py::thread()). Cho xem được kể cả khi
    quan hệ đang declined/blocked (backend chỉ chặn GỬI, không chặn XEM
    — xem docstring route get_history phía backend)."""
    params = {"limit": limit}
    if before_id is not None:
        params["before_id"] = before_id
    return _request("GET", f"/messages/with/{partner_id}", access_token=access_token, params=params)


def get_messages_since(access_token: str, partner_id: str, after_id: int) -> list:
    """GET /messages/since/{partner_id}?after_id=... — polling nhẹ trong
    lúc mở khung chat (xem public/app.js, poll ~5s/lần). Trả CŨ NHẤT
    TRƯỚC (ORDER BY id ASC ở backend), khớp đúng thứ tự append vào cuối
    khung chat phía JS, không cần đảo lại."""
    return _request(
        "GET", f"/messages/since/{partner_id}", access_token=access_token,
        params={"after_id": after_id},
    )


def mark_messages_read(access_token: str, partner_id: str) -> int:
    """POST /messages/read/{partner_id} — đánh dấu đã đọc mọi tin
    partner_id gửi cho current_user. Gọi mỗi lần mở khung chat
    (blueprints/messages.py::thread()) — lỗi ở đây bị caller NUỐT (không
    flash) vì không đáng làm hỏng cả trang chỉ vì việc đánh dấu đã đọc
    thất bại, người dùng vẫn cần xem được lịch sử tin nhắn."""
    data = _request("POST", f"/messages/read/{partner_id}", access_token=access_token)
    return data.get("marked_read", 0)


def send_message(access_token: str, receiver_id: str, content: str) -> dict:
    """POST /messages — gửi 1 tin nhắn. Response backend KHÔNG đồng nhất
    1 shape (xem docstring api/routers/messages.py::send_message):
      - 201: tin nhắn thật đã được lưu -> trả {'status': 'sent', **tin nhắn}.
      - 202: học viên vừa TẠO hoặc GỬI LẠI request pending tới 1 SS lần
        đầu — CHƯA có tin nhắn nào được lưu -> trả
        {'status': 'pending', 'message': '...'} (message đã là câu tiếng
        Việt sẵn sàng flash).
    _request() dùng chung ở trên KHÔNG xử lý được 202 (chỉ coi
    200/201/204 là thành công, phần còn lại rơi vào nhánh lỗi) nên hàm
    này tự gọi requests.post() trực tiếp — theo đúng pattern
    apply_to_job() ở trên (route khác cũng cần xử lý status code đặc
    biệt ngoài quy ước chung)."""
    url = f"{CRAWLER_API_URL}/messages"
    try:
        res = requests.post(
            url, headers=_headers(access_token),
            json={"receiver_id": receiver_id, "content": content},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise BackendAuthError(f"Không kết nối được tới backend: {exc}") from exc

    if res.status_code == 201:
        data = res.json()
        data["status"] = "sent"
        return data
    if res.status_code == 202:
        return res.json()

    try:
        detail = res.json().get("detail", "") or ""
    except Exception:
        detail = res.text[:300]

    if res.status_code == 429:
        raise BackendAuthError(
            detail or "Bạn đang gửi quá nhanh, vui lòng thử lại sau ít phút.", status_code=429,
        )
    if res.status_code == 409:
        raise BackendAuthError(
            detail or "Không thể gửi — trạng thái hội thoại vừa thay đổi, tải lại trang để xem mới nhất.",
            status_code=409,
        )
    if res.status_code == 403:
        raise BackendAuthError(detail or "Bạn không có quyền nhắn tin với người này.", status_code=403)
    if res.status_code == 404:
        raise BackendAuthError(detail or "Không tìm thấy người nhận.", status_code=404)
    if res.status_code == 400:
        raise BackendAuthError(detail or "Nội dung tin nhắn không hợp lệ.", status_code=400)

    raise BackendAuthError(detail or f"Lỗi khi gửi tin nhắn ({res.status_code})", status_code=res.status_code)


def accept_message_request(access_token: str, relationship_id: str) -> dict:
    """POST /messages/relationships/{id}/accept — CHỈ SS/admin sở hữu
    request đó gọi được (backend tự 403 nếu không đúng role, 409 nếu
    request đã bị xử lý bởi thao tác khác / không thuộc về mình)."""
    return _request("POST", f"/messages/relationships/{relationship_id}/accept", access_token=access_token)


def decline_message_request(access_token: str, relationship_id: str) -> dict:
    """POST /messages/relationships/{id}/decline — cùng điều kiện như
    accept_message_request() ở trên."""
    return _request("POST", f"/messages/relationships/{relationship_id}/decline", access_token=access_token)


def cancel_pending_request(access_token: str, ss_id: str) -> dict:
    """POST /messages/cancel/{ss_id} — CHỈ role 'user' gọi được (backend
    tự 403 nếu SS gọi nhầm). Học viên tự huỷ request 'pending' do CHÍNH
    MÌNH tạo (gửi nhầm SS / đổi ý) — nhận thẳng ss_id (giống
    block_student_in_chat() bên dưới, KHÔNG cần relationship_id) nên
    dùng được ngay từ trang tìm người/inbox mà không vướng gap
    relationship_id như unblock_message_relationship().

    KHÁC decline (do SS làm): huỷ ở đây XOÁ HẲN row, KHÔNG áp cooldown 7
    ngày — học viên gửi lại ngay lập tức được. 404 nếu không có request
    pending nào đang chờ với ss_id này (đã bị SS xử lý / chưa từng gửi),
    409 nếu SS vừa accept/decline đúng lúc gọi (race hiếm)."""
    return _request("POST", f"/messages/cancel/{ss_id}", access_token=access_token)


def block_student_in_chat(access_token: str, student_id: str) -> dict:
    """POST /messages/block/{student_id} — SS/admin tự chặn 1 học viên,
    nhận THẲNG student_id (KHÔNG cần biết relationship_id trước) nên
    dùng được cả 2 trường hợp: chặn trước 1 học viên chưa từng có quan
    hệ nào, LẪN chặn giữa chừng 1 hội thoại đã 'accepted' — xem docstring
    route block_student phía backend."""
    return _request("POST", f"/messages/block/{student_id}", access_token=access_token)


def unblock_message_relationship(access_token: str, relationship_id: str) -> dict:
    """POST /messages/relationships/{id}/unblock — CẦN relationship_id.

    LƯU Ý (08/2026, xem trao đổi lúc làm FE): hiện KHÔNG có route backend
    nào trả relationship_id cho 1 cặp đã 'accepted'/'blocked' —
    ConversationOut (GET /messages/conversations) KHÔNG có field id, chỉ
    PendingRequestOut (GET /messages/pending-requests, dành cho request
    CHƯA từng nhắn) mới có. Nghĩa là UI (blueprints/messages.py,
    templates/messages.html) hiện KHÔNG có cách lấy relationship_id để
    gọi hàm này sau khi đã rời khỏi phản hồi ngay lúc vừa block (response
    của block_student_in_chat() ở trên CÓ trả id, nhưng chỉ dùng được
    ngay tại thời điểm đó, không có nơi nào lưu lại cho lần sau).

    Hàm này vẫn viết sẵn, gọi được ngay khi backend bổ sung 1 trong 2:
    (a) thêm field relationship_id vào ConversationOut, hoặc
    (b) thêm route POST /messages/unblock/{student_id} mirror đúng
        block_student_in_chat() ở trên."""
    return _request("POST", f"/messages/relationships/{relationship_id}/unblock", access_token=access_token)
