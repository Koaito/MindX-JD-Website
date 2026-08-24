"""Lớp 1 cho crawler_client.py.

Trọng tâm: get_enums()/get_level_codes() — nguy cơ regression cao nhất
theo đánh giá ban đầu, vì đây là cache TTL 5 phút cấp module vừa mới
thêm (08/2026), thay thế list LEVEL_CODE hardcode cũ.

fixture `reset_enums_cache` (conftest.py, autouse) đảm bảo mỗi test
dưới đây bắt đầu với cache rỗng.
"""

import pytest

import crawler_client


# ---------------------------------------------------------------------------
# get_enums / get_level_codes — cache TTL 5 phút
# ---------------------------------------------------------------------------

class TestGetEnumsCache:
    def test_cache_miss_calls_backend(self, mocker):
        request_mock = mocker.patch(
            "crawler_client._request", return_value={"level_code": ["Intern", "Junior"]}
        )
        result = crawler_client.get_enums()
        assert result == {"level_code": ["Intern", "Junior"]}
        request_mock.assert_called_once_with("GET", "/enums")

    def test_cache_hit_does_not_call_backend_again(self, mocker):
        request_mock = mocker.patch(
            "crawler_client._request", return_value={"level_code": ["Intern"]}
        )
        crawler_client.get_enums()
        crawler_client.get_enums()
        crawler_client.get_enums()
        # 3 lần gọi liên tiếp trong TTL -> chỉ 1 lần request thật ra mạng
        assert request_mock.call_count == 1

    def test_stale_cache_triggers_refetch(self, mocker):
        request_mock = mocker.patch(
            "crawler_client._request", return_value={"level_code": ["Intern"]}
        )
        crawler_client.get_enums()
        # Giả lập đã qua 301 giây (> TTL 300s)
        crawler_client._enums_cache["fetched_at"] -= 301
        crawler_client.get_enums()
        assert request_mock.call_count == 2

    def test_force_refresh_bypasses_fresh_cache(self, mocker):
        request_mock = mocker.patch(
            "crawler_client._request", return_value={"level_code": ["Intern"]}
        )
        crawler_client.get_enums()
        crawler_client.get_enums(force_refresh=True)
        assert request_mock.call_count == 2

    def test_backend_failure_falls_back_to_stale_cache(self, mocker):
        """Nếu đã có cache thành công trước đó, backend lỗi lần sau ->
        vẫn trả cache CŨ (dù hết hạn) thay vì để trang trắng."""
        mocker.patch(
            "crawler_client._request", return_value={"level_code": ["Intern", "Senior"]}
        )
        first = crawler_client.get_enums()
        assert first == {"level_code": ["Intern", "Senior"]}

        crawler_client._enums_cache["fetched_at"] -= 301
        mocker.patch(
            "crawler_client._request",
            side_effect=crawler_client.CrawlerAPIError("backend sập"),
        )
        second = crawler_client.get_enums()
        assert second == {"level_code": ["Intern", "Senior"]}

    def test_backend_failure_with_no_cache_returns_empty_dict(self, mocker):
        """Chưa từng cache thành công lần nào (vd app vừa khởi động) VÀ
        backend lỗi -> trả {} rỗng, KHÔNG raise (caller tự lo fallback)."""
        mocker.patch(
            "crawler_client._request",
            side_effect=crawler_client.CrawlerAPIError("backend sập"),
        )
        result = crawler_client.get_enums()
        assert result == {}


class TestGetLevelCodes:
    def test_returns_values_from_enums(self, mocker):
        mocker.patch(
            "crawler_client.get_enums", return_value={"level_code": ["Intern", "Middle"]}
        )
        assert crawler_client.get_level_codes() == ["Intern", "Middle"]

    def test_falls_back_when_enums_missing_key(self, mocker):
        mocker.patch("crawler_client.get_enums", return_value={})
        assert crawler_client.get_level_codes() == crawler_client._LEVEL_CODES_FALLBACK

    def test_falls_back_when_level_code_empty_list(self, mocker):
        mocker.patch("crawler_client.get_enums", return_value={"level_code": []})
        assert crawler_client.get_level_codes() == crawler_client._LEVEL_CODES_FALLBACK

    def test_fallback_list_has_7_values(self):
        # Docstring get_level_codes() ghi rõ "7 giá trị level_code hợp lệ"
        assert len(crawler_client._LEVEL_CODES_FALLBACK) == 7


# ---------------------------------------------------------------------------
# *_MAP / *_MAP_REV — đối xứng 2 chiều (VN <-> mã backend)
# ---------------------------------------------------------------------------

MAP_PAIRS = [
    ("JOB_STATUS_MAP", "JOB_STATUS_MAP_REV"),
    ("WORK_TYPE_MAP", "WORK_TYPE_MAP_REV"),
    ("SALARY_TYPE_MAP", "SALARY_TYPE_MAP_REV"),
    ("SALARY_PERIOD_MAP", "SALARY_PERIOD_MAP_REV"),
    ("CONTACT_STATUS_MAP", "CONTACT_STATUS_MAP_REV"),
    ("PARTNERSHIP_POTENTIAL_MAP", "PARTNERSHIP_POTENTIAL_MAP_REV"),
]


@pytest.mark.parametrize("map_name,rev_name", MAP_PAIRS)
class TestMapSymmetry:
    def test_rev_is_exact_inverse(self, map_name, rev_name):
        forward = getattr(crawler_client, map_name)
        backward = getattr(crawler_client, rev_name)
        assert backward == {v: k for k, v in forward.items()}

    def test_no_duplicate_display_values(self, map_name, rev_name):
        """Nếu 2 mã backend khác nhau map ra cùng 1 label tiếng Việt, MAP_REV
        sẽ mất dữ liệu (key ghi đè key) — value hiển thị phải là duy nhất."""
        forward = getattr(crawler_client, map_name)
        values = list(forward.values())
        assert len(values) == len(set(values)), (
            f"{map_name} có giá trị hiển thị trùng nhau: {values}"
        )

    def test_round_trip_every_key(self, map_name, rev_name):
        forward = getattr(crawler_client, map_name)
        backward = getattr(crawler_client, rev_name)
        for backend_code, vn_label in forward.items():
            assert backward[vn_label] == backend_code
