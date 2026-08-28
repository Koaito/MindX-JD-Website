"""Lớp 1 cho crawler_client.py.

Trọng tâm: get_enums()/get_level_codes() — nguy cơ regression cao nhất
theo đánh giá ban đầu, vì đây là cache TTL 5 phút cấp module vừa mới
thêm (08/2026), thay thế list LEVEL_CODE hardcode cũ.

fixture `reset_enums_cache` (conftest.py, autouse) đảm bảo mỗi test
dưới đây bắt đầu với cache rỗng.

QUAN TRỌNG — mock đúng vị trí (sau khi tách crawler_client.py thành
package, 08/2026): get_enums()/get_level_codes() giờ nằm trong
crawler_client/enums.py và gọi lẫn nhau (get_level_codes -> get_enums
-> _request) bằng tên cục bộ NGAY TRONG enums.py, không đi qua
crawler_client/__init__.py ở call time. Patch tại "crawler_client._request"/
"crawler_client.get_enums" (re-export ở __init__.py) KHÔNG có tác dụng gì
với lời gọi nội bộ này — phải patch "crawler_client.enums._request"/
"crawler_client.enums.get_enums" (đúng namespace nơi enums.py NHÌN THẤY
tên đó), giống lý do đã ghi ở tests/test_data_management.py.
"""

import pytest

import crawler_client

# ---------------------------------------------------------------------------
# get_enums / get_level_codes — cache TTL 5 phút
# ---------------------------------------------------------------------------

class TestGetEnumsCache:
    def test_cache_miss_calls_backend(self, mocker):
        request_mock = mocker.patch(
            "crawler_client.enums._request", return_value={"level_code": ["Intern", "Junior"]}
        )
        result = crawler_client.get_enums()
        assert result == {"level_code": ["Intern", "Junior"]}
        request_mock.assert_called_once_with("GET", "/enums")

    def test_cache_hit_does_not_call_backend_again(self, mocker):
        request_mock = mocker.patch(
            "crawler_client.enums._request", return_value={"level_code": ["Intern"]}
        )
        crawler_client.get_enums()
        crawler_client.get_enums()
        crawler_client.get_enums()
        # 3 lần gọi liên tiếp trong TTL -> chỉ 1 lần request thật ra mạng
        assert request_mock.call_count == 1

    def test_stale_cache_triggers_refetch(self, mocker):
        request_mock = mocker.patch(
            "crawler_client.enums._request", return_value={"level_code": ["Intern"]}
        )
        crawler_client.get_enums()
        # Giả lập đã qua 301 giây (> TTL 300s)
        crawler_client._enums_cache["fetched_at"] -= 301
        crawler_client.get_enums()
        assert request_mock.call_count == 2

    def test_force_refresh_bypasses_fresh_cache(self, mocker):
        request_mock = mocker.patch(
            "crawler_client.enums._request", return_value={"level_code": ["Intern"]}
        )
        crawler_client.get_enums()
        crawler_client.get_enums(force_refresh=True)
        assert request_mock.call_count == 2

    def test_backend_failure_falls_back_to_stale_cache(self, mocker):
        """Nếu đã có cache thành công trước đó, backend lỗi lần sau ->
        vẫn trả cache CŨ (dù hết hạn) thay vì để trang trắng."""
        mocker.patch(
            "crawler_client.enums._request", return_value={"level_code": ["Intern", "Senior"]}
        )
        first = crawler_client.get_enums()
        assert first == {"level_code": ["Intern", "Senior"]}

        crawler_client._enums_cache["fetched_at"] -= 301
        mocker.patch(
            "crawler_client.enums._request",
            side_effect=crawler_client.CrawlerAPIError("backend sập"),
        )
        second = crawler_client.get_enums()
        assert second == {"level_code": ["Intern", "Senior"]}

    def test_backend_failure_with_no_cache_returns_empty_dict(self, mocker):
        """Chưa từng cache thành công lần nào (vd app vừa khởi động) VÀ
        backend lỗi -> trả {} rỗng, KHÔNG raise (caller tự lo fallback)."""
        mocker.patch(
            "crawler_client.enums._request",
            side_effect=crawler_client.CrawlerAPIError("backend sập"),
        )
        result = crawler_client.get_enums()
        assert result == {}


class TestGetLevelCodes:
    def test_returns_values_from_enums(self, mocker):
        mocker.patch(
            "crawler_client.enums.get_enums", return_value={"level_code": ["Intern", "Middle"]}
        )
        assert crawler_client.get_level_codes() == ["Intern", "Middle"]

    def test_falls_back_when_enums_missing_key(self, mocker):
        mocker.patch("crawler_client.enums.get_enums", return_value={})
        assert crawler_client.get_level_codes() == crawler_client._LEVEL_CODES_FALLBACK

    def test_falls_back_when_level_code_empty_list(self, mocker):
        mocker.patch("crawler_client.enums.get_enums", return_value={"level_code": []})
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


# ---------------------------------------------------------------------------
# Re-export completeness — bug thật ĐÃ XẢY RA (08/2026): thêm hàm
# update_company_potential() vào crawler_client/companies.py nhưng quên
# thêm vào danh sách `from .companies import (...)` + __all__ ở
# crawler_client/__init__.py -> mọi nơi gọi qua `db_data.update_company_
# potential(...)` (cách gọi chuẩn của cả repo, xem docstring __init__.py)
# ăn AttributeError ngay ở production, KHÔNG lỗi lúc import module — vì
# `crawler_client.companies.update_company_potential` vẫn tồn tại bình
# thường, chỉ là không được re-export lên `crawler_client`.
#
# __init__.py CỐ Ý liệt kê thủ công (không dùng `from .x import *`) để
# tường minh/dễ đọc — đánh đổi là dễ quên 1 dòng khi thêm hàm mới. Test
# dưới đây tự dò TOÀN BỘ hàm public (không bắt đầu bằng "_") khai báo Ở
# CẤP MODULE (không tính hàm lồng bên trong hàm khác) của MỌI submodule
# crawler_client/*.py, rồi assert từng hàm đó:
#   1. Có mặt trong crawler_client.__all__
#   2. `crawler_client.<tên>` trỏ ĐÚNG object hàm đó (không phải bị hàm
#      cùng tên ở submodule khác ghi đè nhầm)
# Không cần thêm dòng nào ở đây khi thêm hàm public mới — test tự quét
# lại toàn bộ package mỗi lần chạy CI, sẽ đỏ ngay nếu ai quên re-export,
# thay vì đợi user bấm nút và ăn 500 ở production như lần trước.
# ---------------------------------------------------------------------------

import ast
import importlib
import pathlib

_CRAWLER_CLIENT_DIR = pathlib.Path(crawler_client.__file__).parent

# Submodule nào KHÔNG cần dò (không phải "domain" thật, hoặc __init__.py
# tự chủ động KHÔNG re-export toàn bộ — hiện chưa có case nào, để trống
# sẵn cho tương lai nếu phát sinh 1 submodule nội bộ thuần túy).
_SKIP_SUBMODULES = {"__init__"}


def _public_toplevel_functions(py_file: pathlib.Path) -> list[str]:
    """Trả về tên mọi function/class khai báo Ở CẤP MODULE (không lồng
    trong hàm/class khác) trong 1 file .py, bỏ qua tên bắt đầu bằng "_"
    (helper nội bộ, không kỳ vọng phải export ra ngoài submodule)."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
    return names


def _all_domain_submodules() -> list[str]:
    return sorted(
        p.stem for p in _CRAWLER_CLIENT_DIR.glob("*.py")
        if p.stem not in _SKIP_SUBMODULES
    )


class TestReExportCompleteness:
    @pytest.mark.parametrize("submodule_name", _all_domain_submodules())
    def test_every_public_function_is_reexported(self, submodule_name):
        py_file = _CRAWLER_CLIENT_DIR / f"{submodule_name}.py"
        public_names = _public_toplevel_functions(py_file)
        if not public_names:
            pytest.skip(f"{submodule_name}.py không có hàm/class public cấp module.")

        submodule = importlib.import_module(f"crawler_client.{submodule_name}")
        missing_from_all = []
        missing_from_package = []
        wrong_object = []

        for name in public_names:
            if name not in crawler_client.__all__:
                missing_from_all.append(name)
            if not hasattr(crawler_client, name):
                missing_from_package.append(name)
            elif getattr(crawler_client, name) is not getattr(submodule, name):
                wrong_object.append(name)

        assert not missing_from_all, (
            f"crawler_client/{submodule_name}.py có hàm public chưa thêm vào "
            f"__all__ ở crawler_client/__init__.py: {missing_from_all}"
        )
        assert not missing_from_package, (
            f"crawler_client/{submodule_name}.py có hàm public chưa `from ."
            f"{submodule_name} import ...` ở crawler_client/__init__.py: "
            f"{missing_from_package}"
        )
        assert not wrong_object, (
            f"crawler_client.<tên> đang trỏ NHẦM object khác (đụng tên với "
            f"submodule khác) cho: {wrong_object} (từ {submodule_name}.py)"
        )
