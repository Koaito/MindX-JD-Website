"""Lớp 3 cho blueprints/data_management.py — route-level, mock toàn bộ
crawler_client calls.

QUAN TRỌNG — mock đúng vị trí: blueprint import `crawler_client as
db_data`, nên phải patch tại "blueprints.data_management.db_data.<fn>"
(namespace nơi blueprint NHÌN THẤY tên đó), KHÔNG phải
"crawler_client.<fn>" — patch sai chỗ khiến mock coi như không tồn tại,
code thật vẫn chạy và có thể gọi ra internet thật trong lúc test.

Route được chọn theo đúng lịch sử bug thật (xem docstring các route
trong data_management.py — nơi đã sửa 3 bug gần đây về import company
suggestion/duplicate check):
  - export()
  - import_preview()
  - verify_field() — cố ý dùng _call_authed (khác company_suggestions()
    cũ), test đảm bảo route MỚI này thực sự đi qua _call_authed.
  - import_confirm()
"""

import io

from crawler_client import CrawlerAPIError


class TestExport:
    def test_export_success_returns_file(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        # export() gọi qua _call_authed(db_data.export_entity, ...) —
        # mock tại blueprints.data_management.db_data (namespace blueprint
        # nhìn thấy), không phải crawler_client trực tiếp.
        mocker.patch(
            "blueprints.data_management.db_data.export_entity",
            return_value=(b"col1,col2\nval1,val2", "job_export.csv", "text/csv"),
        )
        resp = staff_client.get("/data-management/export/job?format=csv")
        assert resp.status_code == 200
        assert resp.data == b"col1,col2\nval1,val2"
        assert "job_export.csv" in resp.headers["Content-Disposition"]

    def test_export_invalid_entity_type_404(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        resp = staff_client.get("/data-management/export/not-a-real-entity")
        assert resp.status_code == 404

    def test_export_backend_error_flashes_and_redirects(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.data_management.db_data.export_entity",
            side_effect=CrawlerAPIError("Backend lỗi 500"),
        )
        resp = staff_client.get("/data-management/export/job", follow_redirects=False)
        assert resp.status_code == 302
        assert "/data-management" in resp.headers["Location"]

    def test_export_default_format_is_xlsx(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        export_mock = mocker.patch(
            "blueprints.data_management.db_data.export_entity",
            return_value=(b"", "x.xlsx", "application/vnd.openxmlformats"),
        )
        staff_client.get("/data-management/export/company")
        # _call_authed(db_data.export_entity, entity_type, file_format, filters=...)
        args, kwargs = export_mock.call_args
        assert args[1] == "company"
        assert args[2] == "xlsx"

    def test_export_forwards_filter_query_params(self, staff_client, mocker):
        """Filter trên querystring (?status=OPEN&limit=50...) phải được
        forward đúng xuống db_data.export_entity(filters=...) — đây là
        toàn bộ lý do route nhận thêm query params, xem
        _parse_export_filters() trong blueprints/data_management.py."""
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        export_mock = mocker.patch(
            "blueprints.data_management.db_data.export_entity",
            return_value=(b"", "job_export.xlsx", "application/vnd.openxmlformats"),
        )
        staff_client.get(
            "/data-management/export/job"
            "?format=csv&status=OPEN&company_id=c-1&from_date=2026-01-01"
            "&to_date=2026-08-01&date_field=updated_at&limit=50&is_active=true"
        )
        _, kwargs = export_mock.call_args
        assert kwargs["filters"] == {
            "status": "OPEN",
            "is_active": "true",
            "company_id": "c-1",
            "date_field": "updated_at",
            "from_date": "2026-01-01",
            "to_date": "2026-08-01",
            "limit": "50",
        }

    def test_export_blank_filter_values_are_dropped(self, staff_client, mocker):
        """?status=&company_id= (select "Tất cả"/"bỏ trống") KHÔNG được
        forward thành filter thật — chuỗi rỗng nghĩa là "không lọc field
        này", khác hẳn lọc theo giá trị rỗng."""
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        export_mock = mocker.patch(
            "blueprints.data_management.db_data.export_entity",
            return_value=(b"", "job_export.xlsx", "application/vnd.openxmlformats"),
        )
        staff_client.get("/data-management/export/job?status=&company_id=")
        _, kwargs = export_mock.call_args
        assert kwargs["filters"] == {}


class TestExportPreview:
    """export_preview_route() — AJAX, staff bấm "Xem trước" ở
    _dm_export.html trước khi tải file thật (thêm 08/2026)."""

    def test_preview_success_returns_json(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.data_management.db_data.export_preview",
            return_value={
                "entity_type": "job",
                "total_matching": 5,
                "will_export": 5,
                "columns": ["job_id", "job_title"],
                "sample_rows": [{"job_id": "j-1", "job_title": "Backend Dev"}],
            },
        )
        resp = staff_client.get(
            "/data-management/export/job/preview?status=OPEN",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 200
        assert resp.content_type.startswith("application/json")
        data = resp.get_json()
        assert data["total_matching"] == 5
        assert data["sample_rows"][0]["job_id"] == "j-1"

    def test_preview_forwards_filters_to_client(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        preview_mock = mocker.patch(
            "blueprints.data_management.db_data.export_preview",
            return_value={"entity_type": "job", "total_matching": 0, "will_export": 0,
                          "columns": [], "sample_rows": []},
        )
        staff_client.get(
            "/data-management/export/job/preview?status=CLOSED&limit=10",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        _, kwargs = preview_mock.call_args
        assert kwargs["filters"] == {"status": "CLOSED", "limit": "10"}

    def test_preview_invalid_entity_type_returns_json_404(self, staff_client, mocker):
        """Regression test: entity_type sai TRƯỚC ĐÂY dùng abort(404),
        route AJAX này trả HTML lỗi mặc định của Flask thay vì JSON —
        khiến fetch().then(res => res.json()) ở _dm_export.html crash.
        Route AJAX phải LUÔN trả JSON, kể cả lỗi 404."""
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        resp = staff_client.get(
            "/data-management/export/not-a-real-entity/preview",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 404
        assert resp.content_type.startswith("application/json")
        assert "error" in resp.get_json()

    def test_preview_backend_error_returns_json_with_status_code(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.data_management.db_data.export_preview",
            side_effect=CrawlerAPIError("status 'BOGUS' không hợp lệ", status_code=400),
        )
        resp = staff_client.get(
            "/data-management/export/job/preview?status=BOGUS",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "status 'BOGUS' không hợp lệ"

    def test_preview_not_logged_in_returns_json_not_html(self, client, mocker):
        """staff_required() đã tự xử lý case này (xem utils/decorators.py
        _wants_json()) — test khẳng định lại hành vi cho riêng route mới
        này, vì đây chính là lỗi vừa sửa ở entity_type sai phía trên."""
        resp = client.get(
            "/data-management/export/job/preview",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 401
        assert resp.content_type.startswith("application/json")


class TestImportPreview:
    def test_no_file_uploaded_flashes_error(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        resp = staff_client.post(
            "/data-management/import/job/preview", data={}, follow_redirects=False
        )
        assert resp.status_code == 302
        assert "tab=import" in resp.headers["Location"]

    def test_successful_preview_redirects_with_preview_id(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.data_management.db_data.import_preview",
            return_value={
                "preview_id": "prev-123",
                "total_rows": 10,
                "new_count": 7,
                "conflict_count": 2,
                "conflict_inactive_count": 1,
            },
        )
        data = {"file": (io.BytesIO(b"fake,csv,data"), "jobs.csv")}
        resp = staff_client.post(
            "/data-management/import/job/preview",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "preview=prev-123" in resp.headers["Location"]

    def test_invalid_entity_type_404(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        data = {"file": (io.BytesIO(b"x"), "x.csv")}
        resp = staff_client.post(
            "/data-management/import/not-a-real-entity/preview",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 404


class TestVerifyField:
    """verify_field() cố ý dùng _call_authed thay vì gọi thẳng như
    company_suggestions() (bản cũ, thiếu refresh) — test đảm bảo route
    MỚI này thực sự tự refresh khi 401, không lặp lại bug cũ."""

    def test_missing_preview_id_returns_400(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        resp = staff_client.post(
            "/data-management/import/job/verify-field",
            json={"field_name": "level_code", "value": "Junior", "row_index": 0},
        )
        assert resp.status_code == 400

    def test_success_path(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.data_management.db_data.get_import_preview",
            return_value={"id_field": "job_id"},
        )
        mocker.patch(
            "blueprints.data_management.db_data.verify_field",
            return_value={"ok": True, "row_index": 0},
        )
        resp = staff_client.post(
            "/data-management/import/job/verify-field",
            json={
                "preview_id": "prev-1", "field_name": "level_code",
                "value": "Junior", "row_index": 0,
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_401_triggers_refresh_transparently(self, staff_client, mocker):
        """Đây là bài test cốt lõi của route này: access token hết hạn
        giữa chừng -> _call_authed tự refresh -> route vẫn trả 200,
        KHÔNG crash 500 như bug lịch sử của bản _call_authed cũ."""
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.data_management.db_data.get_import_preview",
            return_value={"id_field": "job_id"},
        )
        mocker.patch(
            "helpers.backend_auth.refresh",
            return_value={"access_token": "new-tok", "refresh_token": "new-refresh"},
        )

        call_count = {"n": 0}

        def verify_field_side_effect(token, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise CrawlerAPIError("hết hạn", status_code=401)
            return {"ok": True}

        mocker.patch(
            "blueprints.data_management.db_data.verify_field",
            side_effect=verify_field_side_effect,
        )

        resp = staff_client.post(
            "/data-management/import/job/verify-field",
            json={
                "preview_id": "prev-1", "field_name": "level_code",
                "value": "Junior", "row_index": 0,
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert call_count["n"] == 2


class TestImportConfirm:
    def test_missing_import_note_flashes_error(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        resp = staff_client.post(
            "/data-management/import/job/confirm",
            data={"preview_id": "prev-1", "resolutions": "[]", "import_note": ""},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "tab=import" in resp.headers["Location"]

    def test_invalid_resolutions_json_flashes_error(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        resp = staff_client.post(
            "/data-management/import/job/confirm",
            data={
                "preview_id": "prev-1", "resolutions": "{not valid json",
                "import_note": "ghi chú",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_success_redirects_to_import_tab(self, staff_client, mocker):
        # Sửa 08/2026 (staff báo bất tiện): TRƯỚC ĐÂY redirect về tab=export
        # sau khi import thành công — staff cần import nhiều lượt liên tiếp
        # phải tự bấm lại tab "Nhập dữ liệu" mỗi lần. Giờ ở lại tab=import
        # (test này ĐÃ ĐỔI assertion so với bản cũ test_success_redirects_
        # to_export_tab — đây là thay đổi hành vi CÓ CHỦ ĐÍCH, không phải
        # regression).
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.data_management.db_data.import_confirm",
            return_value={"created": 5, "updated": 2, "skipped": 1, "errors": []},
        )
        resp = staff_client.post(
            "/data-management/import/job/confirm",
            data={
                "preview_id": "prev-1", "resolutions": "[]",
                "import_note": "import tuần này",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "tab=import" in resp.headers["Location"]
