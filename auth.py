"""
Lớp user cho Flask-Login — từ bản này (08/2026) MỌI tài khoản (học viên
lẫn team SS) đều xác thực qua hệ JWT của chính backend scrap-jd (xem
backend_auth.py), KHÔNG còn Supabase Auth nữa (đã bỏ hẳn vì lo ngại bảo
mật: trước đây phải giữ SUPABASE_SERVICE_ROLE_KEY — key có TOÀN QUYỀN
trên cả project Supabase — ở phía server Flask).

3 role phía backend (user < ss_team < admin):
  - 'user'    -> học viên (tự đăng ký qua POST /auth/register công khai).
  - 'ss_team' -> nhân viên team SS (admin tạo qua POST /auth/users).
  - 'admin'   -> quản trị (tạo/đổi role người khác, trigger crawl...).

Access token (30 phút) + refresh token (30 ngày) được lưu ở Flask
session (cookie ký server-side mặc định — đủ dùng cho quy mô đồ án nội
bộ), KHÔNG lưu trong đối tượng BackendUser vì object này được dựng lại
mỗi request bởi app.load_user() — xem app.py các hàm
`_store_auth_tokens`/`_auth_tokens_from_session`.
"""

from flask_login import UserMixin


class BackendUser(UserMixin):
    """Đại diện 1 tài khoản đã đăng nhập, dựng từ response GET /auth/me
    (hoặc trực tiếp response TokenPairOut kèm 1 lượt GET /auth/me để lấy
    đủ thông tin — xem app.py login())."""

    def __init__(self, me: dict):
        self.id = me["ss_user_id"]
        self.email = me.get("email", "")
        self.full_name = me.get("full_name") or self.email
        self.role = me.get("role", "user")  # user | ss_team | admin
        # 2 field này backend CHƯA có cột lưu (đã báo, sẽ thêm sau) —
        # get() luôn trả None cho tới lúc đó, KHÔNG lỗi gì, chỉ đơn giản
        # chưa hiển thị được số điện thoại/track ngoài giao diện.
        self.phone = me.get("phone")
        self.track = me.get("track")
        self.must_change_password = bool(me.get("must_change_password"))
        self._active = bool(me.get("is_active", True))

    @property
    def is_active(self):
        # UserMixin.is_active mặc định là @property (read-only, luôn
        # True) — override để phản ánh đúng is_active thật từ backend
        # (tài khoản bị admin vô hiệu hoá thì Flask-Login cũng từ chối).
        return self._active

    @property
    def is_staff(self):
        # role >= 'ss_team' được coi là "team SS" ở phía giao diện web
        # này; role='user' là học viên. Nếu cần phân biệt sâu hơn
        # ss_team/admin thì kiểm tra trực tiếp self.role ở nơi cần.
        return self.role in ("ss_team", "admin")

    @property
    def is_student(self):
        return self.role == "user"

    def get_id(self):
        # Flask-Login lưu giá trị này vào session để load lại user mỗi request.
        return self.id
