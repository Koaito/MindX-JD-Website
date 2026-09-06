"""Test cho backend_auth.py — thêm 09/2026 cùng đợt sửa Giai đoạn 1 kế
hoạch i18n (thêm error_code cho lỗi backend Scrap_JD trả về).

Trọng tâm:
  1. _format_detail() — hàm chuẩn hoá field "detail" từ response FastAPI,
     phải xử lý đúng CẢ 4 dạng có thể gặp (string, dict {error_code,
     message}, list lỗi validate Pydantic, dạng khác/rỗng). Đây là bản
     tương đương phía Flask của formatErrorDetail() bên Next.js
     (client.ts) — cùng 1 lớp bug: nếu không đọc đúng field "message"
     khi detail là dict, Flask sẽ flash() nguyên dict thô ra UI.
  2. BackendAuthError.email_not_verified — SAU khi xoá anti-pattern so
     khớp chuỗi con "xác thực", phải chỉ dựa vào error_code, KHÔNG còn
     bị ảnh hưởng bởi nội dung message (kể cả khi message có chứa từ
     "xác thực" vì lý do khác).
"""

from unittest.mock import MagicMock

import pytest

import backend_auth
from backend_auth import BackendAuthError, _format_detail


# ---------------------------------------------------------------------------
# _format_detail()
# ---------------------------------------------------------------------------

class TestFormatDetail:
    def test_string_detail_returns_as_is_no_error_code(self):
        message, error_code = _format_detail("Email hoặc mật khẩu không đúng.")
        assert message == "Email hoặc mật khẩu không đúng."
        assert error_code is None

    def test_dict_detail_reads_message_and_error_code(self):
        """Case chính — 5+ lỗi auth/session phía Scrap_JD giờ trả dạng này."""
        raw = {"error_code": "auth_email_not_verified", "message": "Email chưa được xác thực."}
        message, error_code = _format_detail(raw)
        assert message == "Email chưa được xác thực."
        assert error_code == "auth_email_not_verified"

    def test_dict_detail_without_message_field_returns_empty_not_raw_dict(self):
        """An toàn: nếu shape dict lạ (không có "message" dạng string),
        KHÔNG được để lộ dict thô ra ngoài — trả rỗng, caller tự có
        message mặc định (giống nhánh JSON.stringify fallback bên
        Next.js, nhưng ở đây caller luôn có default message tiếng Việt
        sẵn nên rỗng là lựa chọn an toàn hơn, tránh flash() ra repr dict)."""
        message, error_code = _format_detail({"weird": "shape"})
        assert message == ""
        assert error_code is None

    def test_list_detail_joins_pydantic_validation_messages(self):
        raw = [
            {"loc": ["body", "email"], "msg": "field required", "type": "missing"},
            {"loc": ["body", "password"], "msg": "string too short", "type": "string_too_short"},
        ]
        message, error_code = _format_detail(raw)
        assert message == "field required; string too short"
        assert error_code is None

    def test_none_detail_returns_empty(self):
        message, error_code = _format_detail(None)
        assert message == ""
        assert error_code is None


# ---------------------------------------------------------------------------
# BackendAuthError.email_not_verified — sau khi xoá anti-pattern so khớp chuỗi
# ---------------------------------------------------------------------------

class TestEmailNotVerified:
    def test_true_when_403_with_matching_error_code(self):
        exc = BackendAuthError("Email chưa được xác thực.", status_code=403, error_code="auth_email_not_verified")
        assert exc.email_not_verified is True

    def test_false_when_error_code_missing_even_if_message_mentions_xac_thuc(self):
        """Bug đã fix: TRƯỚC ĐÂY chỉ cần message chứa "xác thực" là match,
        dù error_code không phải auth_email_not_verified (vd lỗi 403 khác
        vô tình có từ "xác thực" trong câu, hoặc backend đổi câu chữ)."""
        exc = BackendAuthError(
            "Tài khoản đã bị khoá — vui lòng xác thực lại danh tính qua tổng đài.",
            status_code=403, error_code="auth_locked",
        )
        assert exc.email_not_verified is False

    def test_false_when_error_code_none(self):
        """Lỗi mạng/lỗi không có detail từ backend -> error_code=None mặc định."""
        exc = BackendAuthError("Không kết nối được tới backend.", status_code=403)
        assert exc.email_not_verified is False

    def test_false_when_status_code_not_403(self):
        exc = BackendAuthError("x", status_code=401, error_code="auth_email_not_verified")
        assert exc.email_not_verified is False


# ---------------------------------------------------------------------------
# _request() — end-to-end: error_code từ response JSON phải chảy đúng tới
# BackendAuthError, và str(exc) phải là message thuần (không phải dict thô).
# ---------------------------------------------------------------------------

def _fake_response(status_code: int, json_body: dict):
    res = MagicMock()
    res.status_code = status_code
    res.content = b"x"
    res.json.return_value = json_body
    res.text = str(json_body)
    return res


class TestRequestErrorCodePropagation:
    def test_login_401_object_detail_flows_to_error_code_and_plain_message(self, mocker):
        mocker.patch("backend_auth.CRAWLER_API_KEY", "test-key")
        mocker.patch(
            "backend_auth.requests.request",
            return_value=_fake_response(401, {"detail": {"error_code": "auth_wrong_credentials", "message": "Email hoặc mật khẩu không đúng."}}),
        )

        with pytest.raises(BackendAuthError) as exc_info:
            backend_auth.login("a@b.com", "wrong")

        exc = exc_info.value
        # str(exc) phải là message THUẦN, không phải "{'error_code': ...}"
        assert str(exc) == "Email hoặc mật khẩu không đúng."
        assert exc.error_code == "auth_wrong_credentials"
        assert exc.wrong_credentials is True

    def test_login_403_email_not_verified_object_detail(self, mocker):
        mocker.patch("backend_auth.CRAWLER_API_KEY", "test-key")
        mocker.patch(
            "backend_auth.requests.request",
            return_value=_fake_response(403, {"detail": {"error_code": "auth_email_not_verified", "message": "Email chưa được xác thực — kiểm tra hộp thư."}}),
        )

        with pytest.raises(BackendAuthError) as exc_info:
            backend_auth.login("a@b.com", "correct")

        exc = exc_info.value
        assert str(exc) == "Email chưa được xác thực — kiểm tra hộp thư."
        assert exc.email_not_verified is True

    def test_generic_error_string_detail_still_works(self, mocker):
        """Vài route FastAPI vẫn còn raise detail=string thuần (không phải
        mọi route đều có error_code) — phải KHÔNG bị vỡ."""
        mocker.patch("backend_auth.CRAWLER_API_KEY", "test-key")
        mocker.patch(
            "backend_auth.requests.request",
            return_value=_fake_response(404, {"detail": "Không tìm thấy tài khoản assigned_ss_user."}),
        )

        with pytest.raises(BackendAuthError) as exc_info:
            backend_auth.get_me("some-token")

        exc = exc_info.value
        assert str(exc) == "Không tìm thấy tài khoản assigned_ss_user."
        assert exc.error_code is None
