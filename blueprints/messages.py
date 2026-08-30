"""Messages blueprint — hệ thống nhắn tin học viên ↔ SS / SS ↔ SS,
thêm 08/2026. Xem frontend-mindx-jobs-nhan-tin.md cho kế hoạch FE đầy
đủ, backend-scrap-jd-nhan-tin.md cho API/response shape mà module này
gọi tới (qua backend_auth.py).

QUY ƯỚC: partner_id trong file này LUÔN là ss_user_id của người đang
nhắn cùng (học viên hoặc SS/admin) — không phân biệt tên biến theo
role, vì cùng 1 route (vd thread(), send()) phục vụ cả 2 chiều.

partner_name/partner_role hiển thị trên trang chat/inbox lấy qua QUERY
STRING (?name=&role=) do link điều hướng tới tự gắn sẵn (từ
messages.html hoặc messages_new.html) — KHÔNG có API "lấy 1 user theo
id" dùng chung được cho MỌI role (GET /auth/users chỉ SS/admin gọi
được), nên đây là cách khả thi nhất để hiển thị đúng tên mà không cần
thêm route backend mới. Nếu thiếu (gõ thẳng URL, hoặc link cũ đã mất
query string), thread() tự dò lại trong list_conversations() — chỉ
thành công nếu đã từng nhắn qua lại; không suy được thì hiện "Người
dùng" chung chung, KHÔNG chặn xem lịch sử vì lý do này.
"""

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

import backend_auth
from backend_auth import BackendAuthError
from helpers import _auth_tokens_from_session
from utils.decorators import staff_required

messages_bp = Blueprint("messages", __name__, url_prefix="/messages")

# Khớp CHECK char_length(btrim(content)) BETWEEN 1 AND 2000 ở backend
# (sql/migration_add_chat_messages.sql) — check lại ở đây CHỈ để tránh 1
# round-trip mạng vô ích khi rõ ràng đã sai (maxlength HTML là UX-only,
# đây mới là chặn thật phía server — nhưng vẫn chỉ là double-check, cái
# chặn THẬT SỰ nằm ở backend, xem MessageCreate._trim_and_reject_blank).
MAX_CONTENT_LENGTH = 2000


@messages_bp.route("")
@login_required
def inbox():
    """Trang chính: danh sách hội thoại đã có tin nhắn + (riêng SS/admin)
    mục "Yêu cầu đang chờ" — học viên đã gửi request nhưng SS chưa
    accept/decline, xem docstring backend_auth.list_pending_requests()."""
    access_token, _ = _auth_tokens_from_session()
    try:
        conversations = backend_auth.list_conversations(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        conversations = []

    pending_requests = []
    if current_user.is_staff:
        try:
            pending_requests = backend_auth.list_pending_requests(access_token)
        except BackendAuthError as exc:
            flash(str(exc), "error")

    return render_template(
        "messages.html", conversations=conversations, pending_requests=pending_requests,
    )


@messages_bp.route("/new")
@login_required
def new_message():
    """Tìm người để bắt đầu hội thoại mới. Backend tự lọc kết quả theo
    role người tìm (học viên chỉ thấy ss_team/admin) — không lọc lại ở
    đây, tránh 2 nơi cùng chứa 1 luật nghiệp vụ dễ lệch nhau."""
    q = request.args.get("q", "").strip()
    results = []
    if q:
        access_token, _ = _auth_tokens_from_session()
        try:
            results = backend_auth.search_people(access_token, q)
        except BackendAuthError as exc:
            flash(str(exc), "error")
    return render_template("messages_new.html", q=q, results=results)


@messages_bp.route("/<string:partner_id>")
@login_required
def thread(partner_id):
    """Mở 1 hội thoại cụ thể — SSR sẵn 50 tin gần nhất (đọc được ngay,
    không cần chờ JS), JS polling (public/app.js) chỉ lo phần tin ĐẾN
    SAU lúc trang đã tải xong."""
    if partner_id == current_user.id:
        abort(400)

    access_token, _ = _auth_tokens_from_session()

    try:
        history = backend_auth.get_message_history(access_token, partner_id, limit=50)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        history = []
    # Backend trả MỚI NHẤT TRƯỚC (ORDER BY id DESC, tối ưu cho phân
    # trang cursor before_id) — đảo lại để khớp chiều đọc trên->dưới
    # (cũ->mới) trong khung chat.
    history = list(reversed(history))

    partner_name = request.args.get("name", "").strip()
    partner_role = request.args.get("role", "").strip()
    if not partner_name:
        try:
            for conv in backend_auth.list_conversations(access_token):
                if conv.get("partner_id") == partner_id:
                    partner_name = conv.get("partner_name", "")
                    partner_role = conv.get("partner_role", "")
                    break
        except BackendAuthError:
            pass
    partner_name = partner_name or "Người dùng"

    try:
        backend_auth.mark_messages_read(access_token, partner_id)
    except BackendAuthError:
        pass  # không đáng làm hỏng cả trang chỉ vì đánh dấu đã đọc thất bại

    last_id = history[-1]["id"] if history else 0

    return render_template(
        "messages_thread.html",
        partner_id=partner_id, partner_name=partner_name, partner_role=partner_role,
        history=history, last_id=last_id, max_content_length=MAX_CONTENT_LENGTH,
    )


@messages_bp.route("/<string:partner_id>/cancel", methods=["POST"])
@login_required
def cancel(partner_id):
    """Học viên tự huỷ request 'pending' do chính mình gửi tới SS này
    (gửi nhầm / đổi ý) — POST /messages/cancel/{ss_id} phía backend, xem
    docstring backend_auth.cancel_pending_request(). CHỈ hiện nút này ở
    UI khi lịch sử trống VÀ current_user là học viên (xem
    messages_thread.html) — nhưng vẫn tự chặn lại ở đây phòng gõ thẳng
    URL, vì route backend cũng tự 403 nếu SS gọi nhầm."""
    if not current_user.is_student:
        abort(403)

    access_token, _ = _auth_tokens_from_session()
    redirect_url = url_for(
        "messages.thread", partner_id=partner_id,
        name=request.args.get("name", ""), role=request.args.get("role", ""),
    )
    try:
        backend_auth.cancel_pending_request(access_token, partner_id)
        flash("Đã huỷ yêu cầu nhắn tin.", "success")
    except BackendAuthError as exc:
        flash(str(exc), "error")
    return redirect(redirect_url)


@messages_bp.route("/<string:partner_id>/send", methods=["POST"])
@login_required
def send(partner_id):
    """Gửi 1 tin nhắn — form POST thường (không fetch): backend đã lưu
    tin trước khi redirect nên trang thread() render lại SẼ tự hiện
    ngay tin vừa gửi qua SSR, không cần JS chèn tay. name/role trong
    query string được GIỮ NGUYÊN qua redirect để trang mở lại vẫn hiển
    thị đúng tên đối phương (xem docstring đầu file)."""
    if partner_id == current_user.id:
        abort(400)

    content = request.form.get("content", "").strip()
    redirect_url = url_for(
        "messages.thread", partner_id=partner_id,
        name=request.args.get("name", ""), role=request.args.get("role", ""),
    )

    if not content:
        flash("Vui lòng nhập nội dung tin nhắn.", "error")
        return redirect(redirect_url)
    if len(content) > MAX_CONTENT_LENGTH:
        flash(f"Tin nhắn không được vượt quá {MAX_CONTENT_LENGTH} ký tự.", "error")
        return redirect(redirect_url)

    access_token, _ = _auth_tokens_from_session()
    try:
        result = backend_auth.send_message(access_token, partner_id, content)
        if result.get("status") == "pending":
            flash(result.get("message") or "Đã gửi yêu cầu nhắn tin.", "success")
        # status == "sent": không cần flash — tin nhắn mới tự hiện trong
        # lịch sử SSR ngay khi redirect quay lại thread() ở trên.
    except BackendAuthError as exc:
        flash(str(exc), "error")

    return redirect(redirect_url)


@messages_bp.route("/<string:partner_id>/since.json")
def since_json(partner_id):
    """Polling nhẹ trong lúc mở khung chat (~5s/lần, xem public/app.js).
    Check current_user THỦ CÔNG (KHÔNG dùng @login_required) — decorator
    đó redirect (302) sang trang HTML login khi hết phiên, còn fetch()
    JS cần 1 mã lỗi 401 THẬT để tự dừng polling hẳn (xem vòng đời polling,
    frontend-mindx-jobs-nhan-tin.md §4 mục 3) — cùng lý do _wants_json()
    trong utils/decorators.py, chỉ khác route này CHỈ dùng cho JSON nên
    không cần nhánh HTML."""
    if not current_user.is_authenticated:
        return jsonify(error="not_authenticated"), 401

    try:
        after_id = int(request.args.get("after_id", 0))
    except (TypeError, ValueError):
        after_id = 0

    access_token, _ = _auth_tokens_from_session()
    try:
        new_messages = backend_auth.get_messages_since(access_token, partner_id, after_id)
    except BackendAuthError as exc:
        status = exc.status_code if exc.status_code in (401, 403, 404, 429) else 500
        return jsonify(error=str(exc)), status

    resp = jsonify(new_messages)
    # Header Cache-Control: no-store (§3 backend-scrap-jd-nhan-tin.md) —
    # TODO ở backend chưa set được (route trả list qua response_model,
    # xem docstring get_new_messages phía backend); set ở tầng proxy này
    # thay, vẫn đủ để trình duyệt/CDN không cache response polling.
    resp.headers["Cache-Control"] = "no-store"
    return resp


@messages_bp.route("/unread-count.json")
def unread_count_json():
    """Badge sidebar (poll 20-30s, xem public/app.js + base.html) — cùng
    lý do check thủ công is_authenticated như since_json() ở trên."""
    if not current_user.is_authenticated:
        return jsonify(error="not_authenticated"), 401

    access_token, _ = _auth_tokens_from_session()
    try:
        count = backend_auth.get_unread_count(access_token)
    except BackendAuthError as exc:
        status = exc.status_code if exc.status_code in (401, 403, 429) else 500
        return jsonify(error=str(exc)), status

    resp = jsonify(count=count)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ============================================================
# Quản lý quan hệ — accept / decline / block. CHỈ SS/admin (@staff_required
# đã tự check is_authenticated + is_staff + must_change_password, xem
# utils/decorators.py) — học viên không có nút này ở UI, chặn cả ở route
# để gõ thẳng URL cũng không vào được. Form POST thường (không fetch),
# redirect lại /messages theo đúng kế hoạch FE.
#
# unblock CHƯA có route ở đây — cần relationship_id mà UI hiện không có
# cách lấy cho 1 hội thoại đã accepted/blocked (xem docstring
# backend_auth.unblock_message_relationship()). Đã báo lại việc này,
# tạm thời SS muốn bỏ chặn phải nhờ chỉnh trực tiếp DB/qua kênh khác.
# ============================================================

@messages_bp.route("/relationships/<string:relationship_id>/accept", methods=["POST"])
@staff_required
def accept_request_route(relationship_id):
    access_token, _ = _auth_tokens_from_session()
    try:
        backend_auth.accept_message_request(access_token, relationship_id)
        flash("Đã chấp nhận yêu cầu nhắn tin.", "success")
    except BackendAuthError as exc:
        flash(str(exc), "error")
    return redirect(url_for("messages.inbox"))


@messages_bp.route("/relationships/<string:relationship_id>/decline", methods=["POST"])
@staff_required
def decline_request_route(relationship_id):
    access_token, _ = _auth_tokens_from_session()
    try:
        backend_auth.decline_message_request(access_token, relationship_id)
        flash("Đã từ chối yêu cầu nhắn tin.", "success")
    except BackendAuthError as exc:
        flash(str(exc), "error")
    return redirect(url_for("messages.inbox"))


@messages_bp.route("/block/<string:student_id>", methods=["POST"])
@staff_required
def block_student(student_id):
    access_token, _ = _auth_tokens_from_session()
    try:
        backend_auth.block_student_in_chat(access_token, student_id)
        flash("Đã chặn học viên này — họ sẽ không nhắn tin được cho bạn nữa.", "success")
    except BackendAuthError as exc:
        flash(str(exc), "error")
    return redirect(url_for("messages.inbox"))
