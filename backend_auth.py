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


# ---------------------------------------------------------------------------
# /me/... — ứng tuyển & lưu job của CHÍNH học viên đang đăng nhập
# + GET /jobs/{id}/applications (staff xem ai đã ứng tuyển 1 job)
#
# Đặt ở ĐÂY (không phải crawler_client.py) vì mọi route này đều bắt buộc
# Authorization: Bearer <access_token> — crawler_client.py hiện chỉ gửi
# X-API-Key, không gửi JWT (crawler_client.py thuộc phạm vi việc khác
# đang sửa job/company/contact, không đụng vào để tránh xung đột khi
# merge). ss_user_id KHÔNG cần truyền — backend tự lấy từ chính JWT.
# ---------------------------------------------------------------------------

def apply_to_job(access_token: str, job_id: str, note: str = "") -> dict:
    """POST /me/applications. Backend tự chặn nếu job không ở trạng
    thái OPEN (400) hoặc đã ứng tuyển rồi (409)."""
    payload = {"job_id": job_id}
    if note:
        payload["note"] = note
    return _request("POST", "/me/applications", access_token=access_token, json=payload)


def list_my_applications(access_token: str) -> list:
    """GET /me/applications — trả sẵn job_title/company_name/job_status,
    không cần gọi thêm GET /jobs/{id} cho từng cái để lấy tên job."""
    return _request("GET", "/me/applications", access_token=access_token)


def withdraw_application(access_token: str, job_id: str) -> None:
    """DELETE /me/applications/{job_id} — huỷ đơn ứng tuyển của chính mình."""
    _request("DELETE", f"/me/applications/{job_id}", access_token=access_token)


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


# ---------------------------------------------------------------------------
# Đăng ký công khai (học viên) — public_router, KHÔNG cần JWT
# ---------------------------------------------------------------------------

def register(full_name: str, email: str, password: str, phone: str = "", track: str = "") -> dict:
    """POST /auth/register — luôn tạo role='user' (= học viên ở web này).
    Trả về {ss_user_id, email, message} — KHÔNG có token, vì tài khoản
    phải xác thực email (bấm link trong mail) trước khi login được.

    LƯU Ý: backend hiện CHƯA có cột phone/track trên ss_team_members
    (đã báo, sẽ thêm sau) — 2 field này vẫn được gửi kèm ở đây cho ĐÚNG
    hợp đồng tương lai, nhưng Pydantic (RegisterRequest) sẽ tự bỏ qua
    field lạ nên KHÔNG lỗi, chỉ đơn giản là chưa được lưu cho tới khi
    backend bổ sung cột + field trong schema. Không cần sửa lại chỗ gọi
    hàm này khi backend thêm xong — chỉ cần bỏ đoạn note này đi."""
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
