"""
Import / Export (trang /data-management)

ENTITY_TYPE dùng trong path: "job" | "company" | "contact" (chữ
thường, số ít — khác audit_logs.ENTITY_TYPE_MAP vốn dùng cho audit log,
key "JOB"/"COMPANY"/"CONTACT" chữ hoa; 2 map KHÔNG dùng lẫn nhau).
"""

import requests

from .base import CRAWLER_API_URL, REQUEST_TIMEOUT, CrawlerAPIError, _headers, _request

IMPORT_EXPORT_ENTITY_TYPES = ["job", "company", "contact"]
IMPORT_EXPORT_ENTITY_LABELS = {"job": "JD", "company": "Công ty", "contact": "Người liên hệ HR"}

# Nhãn hiển thị cho conflict_status trả về từ conflict_detector backend
# (xem preview row "conflict_status" bên dưới) — 4 trạng thái thật sự trả
# về bởi api/services/preview_manager.py + conflict_detector.py (đã đối
# chiếu lại với backend 08/2026, KHÁC với bản nháp contract cũ 3 trạng
# thái "new"/"conflict"/"conflict_inactive" từng viết ở đây trước khi
# backend triển khai xong):
#   - "no_conflict": không trùng, tạo mới bình thường
#   - "conflict": trùng với bản ghi ĐANG active (cho chọn Skip/Update/Create)
#   - "conflict_inactive": trùng với bản ghi INACTIVE/CLOSED/EXPIRED (cảnh
#     báo riêng, hỏi có ghi đè + kích hoạt lại không)
#   - "pending_company_resolution": (chỉ Job/Contact) company_name trong
#     file chưa map thẳng ra được company_id, cần staff tự chọn
CONFLICT_STATUS_LABELS = {
    "no_conflict": "Dòng mới",
    "conflict": "Trùng dữ liệu",
    "conflict_inactive": "Trùng — bản ghi đã ngừng hoạt động",
    "pending_company_resolution": "Cần chọn công ty",
}


def export_entity(access_token, entity_type, file_format="xlsx"):
    """GET /export/{entity_type} — trả file nhị phân (CSV hoặc XLSX).

    Khác mọi hàm khác trong package này: trả về (content_bytes, filename,
    content_type) thay vì dict đã chuẩn hoá, vì đây là file tải xuống
    thẳng cho user (app.py dùng send_file/Response), không phải data
    hiển thị trên UI. Raise CrawlerAPIError nếu backend lỗi — app.py tự
    bắt và flash, KHÔNG trả file rỗng để tránh user tải nhầm file hỏng."""
    url = f"{CRAWLER_API_URL}/export/{entity_type}"
    try:
        res = requests.get(
            url, headers=_headers(access_token), params={"format": file_format},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise CrawlerAPIError(f"Không kết nối được tới backend ({url}): {exc}") from exc

    if not res.ok:
        try:
            detail = res.json().get("detail", "") or ""
        except Exception:
            detail = res.text[:300]
        raise CrawlerAPIError(f"Xuất file thất bại ({res.status_code}): {detail}", status_code=res.status_code)

    content_type = res.headers.get("Content-Type", "application/octet-stream")
    # Backend nên trả Content-Disposition kèm filename gợi ý; nếu thiếu,
    # tự đặt tên theo đúng convention Requirement 1.9 (đã chốt) làm dự
    # phòng — KHÔNG để app.py phải tự đoán tên file.
    disposition = res.headers.get("Content-Disposition", "")
    filename = None
    if "filename=" in disposition:
        filename = disposition.split("filename=")[-1].strip('"; ')
    if not filename:
        ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = "xlsx" if file_format == "xlsx" else "csv"
        filename = f"{entity_type}_export_{ts}.{ext}"
    return res.content, filename, content_type


def _normalize_preview_row(raw: dict, id_field: str | None = None) -> dict:
    # Backend (api/services/preview_manager.py::build_preview) trả field
    # "existing_record" (không tách existing_data/existing_id riêng) và
    # "company_resolution": {"status": "resolved"|"needs_resolution",
    # "company_id", "company_is_active", "suggestions": [...]}  (không
    # phải "needs_company_resolve"/"resolved_company_id" phẳng như bản
    # nháp contract cũ) — đối chiếu lại 08/2026, sửa cho khớp thật.
    # needs_field_fix/field_errors (thêm 08/2026 — xem preview_manager.py
    # docstring): field lỗi type/required/business-rule KHÔNG còn chặn
    # nguyên file ở bước upload nữa (trừ required_column_missing, vẫn
    # reject cứng ở import_preview() bên dưới) — pass-through nguyên 2
    # field này để _dm_import.html render ô sửa tại chỗ trên bảng
    # preview, KHÔNG transform gì thêm (widget_type/options đã tính sẵn
    # ở backend, xem entity_specs.field_widget_type/field_options).
    #
    # id_field: tên cột PK thật của entity (vd "job_id") — LẤY TỪ
    # summary.id_field mà backend trả về (xem EntitySpec.id_field,
    # api/services/entity_specs.py backend + _normalize_preview_summary()
    # bên dưới, nơi gọi hàm này), KHÔNG tự đoán bằng map hardcode
    # entity_type -> tên cột id ở tầng gọi (bản cũ ở đây từng có 1 dict
    # {"job": "job_id", "company": "company_id", "contact": "contact_id"}
    # ngay trong hàm — dễ quên cập nhật khi thêm entity mới, vì nó không
    # nằm cạnh IMPORT_EXPORT_ENTITY_TYPES/CONFLICT_STATUS_LABELS là chỗ
    # người sửa code tự nhiên nghĩ tới. Giờ backend là nguồn sự thật duy
    # nhất cho tên cột id, module này chỉ đọc lại).
    company_resolution = raw.get("company_resolution") or {}
    status = raw.get("conflict_status") or "no_conflict"
    existing_record = raw.get("existing_record")
    return {
        "row_index": raw.get("row_index"),
        "data": raw.get("data") or {},
        "conflict_status": status,
        "conflict_status_label": CONFLICT_STATUS_LABELS.get(status, status),
        "existing_data": existing_record,
        "existing_id": (existing_record.get(id_field) if id_field else None) if existing_record else None,
        "needs_company_resolve": status == "pending_company_resolution",
        "resolved_company_id": company_resolution.get("company_id"),
        "resolved_company_name": company_resolution.get("company_name"),
        "company_suggestions": company_resolution.get("suggestions") or [],
        # needs_level_resolve/level_code_raw (chỉ Job, 08/2026 — xem
        # preview_manager.py::build_preview): TRỤC ĐỘC LẬP với
        # conflict_status/needs_company_resolve ở trên — 1 dòng "no_conflict"
        # vẫn có thể cần chọn lại level (level_code trong file không khớp
        # 1 trong 7 giá trị hợp lệ dù đã chuẩn hoá hoa/thường), nên KHÔNG
        # gộp vào conflict_status_label như 1 trạng thái riêng.
        "needs_level_resolve": bool(raw.get("needs_level_resolve")),
        "level_code_raw": raw.get("level_code_raw"),
        "needs_field_fix": bool(raw.get("needs_field_fix")),
        # field_errors: {field_name: {"rule","message","raw_value",
        # "widget_type","options"}} — {} nếu needs_field_fix=false. Giữ
        # nguyên key/shape backend trả, _dm_import.html đọc thẳng field
        # này (widget_type quyết định select/input type=date/input số/
        # input chữ, options chỉ có giá trị khi widget_type=="enum").
        "field_errors": raw.get("field_errors") or {},
        # duplicate_match (08/2026, chỉ Contact — xem preview_manager.py::
        # apply_field_fix() backend): chỉ có giá trị khi conflict_status
        # "conflict" được set NGAY LÚC re-check trùng mờ tại chỗ (khác
        # conflict phát hiện lúc build preview ban đầu, vốn không có field
        # này) — {"match_score": 0.33/0.67/1.0, "matched_fields": [...]}.
        # Pass-through nguyên shape backend trả, _dm_import.html tự hiện
        # badge độ tin cậy match cạnh trạng thái "Trùng".
        "duplicate_match": raw.get("duplicate_match"),
        "errors": [],
    }


def _normalize_preview_summary(raw: dict) -> dict:
    # Backend (ImportUploadResponse, api/schemas.py) lồng các số đếm
    # trong "summary" — KHÔNG ở top-level — và dùng tên field khác:
    # total_rows / new_records / conflicts / conflicts_inactive /
    # pending_company_resolution / id_field (xem preview_manager.py::
    # build_preview). Bản cũ ở đây đọc raw.get("total_rows"/"new_count"/
    # ...) thẳng ở top-level -> luôn miss, luôn fallback 0 (bug đã xác
    # nhận 08/2026).
    summary = raw.get("summary") or {}
    entity_type = raw.get("entity_type")
    id_field = summary.get("id_field")
    rows = [_normalize_preview_row(r, id_field=id_field) for r in raw.get("rows", [])]
    return {
        "preview_id": raw.get("preview_id"),
        "entity_type": entity_type,
        "id_field": id_field,
        "total_rows": summary.get("total_rows", 0),
        "new_count": summary.get("new_records", 0),
        "conflict_count": summary.get("conflicts", 0),
        "conflict_inactive_count": summary.get("conflicts_inactive", 0),
        "error_count": summary.get("errors", 0),
        "needs_company_resolve_count": summary.get("pending_company_resolution", 0),
        "needs_level_resolve_count": summary.get("pending_level_resolution", 0),
        # pending_field_fix_count (thêm 08/2026, xem preview_manager.py):
        # tổng số dòng có needs_field_fix=true trong preview này — dùng
        # để hiện ô thống kê "Cần sửa dữ liệu" trên _dm_import.html giống
        # cách needs_company_resolve_count/needs_level_resolve_count đã
        # hiện (chỉ hiện ô khi > 0, xem template).
        "needs_field_fix_count": summary.get("pending_field_fix", 0),
        "expires_at": raw.get("expires_at"),
        "rows": rows,
    }


def _format_import_errors_detail(detail) -> str:
    """Backend (api/routers/import_export.py::import_preview) là DUY NHẤT
    chỗ trả HTTPException.detail dạng OBJECT thay vì string trong toàn bộ
    backend (đã grep 'detail={' khắp api/routers/, chỉ có đúng 1 kết quả)
    — mọi route khác luôn trả detail dạng string thuần, các hàm khác
    trong package này (đọc res.json().get("detail","") rồi dùng thẳng) vẫn
    đúng, KHÔNG cần đổi.

    Shape thật của detail khi file có dòng validate lỗi (422):
        {"message": "File có dòng không hợp lệ...",
         "errors": [{"row_number": int, "field_name": str, "rule": str,
                      "message": str}, ...]}

    BUG (08/2026, phát hiện qua ảnh chụp màn hình staff báo lỗi import
    contact): import_preview() cũ gán thẳng
    `detail = res.json().get("detail", "")` (ra 1 dict) rồi nhét vào
    f-string `f"File không hợp lệ: {detail}"` — Python f-string gọi
    str(dict) trên 1 dict lồng list-of-dict -> in NGUYÊN literal Python
    (`{'message': ..., 'errors': [{'row_number': 4, ...}]}`) thẳng ra
    flash message cho staff xem, không ai đọc nổi — dù nội dung lỗi bên
    trong (mỗi error["message"]) thật ra đã viết sẵn dạng câu tiếng Việt
    dễ hiểu ("Dòng 4, cột 'work_email': email không hợp lệ ...").

    Hàm này tách riêng để format lại: nối error["message"] (ĐÃ viết sẵn
    dễ đọc, không cần tự dựng câu từ row_number/field_name/rule) mỗi lỗi
    1 dòng, giới hạn hiện tối đa 20 dòng đầu (file cho phép tới 5.000
    dòng — lỗi hàng loạt kiểu sai nguyên 1 cột thì in hết ra vô ích, tràn
    màn hình) + báo còn bao nhiêu lỗi khác nếu vượt quá. Nếu detail không
    phải dict (route khác, hoặc backend đổi shape) -> trả thẳng str(detail)
    làm fallback an toàn, không throw."""
    if not isinstance(detail, dict):
        return str(detail)
    message = detail.get("message") or "File có dòng không hợp lệ."
    errors = detail.get("errors") or []
    if not errors:
        return message
    MAX_SHOWN = 20
    lines = [message]
    for err in errors[:MAX_SHOWN]:
        err_message = err.get("message")
        if err_message:
            lines.append(f"- {err_message}")
        else:
            # Fallback nếu backend đổi shape sau này, thiếu sẵn "message"
            # cho 1 error entry — vẫn dựng được câu tối thiểu từ 3 field
            # còn lại thay vì bỏ trống dòng đó.
            row = err.get("row_number", "?")
            field = err.get("field_name", "?")
            rule = err.get("rule", "?")
            lines.append(f"- Dòng {row}, cột '{field}' (rule={rule}): không hợp lệ")
    if len(errors) > MAX_SHOWN:
        lines.append(f"... và {len(errors) - MAX_SHOWN} dòng lỗi khác.")
    return "\n".join(lines)


def import_preview(access_token, entity_type, file_storage):
    """POST /import/{entity_type}/preview — upload file (multipart), trả
    preview_id + summary (đếm dòng mới/conflict/lỗi) + toàn bộ rows để
    FE render bảng (bảng có thể tới 5000 dòng theo giới hạn file_parser
    backend — phân trang do JS phía template tự làm, KHÔNG phân trang
    ở tầng gọi API này).

    file_storage: werkzeug.datastructures.FileStorage (từ
    request.files["file"] trong route Flask) — đọc thẳng .stream/.filename,
    KHÔNG cần lưu ra đĩa trước."""
    url = f"{CRAWLER_API_URL}/import/{entity_type}/preview"
    files = {"file": (file_storage.filename, file_storage.stream, file_storage.mimetype)}
    try:
        res = requests.post(url, headers=_headers(access_token), files=files, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        raise CrawlerAPIError(f"Không kết nối được tới backend ({url}): {exc}") from exc

    if res.ok:
        return _normalize_preview_summary(res.json())

    try:
        detail = res.json().get("detail", "") or ""
    except Exception:
        detail = res.text[:300]
    if res.status_code == 401:
        raise CrawlerAPIError(detail or "Chưa đăng nhập hoặc phiên đã hết hạn.", status_code=401)
    if res.status_code == 403:
        raise CrawlerAPIError(detail or "Tài khoản không có quyền thực hiện thao tác này.", status_code=403)
    if res.status_code == 422:
        raise CrawlerAPIError(f"File không hợp lệ: {_format_import_errors_detail(detail)}", status_code=422)
    raise CrawlerAPIError(f"Backend lỗi {res.status_code} khi đọc preview: {detail}", status_code=res.status_code)


def get_import_preview(access_token, entity_type, preview_id):
    """GET /import/{entity_type}/preview/{preview_id} — lấy lại preview đã
    tạo (vd sau khi reload trang, hoặc load lại để render bảng phân
    trang phía JS mà không cần re-upload file). Trả None nếu preview đã
    hết hạn (TTL 1h) hoặc không thuộc user hiện tại — backend trả 404
    cho cả 2 case này để không lộ preview_id của người khác tồn tại hay
    không (_request() có sẵn coi 404 = None)."""
    raw = _request("GET", f"/import/{entity_type}/preview/{preview_id}", access_token=access_token)
    return _normalize_preview_summary(raw) if raw is not None else None


def get_company_suggestions(access_token, entity_type, preview_id, row_index):
    """GET /import/{entity_type}/preview/{preview_id}/company-suggestions?row_index=
    — danh sách công ty gợi ý (fuzzy match) cho 1 dòng cụ thể cần resolve
    company (xem company_resolver.py backend). Trả list
    [{"company_id", "company_name", "tax_id", "score"}, ...], KHÔNG tự
    chọn hộ — staff bấm chọn tay trên UI.

    BUG FIX (08/2026): backend trả về OBJECT {"suggestions": [...]}
    (CompanySuggestionsResponse — xem api/schemas.py), KHÔNG PHẢI list
    trần. Code cũ gán thẳng raw = _request(...) rồi `for s in raw` —
    lặp qua CÁC KEY của dict (chỉ có đúng 1 key "suggestions" — 1
    chuỗi), rồi gọi s.get("company_id") trên chuỗi đó -> AttributeError
    ('str' object has no attribute 'get'), Flask không bắt được lỗi
    này (không phải CrawlerAPIError) -> trả về trang lỗi 500 dạng HTML.
    Trình duyệt cố parse HTML đó thành JSON (res.json() ở
    _dm_import.html) -> thất bại -> rơi vào .catch() và hiện đúng cái
    alert "Lỗi kết nối khi tải danh sách công ty gợi ý ... (HTTP 500)"
    mà bạn thấy khi bấm "Chọn công ty..." ở bước Import.

    Field cũng bị sai tên: backend trả "similarity" (0-1), code cũ đọc
    "score" (không tồn tại) -> luôn None -> UI luôn thiếu phần "độ khớp
    x%" dù request có chạy được."""
    raw = _request(
        "GET", f"/import/{entity_type}/preview/{preview_id}/company-suggestions",
        access_token=access_token, params={"row_index": row_index},
    ) or {}
    suggestions = raw.get("suggestions") or []
    return [
        {
            "company_id": s.get("company_id"),
            "company_name": s.get("company_name") or "",
            "tax_id": s.get("tax_id") or "",
            "score": s.get("similarity"),
        }
        for s in suggestions
    ]


def verify_field(access_token, entity_type, preview_id, row_index, field_name, value, id_field=None):
    """POST /import/{entity_type}/preview/{preview_id}/rows/{row_index}/verify-field
    — staff sửa 1 ô lỗi trên bảng preview, bấm nút "Xác nhận" cạnh ô đó
    (thêm 08/2026, xem trao đổi thiết kế "cảnh báo trùng contact sau khi
    sửa field lỗi"). Backend re-validate format field_name NGAY + (riêng
    contact, khi field vừa sửa là work_email/social_link/phone_number)
    re-check trùng mờ với DB — xem api/services/preview_manager.py::
    apply_field_fix() backend cho toàn bộ logic.

    Trả dict {"row": <row đã normalize qua _normalize_preview_row(), khớp
    đúng shape mỗi phần tử preview.rows>, "field_error": {"rule","message"}
    | None}. field_error != None nghĩa là field VẪN CÒN lỗi sau khi sửa —
    backend KHÔNG lưu gì trong case này, "row" trả về vẫn là dòng CŨ (chưa
    đổi), _dm_import.html chỉ cần hiện field_error ngay tại ô, không cần
    ghi đè PREVIEW_DATA.

    id_field: tên cột PK thật của entity (vd "job_id") — route verify-field
    chỉ trả 1 row, KHÔNG có summary.id_field kèm theo (khác response
    preview đầy đủ), nên tầng gọi (blueprints/data_management.py) phải tự
    truyền vào từ preview đã load sẵn trong session, để _normalize_preview_row()
    tính đúng "existing_id" nếu dòng chuyển sang conflict."""
    payload = {"field_name": field_name, "value": value}
    raw = _request(
        "POST",
        f"/import/{entity_type}/preview/{preview_id}/rows/{row_index}/verify-field",
        access_token=access_token, json=payload,
    ) or {}
    row = raw.get("row")
    return {
        "row": _normalize_preview_row(row, id_field=id_field) if row else None,
        "field_error": raw.get("field_error"),
    }


def resolve_company(access_token, entity_type, preview_id, row_index, company_id, id_field=None):
    """POST /import/{entity_type}/preview/{preview_id}/rows/{row_index}/resolve-company
    — staff chọn 1 công ty (hoặc "Tạo công ty mới") trong modal chọn công
    ty ở bước preview, cho dòng needs_company_resolve (thêm 08/2026, xem
    trao đổi thiết kế "vấn đề 2 & 3": trước đây modal chỉ đổi state cục bộ
    ở FE, KHÔNG hề gọi backend re-check trùng, khiến UI hiện sai — dòng
    thật ra trùng nhưng hiện "Sẽ tạo mới", action ngầm gửi lên vẫn là
    "skip" mặc định). Route generic theo entity_type — dùng chung cho cả
    job lẫn contact (khác verify-field, hiện chỉ contact).

    company_id: "<uuid>" công ty staff chọn, hoặc None/"__new__" = xác
    nhận không công ty gợi ý nào đúng, sẽ tạo công ty mới theo
    company_name trong file (backend tự hiểu, xem
    api/schemas.py::ResolveCompanyRequest).

    Trả dict {"row": <row đã normalize qua _normalize_preview_row(), khớp
    đúng shape mỗi phần tử preview.rows>} — CHỈ 1 field "row" (khác
    verify_field() có thêm "field_error", route này không có khái niệm
    lỗi format vì company_id không phải dữ liệu staff tự gõ).

    id_field: tên cột PK thật của entity (vd "job_id") — cùng lý do
    verify_field() cần, route resolve-company chỉ trả 1 row, không có
    summary.id_field kèm theo — tầng gọi (blueprints/data_management.py)
    tự truyền vào từ preview đã load sẵn trong session."""
    payload = {"company_id": None if company_id in (None, "__new__") else company_id}
    raw = _request(
        "POST",
        f"/import/{entity_type}/preview/{preview_id}/rows/{row_index}/resolve-company",
        access_token=access_token, json=payload,
    ) or {}
    row = raw.get("row")
    return {"row": _normalize_preview_row(row, id_field=id_field) if row else None}


def import_confirm(access_token, entity_type, preview_id, resolutions, import_note):
    """POST /import/{entity_type}/confirm — chạy import thật trong 1
    transaction, ghi đúng 1 dòng audit_logs tổng hợp kèm import_note.

    Đối chiếu lại với backend thật 08/2026 (api/schemas.py::
    ImportConfirmRequest/RowResolution + api/services/import_executor.py)
    — KHÁC hoàn toàn bản nháp contract cũ từng viết ở đây:

    resolutions ở ĐÂY (tham số truyền vào hàm) vẫn là list các dict, MỖI
    DÒNG preview cần resolve gửi lên 1 phần tử:
        {
          "row_index": int,
          "action": "create" | "update" | "skip" | "reactivate",
          "selected_company_id": str | None,  # chỉ khi needs_company_resolve
          "level_code": str | None,  # chỉ khi needs_level_resolve (Job)
          "field_fixes": dict[str, str] | None,  # chỉ khi needs_field_fix
        }
    (giữ format list này ở tầng gọi vì _dm_import.html JS build ra sẵn
    dạng này) — nhưng payload GỬI LÊN BACKEND phải convert sang đúng
    contract thật:
        resolutions: {str(row_index): {"action": "skip"|"create"|"update",
                       "company_id": str|None,
                       "confirm_reactivate": bool,
                       "level_code": str|None,
                       "field_fixes": dict[str, str]|None}}
    (dict keyed theo row_index dạng CHUỖI, field tên "company_id" chứ
    không phải "selected_company_id", và action "reactivate" ở tầng gọi
    phải được dịch thành action="update" + confirm_reactivate=True vì
    backend không có action="reactivate" — xem RowResolution docstring,
    bug đã từng khiến flow ghi đè + kích hoạt lại không bao giờ chạy).
    Backend dùng model_config = ConfigDict(extra="forbid") nên field lạ
    (vd "create_new_company") sẽ khiến CẢ REQUEST bị Pydantic reject
    422, không phải bị âm thầm bỏ qua — không được gửi field thừa.

    "field_fixes" (thêm 08/2026, xem RowResolution.field_fixes +
    import_executor.py::_apply_field_fixes): BẮT BUỘC chứa đủ mọi field
    còn trong needs_field_fix/field_errors của dòng đó nếu action khác
    "skip" — backend re-validate lại giá trị staff sửa (không tin ngầm
    FE), raise lỗi rõ ràng (422) nếu thiếu/còn sai sau khi sửa. Chỉ gửi
    field này khi có giá trị, giống company_id/level_code ở trên — dòng
    không needs_field_fix thì field_fixes luôn None, không gửi key rỗng
    thừa lên backend.

    "level_code" (08/2026, xem RowResolution + import_executor.py::
    execute_import backend): BẮT BUỘC nếu dòng needs_level_resolve=true
    (Job, level_code trong file không khớp 1 trong 7 giá trị hợp lệ dù
    đã chuẩn hoá hoa/thường — xem preview_manager.py) VÀ action khác
    "skip" — check này chạy TRƯỚC NHÁNH conflict_status trong
    import_executor.py, nên áp dụng cho MỌI status kể cả "no_conflict"
    (khác company_id, vốn chỉ liên quan status="pending_company_
    resolution"). Chỉ gửi field này khi có giá trị (giống company_id) —
    _dm_import.html JS chặn submit (disable nút xác nhận) nếu dòng cần
    resolve level mà chưa chọn, nên tới được đây thì level_code coi như
    đã hợp lệ hoặc dòng đó có action="skip".

    Dòng "no_conflict"/"new" thường KHÔNG cần có trong resolutions — backend
    (import_executor.execute_import) LUÔN tạo mới dòng no_conflict bất
    kể resolution có gì hay không (Requirement 6.3) — TRỪ dòng vừa
    "no_conflict" vừa needs_level_resolve=true, bắt buộc phải có
    resolution kèm level_code (xem trên), nên tầng gọi (_dm_import.html)
    KHÔNG được lược các dòng này ra dù conflict_status="no_conflict".

    import_note: BẮT BUỘC, khác rỗng — app.py chặn submit nếu rỗng
    TRƯỚC khi gọi hàm này, nhưng vẫn để backend là nguồn xác thực cuối
    (422 nếu thiếu) phòng gọi thẳng. Backend nhận field tên "note", không
    phải "import_note" (ImportConfirmRequest.note).

    Trả {"created": int, "updated": int, "skipped": int}; backend
    (ImportConfirmResult) KHÔNG có field "reactivated" riêng — action
    reactivate được tính gộp vào "updated" (xem import_executor.py:
    _apply_conflict_action, action="update" luôn summary.updated += 1
    kể cả khi reactivate=True), nên field "reactivated" ở dict trả về
    của hàm này giữ lại = 0 cố định chỉ để khỏi phải sửa lại chỗ gọi
    hiển thị flash message, KHÔNG phản ánh số liệu thật — nếu cần đếm
    riêng, phải sửa backend trả thêm field này.
    preview bị XOÁ ở backend sau khi confirm thành công (không gọi lại
    được preview_id này nữa)."""
    resolutions_map = {}
    for entry in resolutions:
        row_index = entry.get("row_index")
        if row_index is None:
            continue
        action = entry.get("action") or "skip"
        confirm_reactivate = False
        if action == "reactivate":
            action = "update"
            confirm_reactivate = True
        resolved = {"action": action, "confirm_reactivate": confirm_reactivate}
        company_id = entry.get("selected_company_id")
        if company_id:
            resolved["company_id"] = company_id
        level_code = entry.get("level_code")
        if level_code:
            resolved["level_code"] = level_code
        field_fixes = entry.get("field_fixes")
        if field_fixes:
            resolved["field_fixes"] = field_fixes
        resolutions_map[str(row_index)] = resolved

    payload = {"preview_id": preview_id, "resolutions": resolutions_map, "note": import_note}
    raw = _request(
        "POST", f"/import/{entity_type}/confirm", access_token=access_token, json=payload,
    ) or {}
    return {
        "created": raw.get("created", 0),
        "updated": raw.get("updated", 0),
        "skipped": raw.get("skipped", 0),
        "reactivated": 0,  # backend chưa trả field này riêng — xem docstring
        "errors": raw.get("errors") or [],
    }
