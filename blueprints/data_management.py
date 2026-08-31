"""Data Management blueprint - import/export functionality"""

import json

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

import crawler_client as db_data
from crawler_client import CrawlerAPIError
from helpers import _call_authed
from utils.decorators import staff_required

data_mgmt_bp = Blueprint("data_mgmt", __name__)

# Filter export thêm 08/2026 — khoá query param dùng chung giữa form filter
# (_dm_export.html), route preview AJAX, và route tải file thật bên dưới.
# Giữ 1 danh sách DUY NHẤT ở đây để 3 chỗ không tự gõ tay tên field lệch
# nhau (vd 1 nơi gõ "companyId" nơi khác "company_id").
_EXPORT_FILTER_PARAM_KEYS = (
    "status", "is_active", "company_id", "date_field", "from_date", "to_date", "limit",
)


def _parse_export_filters(args):
    """Đọc filter export từ query string (?status=...&from_date=...) ->
    dict CHỈ gồm key có giá trị thật (bỏ trống = không lọc field đó) —
    dùng chung cho route preview AJAX và route tải file thật, đảm bảo
    "xem preview thấy gì thì tải đúng cái đó" (cùng 1 hàm parse, không
    viết 2 lần dễ lệch nhau).

    is_active nhận "true"/"false" từ <select> — KHÁC mọi filter khác
    (chuỗi thô forward thẳng), cần convert vì backend (FastAPI
    Query(bool)) nhận qua query string vẫn parse được "true"/"false" nên
    thực ra không cần convert kiểu ở đây, chỉ cần đảm bảo giá trị rỗng
    ("" — nghĩa là "Cả 2", không lọc) bị loại bỏ như filter khác."""
    filters = {}
    for key in _EXPORT_FILTER_PARAM_KEYS:
        value = (args.get(key) or "").strip()
        if value:
            filters[key] = value
    return filters


@data_mgmt_bp.route("/data-management")
@staff_required
def index():
    """Trang chọn entity (Job/Company/Contact) + tab Export/Import.

    Query params:
      entity: "job" | "company" | "contact" (mặc định "job")
      tab: "export" | "import" (mặc định "export")
      preview: preview_id — nếu có, load lại preview đã tạo
    """
    entity_type = request.args.get("entity", "job")
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        entity_type = "job"
    tab = request.args.get("tab", "export")
    if tab not in ("export", "import"):
        tab = "export"

    preview = None
    preview_id = request.args.get("preview", "")
    if preview_id:
        try:
            # _call_authed (KHÔNG gọi thẳng access_token) — sửa 08/2026, bug
            # đã biết: gọi thẳng access_token không tự refresh khi hết hạn
            # (30 phút), khiến staff bị flash "phiên hết hạn" giữa lúc thao
            # tác Data Management dù cookie đăng nhập vẫn còn nguyên. Xem
            # helpers.py::_call_authed docstring + lịch sử trao đổi "hay bị
            # kick khỏi acc khi chạy vài script bên vận hành dữ liệu".
            preview = _call_authed(db_data.get_import_preview, entity_type, preview_id)
            if preview is None:
                flash("Bản xem trước đã hết hạn hoặc không tồn tại — vui lòng tải file lên lại.", "error")
        except CrawlerAPIError as exc:
            flash(str(exc), "error")

    # enums.get_enums() cache TTL 5 phút (crawler_client/enums.py) — không
    # round-trip mạng riêng cho job_status/contact_status ở đây, tái dùng
    # đúng cache đã có sẵn cho level_code_values bên dưới.
    enums = db_data.get_enums()

    return render_template(
        "data_management.html",
        entity_type=entity_type,
        entity_types=db_data.IMPORT_EXPORT_ENTITY_TYPES,
        entity_labels=db_data.IMPORT_EXPORT_ENTITY_LABELS,
        tab=tab,
        preview=preview,
        preview_id=preview_id,
        # Nguồn 7 giá trị level_code hợp lệ cho dropdown "chọn lại level"
        # ở bước Import (chỉ Job, dòng needs_level_resolve — xem
        # _dm_import.html) — lấy qua get_level_codes() (GET /enums, cache
        # TTL 5 phút phía crawler_client.py), tự đồng bộ với backend thay
        # vì hardcode tĩnh như trước 08/2026.
        level_code_values=db_data.get_level_codes(),
        # Filter export (thêm 08/2026, chỉ dùng khi tab == "export") —
        # job_status/contact_status cho dropdown "Trạng thái", companies
        # cho ô chọn công ty (tái dùng _company_combobox.html, cùng
        # combobox đang dùng ở add_job.html/add_contact.html — công ty ở
        # đây KHÔNG bắt buộc chọn, khác 2 trang kia). Chỉ tải khi đang ở
        # tab export để không tốn round-trip /companies thừa lúc staff
        # đang xem tab import.
        job_status_values=enums.get("job_status", []),
        contact_status_values=enums.get("contact_status", []),
        # Nhãn tiếng Việt cho từng status value ở trên — TÁI DÙNG
        # JOB_STATUS_MAP/CONTACT_STATUS_MAP đã có sẵn (jobs.py/contacts.py,
        # dùng để hiển thị badge trạng thái ở trang danh sách), KHÔNG viết
        # tay lại map thứ 3 riêng cho dropdown filter export.
        job_status_labels=db_data.JOB_STATUS_MAP,
        contact_status_labels=db_data.CONTACT_STATUS_MAP,
        export_companies=db_data.list_all_companies() if tab == "export" else [],
    )


@data_mgmt_bp.route("/data-management/export/<string:entity_type>")
@staff_required
def export(entity_type):
    """Tải file export — gọi trực tiếp bằng GET (link/button JS set
    window.location, KHÔNG phải AJAX — trình duyệt tự xử lý tải file từ
    response Content-Disposition: attachment).

    Nhận THÊM bộ query params filter (status/is_active/company_id/
    date_field/from_date/to_date/limit, xem _parse_export_filters()) —
    FE (_dm_export.html) luôn gọi route này với ĐÚNG filter vừa xem ở
    bước preview (cùng querystring), không tự thêm/bớt gì ở giữa."""
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        abort(404)
    file_format = request.args.get("format", "xlsx")
    if file_format not in ("xlsx", "csv"):
        file_format = "xlsx"
    filters = _parse_export_filters(request.args)

    try:
        content, filename, content_type = _call_authed(
            db_data.export_entity, entity_type, file_format, filters=filters
        )
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("data_mgmt.index", entity=entity_type, tab="export"))

    return Response(
        content,
        mimetype=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@data_mgmt_bp.route("/data-management/export/<string:entity_type>/preview")
@staff_required
def export_preview_route(entity_type):
    """AJAX — staff bấm "Xem trước" trên form filter (_dm_export.html)
    -> gọi backend GET /export/{entity_type}/preview với ĐÚNG bộ filter
    hiện có trên form -> trả JSON (total_matching/will_export/columns/
    sample_rows) để JS render bảng preview tại chỗ, KHÔNG reload trang
    (đã chốt dùng AJAX, cùng trải nghiệm với các thao tác preview đang
    có ở tab Import — xem trao đổi thiết kế 08/2026).

    Tên hàm route cố ý là export_preview_route (không phải export_preview)
    để tránh trùng tên với db_data.export_preview import vào — 2 hàm
    KHÔNG xung đột namespace thật (Flask chỉ dùng tên hàm cho
    url_for('data_mgmt.export_preview_route'), db_data.export_preview
    luôn gọi qua module prefix), nhưng đặt tên khác cho rõ ràng khi đọc
    code, đỡ nhầm "đang gọi route hay đang gọi hàm client".

    entity_type sai trả JSON 404 (KHÔNG dùng abort(404) như export()
    bên trên) — đây là route AJAX, abort() trả trang lỗi HTML mặc định
    của Flask, khiến fetch().then(res => res.json()) ở _dm_export.html
    crash vì cố parse HTML như JSON (cùng lý do staff_required() đã xử
    lý riêng cho case chưa đăng nhập, xem utils/decorators.py)."""
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        return jsonify({"error": "entity_type không hợp lệ."}), 404
    filters = _parse_export_filters(request.args)

    try:
        preview = _call_authed(db_data.export_preview, entity_type, filters=filters)
        return jsonify(preview)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)


@data_mgmt_bp.route("/data-management/import/<string:entity_type>/preview", methods=["POST"])
@staff_required
def import_preview(entity_type):
    """Bước 1: nhận file upload -> gọi backend preview -> redirect sang
    tab import kèm ?preview=<preview_id> để render bảng preview."""
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        abort(404)

    file_storage = request.files.get("file")
    if not file_storage or not file_storage.filename:
        flash("Vui lòng chọn file CSV/XLSX để tải lên.", "error")
        return redirect(url_for("data_mgmt.index", entity=entity_type, tab="import"))

    try:
        preview = _call_authed(db_data.import_preview, entity_type, file_storage)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("data_mgmt.index", entity=entity_type, tab="import"))

    # Không hiện "N lỗi" ở đây (khác bản cũ) — cùng lý do đã bỏ ô "Dòng
    # lỗi" khỏi _dm_import.html: preview['error_count'] luôn = 0 vì file
    # có dòng lỗi bị chặn NGUYÊN FILE ở bước upload (422) trước khi tới
    # được đây, không phải giá trị thật phản ánh dòng nào trong preview.
    flash(
        f"Đã đọc {preview['total_rows']} dòng — {preview['new_count']} dòng mới, "
        f"{preview['conflict_count']} trùng, {preview['conflict_inactive_count']} trùng bản ghi "
        f"ngừng hoạt động.",
        "success",
    )
    return redirect(url_for(
        "data_mgmt.index", entity=entity_type, tab="import", preview=preview["preview_id"]
    ))


@data_mgmt_bp.route("/data-management/import/<string:entity_type>/company-suggestions")
@staff_required
def company_suggestions(entity_type):
    """AJAX endpoint — trả JSON danh sách company gợi ý cho 1 dòng cụ thể"""
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        abort(404)
    preview_id = request.args.get("preview_id", "")
    try:
        row_index = int(request.args.get("row_index", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "row_index không hợp lệ"}), 400

    try:
        # _call_authed — sửa 08/2026 (trước đây gọi thẳng access_token, bản
        # CŨ thiếu logic tự refresh token hết hạn; xem helpers.py::
        # _call_authed docstring + lịch sử trao đổi "hay bị kick khỏi acc").
        suggestions = _call_authed(db_data.get_company_suggestions, entity_type, preview_id, row_index)
        return jsonify({"suggestions": suggestions})
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)


@data_mgmt_bp.route("/data-management/import/<string:entity_type>/verify-field", methods=["POST"])
@staff_required
def verify_field(entity_type):
    """AJAX endpoint — staff sửa 1 ô lỗi trên bảng preview, bấm nút "Xác
    nhận" cạnh ô đó -> gọi backend re-validate + (contact) re-check trùng
    mờ ngay tại đó, KHÔNG đợi tới bước confirm cuối (xem trao đổi thiết kế
    "cảnh báo trùng contact sau khi sửa field lỗi", 08/2026).

    Dùng _call_authed (tự refresh token hết hạn) — cùng cách company_
    suggestions() ở trên đang làm từ 08/2026 (trước đó gọi thẳng
    access_token, là bug đã biết, xem helpers.py::_call_authed docstring +
    lịch sử trao đổi "hay bị kick khỏi acc khi chạy vài script bên vận
    hành dữ liệu")."""
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        abort(404)

    payload = request.get_json(silent=True) or {}
    preview_id = payload.get("preview_id", "")
    field_name = payload.get("field_name", "")
    value = payload.get("value", "")
    try:
        row_index = int(payload.get("row_index"))
    except (TypeError, ValueError):
        return jsonify({"error": "row_index không hợp lệ"}), 400

    if not preview_id or not field_name:
        return jsonify({"error": "Thiếu preview_id hoặc field_name"}), 400

    # id_field: lấy từ preview đã load trước đó (đọc lại preview 1 lần từ
    # backend — KHÔNG lưu id_field vào session để tránh lệch dữ liệu nếu
    # preview đổi giữa chừng) để _normalize_preview_row() tính đúng
    # existing_id nếu dòng chuyển sang trạng thái "conflict" (khớp cách
    # get_import_preview() ở index() đang làm).
    try:
        # _call_authed — cùng lý do sửa ở index()/company_suggestions() phía
        # trên (bug: gọi thẳng access_token không tự refresh khi hết hạn).
        preview = _call_authed(db_data.get_import_preview, entity_type, preview_id)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)
    id_field = preview["id_field"] if preview else None

    try:
        result = _call_authed(
            db_data.verify_field, entity_type, preview_id, row_index, field_name, value,
            id_field=id_field,
        )
        return jsonify(result)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)


@data_mgmt_bp.route("/data-management/import/<string:entity_type>/resolve-company", methods=["POST"])
@staff_required
def resolve_company(entity_type):
    """AJAX endpoint — staff chọn 1 công ty (hoặc "Tạo công ty mới") trong
    modal chọn công ty ở bước preview -> gọi backend re-check trùng NGAY
    với company_id thật vừa chọn, KHÔNG chỉ đổi state cục bộ ở FE nữa
    (08/2026, xem trao đổi thiết kế "vấn đề 2 & 3" — bug khiến UI hiện
    "Sẽ tạo mới" cho dòng thật ra trùng, action ngầm gửi lên vẫn "skip").

    Cùng pattern verify_field() ở trên (_call_authed để tự refresh token
    hết hạn, tự đọc lại preview để lấy id_field truyền vào
    _normalize_preview_row())."""
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        abort(404)

    payload = request.get_json(silent=True) or {}
    preview_id = payload.get("preview_id", "")
    company_id = payload.get("company_id")
    try:
        row_index = int(payload.get("row_index"))
    except (TypeError, ValueError):
        return jsonify({"error": "row_index không hợp lệ"}), 400

    if not preview_id:
        return jsonify({"error": "Thiếu preview_id"}), 400

    try:
        # _call_authed — cùng lý do sửa ở index()/company_suggestions() phía
        # trên (bug: gọi thẳng access_token không tự refresh khi hết hạn).
        preview = _call_authed(db_data.get_import_preview, entity_type, preview_id)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)
    id_field = preview["id_field"] if preview else None

    try:
        result = _call_authed(
            db_data.resolve_company, entity_type, preview_id, row_index, company_id,
            id_field=id_field,
        )
        return jsonify(result)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)


@data_mgmt_bp.route("/data-management/import/<string:entity_type>/confirm", methods=["POST"])
@staff_required
def import_confirm(entity_type):
    """Bước 2: nhận resolution map + import_note -> gọi backend confirm"""
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        abort(404)

    preview_id = request.form.get("preview_id", "")
    import_note = request.form.get("import_note", "").strip()
    resolutions_raw = request.form.get("resolutions", "[]")

    if not import_note:
        flash("Vui lòng nhập ghi chú (import note) trước khi xác nhận.", "error")
        return redirect(url_for("data_mgmt.index", entity=entity_type, tab="import", preview=preview_id))

    try:
        resolutions = json.loads(resolutions_raw)
    except (TypeError, ValueError):
        flash("Dữ liệu lựa chọn từng dòng bị lỗi định dạng — vui lòng thử lại.", "error")
        return redirect(url_for("data_mgmt.index", entity=entity_type, tab="import", preview=preview_id))

    try:
        result = _call_authed(db_data.import_confirm, entity_type, preview_id, resolutions, import_note)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("data_mgmt.index", entity=entity_type, tab="import", preview=preview_id))

    # Lưu ý: backend (ImportConfirmResult) gộp chung "reactivate" vào
    # "updated", không trả đếm riêng — result["reactivated"] hiện luôn =
    # 0 phía crawler_client.py (xem docstring import_confirm() ở đó),
    # nên KHÔNG hiện dòng "Kích hoạt lại: 0" gây hiểu nhầm là không có
    # dòng nào được kích hoạt lại; số kích hoạt lại (nếu có) đã nằm
    # trong "Cập nhật" ở trên.
    msg = (
        f"Import hoàn tất — Tạo mới: {result['created']}, Cập nhật: {result['updated']}, "
        f"Bỏ qua: {result['skipped']}."
    )
    if result["errors"]:
        msg += f" ({len(result['errors'])} dòng lỗi, xem chi tiết bên dưới.)"
        flash(msg, "error")
    else:
        flash(msg, "success")

    # Sửa 08/2026 (staff báo bất tiện): TRƯỚC ĐÂY redirect về tab="export"
    # sau khi import xong — staff cần import nhiều lượt liên tiếp phải tự
    # bấm lại tab "Nhập dữ liệu" mỗi lần. Ở lại đúng tab "import" (trang
    # sẽ hiện lại form upload rỗng vì không còn truyền preview= trên URL,
    # sẵn sàng cho lượt import tiếp theo ngay).
    return redirect(url_for("data_mgmt.index", entity=entity_type, tab="import"))
