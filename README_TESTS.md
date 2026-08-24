# Bộ test cho mindx-jobs — hướng dẫn áp dụng

## Cài đặt vào repo

1. Copy `requirements-dev.txt` vào thư mục gốc repo (cạnh `requirements.txt`).
2. Copy `pytest.ini` vào thư mục gốc repo (cạnh `app.py`) — BẮT BUỘC, nếu
   không pytest sẽ báo lỗi `ModuleNotFoundError: No module named
   'crawler_client'` khi chạy `tests/conftest.py` (đã gặp lỗi này thực
   tế — xem lịch sử trao đổi).
3. Copy cả thư mục `tests/` vào thư mục gốc repo (cạnh `app.py`).
4. Cài dependency:
   ```
   pip install -r requirements-dev.txt
   ```

## Chạy test

```
pytest tests/ -v
```

Chạy nhanh (không verbose):
```
pytest tests/
```

Chạy random order (khuyến khích thỉnh thoảng chạy để phát hiện leak trạng thái ẩn):
```
pip install pytest-randomly
pytest tests/ -p randomly
```

## Kết quả hiện tại

**137 test, tất cả pass.**

- `test_helpers.py` — 35 test (parse_date, _parse_any_date, format_date,
  _jobs_by_month, to_bullets, và **_call_authed** — hàm từng có bug lịch
  sử về refresh token).
- `test_crawler_client.py` — 28 test (get_enums/get_level_codes cache TTL
  5 phút, và tính đối xứng của toàn bộ 6 cặp *_MAP/*_MAP_REV).
- `test_decorators.py` — 9 test (staff_required — cả 4 nhánh: chưa
  login, không phải staff, phải đổi mật khẩu, đủ điều kiện).
- `test_data_management.py` — 13 test (export, import_preview,
  verify_field — bao gồm test 401-transparent-refresh ở route thật —,
  import_confirm).
- `test_dashboard.py` — 11 test (happy path, và 6 test partial-backend-
  failure — mỗi lệnh gọi backend lỗi riêng lẻ không được làm sập trang).
- `test_activity_logs.py` — 14 test **(mới)** — blueprint được nhắc
  THẲNG TÊN trong docstring helpers.py là nơi từng dính bug _call_authed
  cũ (crash 500 sau ~30 phút do thiếu refresh token). Cover: index()
  (filter view/entity/company/actor, phân trang, partial-backend-failure)
  và update_note() (bao gồm test 401-transparent-refresh ở đúng route
  lịch sử, và test message 403 thân thiện).
- `test_jobs.py` — 27 test **(mới)** — blueprint phức tạp nhất (234
  dòng). Cover:
  - `detail()` — route công khai nhưng PHÂN NHÁNH nội dung theo role
    (staff thấy applicants/savers, student thấy already_applied, khách
    vãng lai không thấy gì) — rủi ro lộ dữ liệu cá nhân nếu sai nhánh.
  - `_resolve_company_id()` — nhánh tạo công ty mới LỒNG 1 lệnh gọi
    backend bên trong route add() cũng gọi backend khác; test xác nhận
    company_id mới tạo được truyền đúng sang bước tạo job.
  - `update_status()`/`delete()` — xác nhận "xoá" job thực chất là PATCH
    status=CLOSED (soft delete), không có lệnh gọi xoá thật nào.

Đã xác nhận qua sandbox:
- Chạy ổn định qua nhiều random seed khác nhau (không leak trạng thái
  giữa các test nhờ fixture `reset_enums_cache` autouse).
- **Không có test nào gọi network thật** — đã verify bằng cách chặn cứng
  `requests.request` khi chạy toàn bộ suite, tất cả 137 test vẫn pass.
  (Trong lúc viết 2 file mới, cách kiểm tra này thực sự bắt được 2 lỗi
  mock thiếu sót — xem mục "Bài học" bên dưới.)

## Ghi chú thiết kế

- `requirements-dev.txt` tách riêng khỏi `requirements.txt` — Render chỉ
  đọc `requirements.txt` gốc lúc deploy, không bị ảnh hưởng.
- `pytest.ini` (pythonpath = .) đảm bảo pytest luôn thêm thư mục gốc vào
  sys.path khi chạy test, bất kể pytest được gọi từ đâu.
- Mock luôn patch tại namespace nơi blueprint *nhìn thấy* tên hàm (vd
  `blueprints.data_management.db_data.export_entity`), không phải tại
  `crawler_client.export_entity` trực tiếp — vì blueprint dùng
  `import crawler_client as db_data`.
- `conftest.py::reset_enums_cache` là fixture `autouse=True`, tự chạy
  trước MỌI test để reset cache TTL của `get_enums()` — không cần khai
  báo thủ công trong từng test.
- Login staff/student/admin trong test không gọi backend JWT thật — dựng
  `auth.BackendUser` giả rồi gọi `flask_login.login_user()` trực tiếp,
  chỉ mock `app.backend_auth.get_me` (được `login_manager.user_loader`
  gọi lại mỗi request để "load user").
- `student_client` fixture mock sẵn `app.backend_auth.list_my_saved_jobs`
  (xem mục "Bài học" — context_processor toàn cục gọi hàm này mỗi
  request của user không phải staff).

## Bài học — 2 lỗi mock bị bắt bởi bài kiểm tra "chặn network cứng"

Khi viết `test_jobs.py`/`test_activity_logs.py`, cách kiểm tra "patch
`requests.request` để raise lỗi ngay nếu bị gọi" đã bắt được 2 chỗ mock
thiếu sót thực tế trước khi merge:

1. **Context processor toàn cục**: `app.py::inject_saved_job_ids` tự
   động gọi `backend_auth.list_my_saved_jobs()` ở MỌI request của user
   không phải staff (để tô sáng nút "đã lưu" trên mọi trang) — không
   riêng gì route đang test. 3 test dùng `student_client` ban đầu quên
   mock hàm này, lỡ gọi ra network thật. Đã sửa bằng cách mock mặc định
   ngay trong fixture `student_client` ở `conftest.py`, để mọi test sau
   này dùng fixture đó không cần tự nhớ mock lại.

2. **`follow_redirects=True` chạy tiếp route khác**: 1 test POST xong
   redirect sang GET `/activity-logs` (trang `logs()`), nhưng chỉ mock
   dependency của route POST, quên mock dependency của trang GET được
   redirect tới — cũng lỡ gọi network thật. Bài học: khi dùng
   `follow_redirects=True`, phải mock đủ dependency của CẢ route đích,
   không chỉ route gọi ban đầu.

## Chưa làm (mở rộng thêm nếu cần)

- Còn 7 blueprint chưa có test route-level: companies, contacts, auth,
  staff, my_stuff, students, staff_activity.
- Chưa có GitHub Actions CI (đã hỏi, bạn xác nhận không cần).
- Chưa test JS (isFieldFixValid, isRowResolved) — cần Jest/Vitest riêng.
