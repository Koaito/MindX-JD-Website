"""Lớp 1 (pure function) + Lớp 2 (_call_authed, cần session/request context)
cho helpers.py.

_call_authed là hàm quan trọng nhất trong toàn bộ suite này: đây chính
là hàm từng bị bug (2 bản copy-paste lệch nhau, gây crash 500 sau ~30
phút do không tự refresh token 401) — xem docstring đầu helpers.py.
"""

from datetime import date

import pytest
from markupsafe import Markup

from crawler_client import CrawlerAPIError
from backend_auth import BackendAuthError
import helpers


# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_valid_date(self):
        assert helpers.parse_date("2026-08-24") == date(2026, 8, 24)

    def test_none_returns_none(self):
        assert helpers.parse_date(None) is None

    def test_empty_string_returns_none(self):
        assert helpers.parse_date("") is None

    def test_invalid_format_returns_none(self):
        assert helpers.parse_date("24/08/2026") is None

    def test_garbage_string_returns_none(self):
        assert helpers.parse_date("not-a-date") is None


# ---------------------------------------------------------------------------
# _parse_any_date
# ---------------------------------------------------------------------------

class TestParseAnyDate:
    def test_iso_datetime_with_z_suffix(self):
        # Dữ liệu backend hay trả kiểu "2026-08-24T10:30:00Z"
        assert helpers._parse_any_date("2026-08-24T10:30:00Z") == date(2026, 8, 24)

    def test_iso_datetime_with_offset(self):
        assert helpers._parse_any_date("2026-08-24T10:30:00+07:00") == date(2026, 8, 24)

    def test_plain_date_format(self):
        assert helpers._parse_any_date("2026-08-24") == date(2026, 8, 24)

    def test_none_returns_none(self):
        assert helpers._parse_any_date(None) is None

    def test_non_string_returns_none(self):
        assert helpers._parse_any_date(12345) is None
        assert helpers._parse_any_date(date(2026, 1, 1)) is None

    def test_empty_string_returns_none(self):
        assert helpers._parse_any_date("") is None

    def test_garbage_returns_none(self):
        assert helpers._parse_any_date("hello world") is None


# ---------------------------------------------------------------------------
# format_date
# ---------------------------------------------------------------------------

class TestFormatDate:
    def test_none_returns_em_dash(self):
        assert helpers.format_date(None) == "—"

    def test_empty_string_returns_em_dash(self):
        assert helpers.format_date("") == "—"

    def test_iso_string_default_format(self):
        assert helpers.format_date("2026-08-24T10:30:00Z") == "24/08/2026"

    def test_plain_date_string(self):
        assert helpers.format_date("2026-08-24") == "24/08/2026"

    def test_date_object(self):
        assert helpers.format_date(date(2026, 8, 24)) == "24/08/2026"

    def test_custom_format(self):
        assert helpers.format_date("2026-08-24", fmt="%Y/%m") == "2026/08"

    def test_unparseable_string_returned_as_is(self):
        assert helpers.format_date("N/A") == "N/A"

    def test_object_without_strftime_returns_em_dash(self):
        assert helpers.format_date(12345) == "—"


# ---------------------------------------------------------------------------
# _jobs_by_month
# ---------------------------------------------------------------------------

class TestJobsByMonth:
    def test_counts_jobs_in_matching_month(self, monkeypatch):
        # Cố định "hôm nay" để test không phụ thuộc ngày chạy thật
        class FixedDatetime(helpers.datetime):
            @classmethod
            def now(cls):
                return cls(2026, 8, 24)

        monkeypatch.setattr(helpers, "datetime", FixedDatetime)

        jobs = [
            {"date_collected": "2026-08-01"},
            {"date_collected": "2026-08-15"},
            {"date_collected": "2026-07-01"},
        ]
        labels, counts = helpers._jobs_by_month(jobs, "date_collected", months_back=2)
        assert labels == ["07/2026", "08/2026"]
        assert counts == [1, 2]

    def test_ignores_jobs_with_unparseable_date(self, monkeypatch):
        class FixedDatetime(helpers.datetime):
            @classmethod
            def now(cls):
                return cls(2026, 8, 24)

        monkeypatch.setattr(helpers, "datetime", FixedDatetime)

        jobs = [{"date_collected": None}, {"date_collected": "garbage"}]
        labels, counts = helpers._jobs_by_month(jobs, "date_collected", months_back=1)
        assert counts == [0]

    def test_only_past_filters_future_dates(self, monkeypatch):
        class FixedDatetime(helpers.datetime):
            @classmethod
            def now(cls):
                return cls(2026, 8, 24)

        monkeypatch.setattr(helpers, "datetime", FixedDatetime)

        jobs = [{"deadline": "2026-08-30"}, {"deadline": "2026-08-01"}]
        _, counts = helpers._jobs_by_month(jobs, "deadline", months_back=1, only_past=True)
        # Chỉ 2026-08-01 (đã qua) được đếm, 2026-08-30 (tương lai) bị loại
        assert counts == [1]

    def test_year_rollover(self, monkeypatch):
        # Tháng 1 -> months_back phải lùi đúng sang năm trước
        class FixedDatetime(helpers.datetime):
            @classmethod
            def now(cls):
                return cls(2026, 1, 15)

        monkeypatch.setattr(helpers, "datetime", FixedDatetime)

        jobs = [{"date_collected": "2025-12-01"}]
        labels, counts = helpers._jobs_by_month(jobs, "date_collected", months_back=2)
        assert labels == ["12/2025", "01/2026"]
        assert counts == [1, 0]


# ---------------------------------------------------------------------------
# to_bullets
# ---------------------------------------------------------------------------

class TestToBullets:
    def test_empty_value_returns_empty_string(self):
        assert helpers.to_bullets(None) == ""
        assert helpers.to_bullets("") == ""

    def test_single_line_wraps_in_p(self):
        result = helpers.to_bullets("Một dòng duy nhất")
        assert isinstance(result, Markup)
        assert str(result) == "<p>Một dòng duy nhất</p>"

    def test_multi_line_wraps_in_ul(self):
        result = helpers.to_bullets("Dòng 1\nDòng 2\nDòng 3")
        assert str(result) == (
            '<ul class="jd-bullets"><li>Dòng 1</li><li>Dòng 2</li><li>Dòng 3</li></ul>'
        )

    def test_strips_bullet_markers(self):
        result = helpers.to_bullets("- Dòng 1\n* Dòng 2\n• Dòng 3")
        assert str(result) == (
            '<ul class="jd-bullets"><li>Dòng 1</li><li>Dòng 2</li><li>Dòng 3</li></ul>'
        )

    def test_escapes_html_in_lines(self):
        # Đảm bảo không bị XSS qua nội dung job description
        result = helpers.to_bullets("Dòng 1\n<script>alert(1)</script>")
        assert "<script>" not in str(result)
        assert "&lt;script&gt;" in str(result)

    def test_blank_lines_filtered_out(self):
        result = helpers.to_bullets("Dòng 1\n\n\nDòng 2")
        assert str(result) == '<ul class="jd-bullets"><li>Dòng 1</li><li>Dòng 2</li></ul>'


# ---------------------------------------------------------------------------
# _call_authed — LỚP 2: cần Flask request/session context, mock hết HTTP.
#
# Đây là hàm quan trọng nhất trong suite: bug lịch sử là 2 bản copy-paste
# lệch nhau, thiếu logic refresh token khi 401 -> crash 500 sau khi access
# token hết hạn (~30 phút). Test dưới đây cover đúng 3 nhánh mô tả trong
# docstring của _call_authed.
# ---------------------------------------------------------------------------

class TestCallAuthed:
    def test_calls_fn_with_access_token_from_session(self, flask_app):
        with flask_app.test_request_context():
            from flask import session
            session["access_token"] = "tok-abc"
            session["refresh_token"] = "refresh-abc"

            fn = lambda token, x: (token, x)
            result = helpers._call_authed(fn, "hello")
            assert result == ("tok-abc", "hello")

    def test_401_triggers_refresh_and_retries(self, flask_app, mocker):
        """Nhánh chính: gọi lần 1 dính 401 -> refresh -> gọi lại thành công."""
        with flask_app.test_request_context():
            from flask import session
            session["access_token"] = "expired-tok"
            session["refresh_token"] = "valid-refresh"

            mocker.patch(
                "helpers.backend_auth.refresh",
                return_value={"access_token": "new-tok", "refresh_token": "new-refresh"},
            )

            calls = []

            def fn(token, x):
                calls.append(token)
                if token == "expired-tok":
                    raise CrawlerAPIError("hết hạn", status_code=401)
                return f"ok:{token}:{x}"

            result = helpers._call_authed(fn, "payload")

            assert result == "ok:new-tok:payload"
            assert calls == ["expired-tok", "new-tok"]
            # Token mới phải được lưu lại vào session
            assert session["access_token"] == "new-tok"
            assert session["refresh_token"] == "new-refresh"

    def test_401_without_refresh_token_reraises(self, flask_app):
        """Không có refresh_token trong session -> raise thẳng, không thử refresh."""
        with flask_app.test_request_context():
            from flask import session
            session["access_token"] = "expired-tok"
            session["refresh_token"] = None

            def fn(token):
                raise CrawlerAPIError("hết hạn", status_code=401)

            with pytest.raises(CrawlerAPIError):
                helpers._call_authed(fn)

    def test_non_401_error_reraises_without_refresh(self, flask_app, mocker):
        """Lỗi khác 401 (vd 404/409) -> raise thẳng, KHÔNG thử refresh."""
        with flask_app.test_request_context():
            from flask import session
            session["access_token"] = "tok"
            session["refresh_token"] = "refresh"

            refresh_mock = mocker.patch("helpers.backend_auth.refresh")

            def fn(token):
                raise CrawlerAPIError("trùng dữ liệu", status_code=409)

            with pytest.raises(CrawlerAPIError) as exc_info:
                helpers._call_authed(fn)

            assert exc_info.value.status_code == 409
            refresh_mock.assert_not_called()

    def test_refresh_failure_clears_tokens_and_raises_401(self, flask_app, mocker):
        """Refresh token cũng hết hạn/không hợp lệ -> clear session, raise
        401 với message thân thiện, không để lộ lỗi backend gốc."""
        with flask_app.test_request_context():
            from flask import session
            session["access_token"] = "expired-tok"
            session["refresh_token"] = "expired-refresh"

            mocker.patch(
                "helpers.backend_auth.refresh",
                side_effect=BackendAuthError("refresh token đã hết hạn", status_code=401),
            )

            def fn(token):
                raise CrawlerAPIError("hết hạn", status_code=401)

            with pytest.raises(CrawlerAPIError) as exc_info:
                helpers._call_authed(fn)

            assert exc_info.value.status_code == 401
            assert "access_token" not in session
            assert "refresh_token" not in session
