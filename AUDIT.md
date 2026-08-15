# Audit & Hướng dẫn sử dụng — MindX Career Hub

> Tài liệu này mô tả kiến trúc, tính năng và cách vận hành website MindX
> Career Hub, dành cho các thành viên trong team (dev, team SS) tham khảo
> và sử dụng. **Cập nhật 08/2026** — kiến trúc đã chuyển hẳn sang gọi
> 100% qua API backend "Scrap JD" (FastAPI, deploy Render). **Không còn
> Supabase, không còn SQLite** ở tầng frontend này.

---

## 1. Website này dùng để làm gì

MindX Career Hub là một web app nội bộ giúp:

- **Học viên (role `user`):** tìm việc làm/thực tập phù hợp (Code, Data
  Analysis, Business Analysis), lưu job quan tâm, ứng tuyển, theo dõi
  trạng thái các đơn đã ứng tuyển.
- **Team SS (role `ss_team` / `admin`):** thêm/sửa job, quản lý danh
  sách công ty & người liên hệ (contact) để hợp tác tuyển dụng, xem
  dashboard tổng quan, và xem danh sách học viên đã ứng tuyển vào từng
  job để hỗ trợ kết nối.

---

## 2. Kiến trúc hệ thống

| Thành phần | Công nghệ | Lưu ở đâu |
|---|---|---|
| Web server (frontend) | Flask (Python), deploy **Vercel** | — |
| Giao diện | Jinja2 templates + CSS thuần | `templates/`, `public/style.css` |
| Backend API | FastAPI ("Scrap JD"), deploy **Render** | repo riêng `Koaito/scrap-jd` |
| Đăng nhập/Đăng ký + phân quyền | JWT (access 30 phút + refresh 30 ngày) do **chính backend** phát hành | **Postgres** (Render) — bảng `app_users` |
| Job / Company / Company contact | Đọc/ghi qua REST API backend | **Postgres** (Render) |
| Job đã lưu / Đơn ứng tuyển | `/me/saved-jobs`, `/me/applications` — API backend | **Postgres** (Render) |

**Không còn gì lưu cục bộ ở phía Flask app này** — không SQLite, không
session data ngoài 2 token (access/refresh) ký trong cookie session mặc
định của Flask. Mọi dữ liệu người dùng thật sự nằm 100% ở backend.

**Vì sao đổi từ Supabase sang JWT tự quản:** tránh phải giữ
`SUPABASE_SERVICE_ROLE_KEY` (toàn quyền, bỏ qua RLS) ở phía server
Flask — rủi ro bảo mật nếu key này lộ. Chuyển hẳn xác thực về backend
tự viết, dùng chung hạ tầng Postgres đang có sẵn cho job/company.

### Sơ đồ luồng dữ liệu (tổng quan)

```
Người dùng (trình duyệt)
        │
        ▼
   Flask app (app.py) — deploy Vercel
   ├── backend_auth.py ──► Backend API /auth/*, /me/* (JWT: đăng ký, đăng
   │                        nhập, đổi mật khẩu, quên mật khẩu, ứng tuyển,
   │                        lưu job)
   └── crawler_client.py ─► Backend API /jobs, /companies,
                             /companies/{id}/contacts (đọc/ghi, cần
                             Bearer token cho thao tác ghi)
                             │
                             ▼
                    Backend "Scrap JD" (FastAPI) — deploy Render
                             │
                             ▼
                        Postgres (Render)
```

### File/thư mục quan trọng (frontend — repo này)

| File | Vai trò |
|---|---|
| `app.py` | Toàn bộ route (URL) của web app; quản lý session token, auto-refresh khi access token hết hạn |
| `auth.py` | `BackendUser` — lớp user cho Flask-Login, dựng từ response `GET /auth/me` |
| `backend_auth.py` | Client gọi API xác thực: login/register/refresh/change-password/forgot-password (⚠️ chưa dùng)/logout, và `/me/applications`, `/me/saved-jobs` |
| `crawler_client.py` | Client gọi API job/company/contact — chuẩn hoá field backend sang tên field template dùng (`job.company`, `job.position`...) |
| `env_loader.py` | Đọc file `.env` khi chạy local (`python app.py`) — Vercel không dùng, set env trực tiếp trên dashboard |
| `templates/*.html` | Giao diện các trang (Jinja2) |
| `public/style.css` | CSS — đặt ở `public/` (không phải `static/`) để khớp cách Vercel serve static files |
| `vercel.json` | Cấu hình deploy Vercel (`maxDuration: 30` cho `app.py`) |
| `.env.example` | Mẫu 3 biến môi trường cần set: `CRAWLER_API_URL`, `CRAWLER_API_KEY`, `FLASK_SECRET_KEY` |

**Không còn trong repo** (đã xoá 08/2026, dọn dẹp cùng đợt chuyển sang
backend API thật): `supabase_client.py`, `seed_supabase.py`,
`supabase_schema.sql`, `data.py`, `static/` (thư mục cũ, còn sót file
nhưng không còn được Flask serve — xem mục 8).

---

## 3. Vai trò & phân quyền

3 role, quản lý ở backend (bảng `app_users`, cột `role`), theo thứ bậc
`user < ss_team < admin`:

- **`user`** — học viên. Tự đăng ký qua `/register` (frontend) →
  `POST /auth/register` (backend, public). Bắt buộc xác thực email
  (bấm link trong mail) trước khi đăng nhập được.
- **`ss_team`** — nhân viên team SS. **Không** tự đăng ký qua web được;
  phải do `admin` tạo qua `POST /auth/users` (backend) — thao tác này
  frontend **chưa có giao diện** (xem mục 7, mục "cần làm tiếp").
- **`admin`** — quản trị, có thêm quyền tạo/đổi role người khác, trigger
  crawl job tự động (route backend riêng, không liên quan frontend này).

Ở tầng frontend, decorator `@staff_required` trong `app.py` coi
`ss_team` và `admin` đều là "team SS" (property `current_user.is_staff`)
— route nào cần vai trò này mà học viên cố truy cập sẽ bị đá về trang
job kèm cảnh báo.

Ngoài ra: nếu tài khoản đang `must_change_password=True` (mật khẩu tạm
do admin cấp), mọi route staff sẽ ép chuyển hướng về `/change-password`
trước, trừ chính route đó và `/logout`.

---

## 4. Danh sách tính năng

### 4.1. Dành cho học viên (`user`)

| Tính năng | Trang / URL | Mô tả |
|---|---|---|
| Đăng ký tài khoản | `/register` | Họ tên, email, mật khẩu, SĐT, track. **Lưu ý:** backend hiện chưa có cột lưu `phone`/`track` — 2 field này gửi lên nhưng bị bỏ qua, chưa hiển thị được ở đâu. |
| Đăng nhập | `/login` | Bắt buộc đã xác thực email. Có nút "Gửi lại email xác thực" nếu login báo lỗi 403 do chưa xác thực. |
| Đăng xuất | `/logout` | Thu hồi refresh token phía backend. |
| Xem danh sách job | `/` hoặc `/jobs` | Tìm kiếm theo từ khoá + lọc theo ngành, level, địa điểm, trạng thái. |
| Xem chi tiết job | `/jobs/<id>` | Mô tả, yêu cầu, kỹ năng, lương, hạn nộp, link JD gốc. |
| Lưu / bỏ lưu job | Nút "Lưu" ở trang chi tiết job | Toggle qua `POST /jobs/<id>/save`. |
| Xem job đã lưu | `/saved-jobs` | — |
| Ứng tuyển job | Nút "Ứng tuyển" ở trang chi tiết | Kèm ghi chú tuỳ chọn; backend chặn nếu job không ở trạng thái `OPEN` hoặc đã ứng tuyển rồi. |
| Huỷ ứng tuyển | `/jobs/<id>/withdraw` | Route đã có (backend hỗ trợ `DELETE /me/applications/{id}`), cần xác nhận có nút gọi route này trên UI đơn đã ứng tuyển. |
| Xem đơn đã ứng tuyển | `/my-applications` | — |

### 4.2. Dành cho team SS (`ss_team` / `admin`)

| Tính năng | Trang / URL | Mô tả |
|---|---|---|
| Dashboard tổng quan | `/dashboard` | Số job/company theo ngành/level/trạng thái/địa điểm/thành phố. Tổng học viên lấy qua `GET /auth/users`. **Tổng đơn ứng tuyển hiện luôn ẩn** — backend chưa có endpoint đếm tổng (xem mục 7). |
| Thêm / sửa job | `/jobs/add`, `/jobs/<id>/edit` | Chọn công ty có sẵn hoặc tạo mới ngay tại chỗ. |
| Đổi trạng thái job | `/jobs/<id>/status` | `OPEN` / `EXPIRED` / `CLOSED`. |
| "Xoá" job | `/jobs/<id>/delete` | **Không xoá thật** — backend không có `DELETE /jobs/{id}` (job xoá thật sẽ bị crawl lại tạo trùng). Thực chất là chuyển `job_status=CLOSED`. |
| Xem ai đã ứng tuyển | Trang chi tiết job (chỉ staff) | `GET /jobs/{id}/applications`, trả sẵn tên/email người ứng tuyển. |
| Cảnh báo job trùng | Trang chi tiết job | Tự phát hiện job khác cùng công ty + cùng vị trí. |
| Quản lý công ty | `/companies` | Tìm kiếm + lọc theo thành phố. |
| Thêm / sửa công ty | `/companies/add`, `/companies/<id>/edit` | Tạo idempotent theo `tax_id` (gọi lại với tax_id đã có sẽ vá thông tin công ty cũ, không tạo trùng). **Không có xoá công ty** (backend không hỗ trợ). |
| Quản lý người liên hệ (contact) | Trang chi tiết công ty | Contact là bảng con của company — CRUD đầy đủ (thêm/sửa/đổi trạng thái/xoá mềm). |

---

## 5. Hướng dẫn cài đặt & chạy (cho dev)

### Bước 1 — Cấu hình biến môi trường

```bash
cp .env.example .env
```

Điền 3 biến (xem mô tả chi tiết trong `.env.example`):

| Biến | Bắt buộc? | Ghi chú |
|---|---|---|
| `CRAWLER_API_URL` | Không (có default) | URL backend Render, mặc định `https://scrap-jd-api.onrender.com` |
| `CRAWLER_API_KEY` | **Có** | Trùng với `API_KEY` trong `.env` của backend — thiếu sẽ lỗi ngay mọi request |
| `FLASK_SECRET_KEY` | Nên có | Ký session cookie; có fallback dev nhưng **không an toàn cho production** |

### Bước 2 — Cài thư viện

```bash
pip install -r requirements.txt
```

### Bước 3 — Chạy app

```bash
python app.py
```

Mặc định chạy ở `http://localhost:5000`.

> **Lưu ý:** app này **không tự tạo tài khoản mẫu nào**. Muốn có tài
> khoản staff để test, phải nhờ backend tạo qua `POST /auth/users`
> (route backend, cần role `admin` gọi trước — frontend hiện chưa có
> giao diện gọi route này, xem mục 7).

### Deploy production (Vercel)

Đã deploy thật — xem lại phiên làm việc trước để biết domain cụ thể.
Tóm tắt quy trình (không cần lặp lại trừ khi tạo project Vercel mới):

1. Code phải nằm trong 1 Git repo (GitHub) — Vercel bắt buộc kết nối
   qua Git, không upload zip trực tiếp.
2. Trên Vercel: Import repo → set 3 biến môi trường ở **Project
   Settings → Environment Variables** (Vercel không đọc file `.env`).
3. Trên backend (Render): thêm domain Vercel vào `ALLOWED_ORIGINS`
   (CORS) và set `FRONTEND_BASE_URL` (để link email trỏ đúng chỗ — cần
   cho tính năng quên mật khẩu khi frontend làm xong, xem mục 7).

---

## 6. Quản lý tài khoản staff

`/register` (frontend) chỉ tạo role `user`. Tài khoản `ss_team`/`admin`
phải được tạo **ở phía backend**, bằng 1 trong 2 cách:

1. **`POST /auth/users`** (backend, cần JWT role `admin`) — hiện phải
   gọi trực tiếp API (Postman/curl), **frontend chưa có form nào cho
   thao tác này** (xem mục 7).
2. **Thao tác trực tiếp trên Postgres (Render)** — sửa cột `role` của
   dòng tương ứng trong bảng `app_users`.

> Template `templates/staff_accounts.html` đã tồn tại sẵn trong repo
> nhưng **chưa có route nào trong `app.py` trỏ tới nó** — có thể đây là
> nơi định làm giao diện quản lý tài khoản staff nhưng chưa nối route.
> Xem mục 7.

---

## 7. Việc cần làm tiếp (tính đến bản audit này)

Theo mức độ ưu tiên:

1. **Giao diện "Quên mật khẩu" — backend đã xong, frontend chưa có gì.**
   `templates/login.html` hiện chỉ có dòng text tĩnh bảo học viên liên
   hệ team SS thủ công. Cần thêm:
   - Link "Quên mật khẩu?" ở `/login` → trang nhập email → gọi
     `POST /auth/forgot-password` (`backend_auth.py` đã có sẵn hàm
     `resend_verification`-style nhưng **chưa có hàm gọi
     forgot-password/reset-password** — cần bổ sung 2 hàm này vào
     `backend_auth.py` trước).
   - Trang `/reset-password?token=...` → form nhập mật khẩu mới → gọi
     `POST /auth/reset-password`.
   - Đảm bảo `FRONTEND_BASE_URL` trên Render trỏ đúng domain Vercel
     hiện tại (nếu domain đổi từ lần set trước).

2. **Không có giao diện quản lý tài khoản staff.** Backend có
   `POST /auth/users` (tạo) nhưng frontend chưa có form gọi route này —
   hiện phải tạo tài khoản `ss_team`/`admin` thủ công qua API hoặc DB.
   Template `staff_accounts.html` có sẵn nhưng mồ côi route — nên tận
   dụng lại thay vì viết mới.

3. **Dashboard thiếu "Tổng đơn ứng tuyển".** Backend chưa có endpoint
   đếm tổng số `job_applications` toàn hệ thống (chỉ có đếm theo 1 user
   hoặc theo 1 job) — cần thêm ở backend trước (vd
   `GET /stats/applications`) rồi mới hiện được số này ở `/dashboard`.

4. **`static/style.css` là file thừa, có thể gây nhầm.** App đã đổi
   sang serve static từ `public/` (khớp chuẩn Vercel) — file trong
   `static/` không còn được Flask serve nữa. Nên xoá để tránh 2 người
   sửa nhầm file không có tác dụng.

5. **`phone`/`track` của học viên bị "câm".** Form đăng ký gửi 2 field
   này lên nhưng backend chưa có cột lưu → dữ liệu mất, không hiển thị
   được ở đâu (kể cả dashboard/trang xem người ứng tuyển). Cần backend
   thêm cột trước khi 2 field này có ý nghĩa thật.

6. **Nút "Huỷ ứng tuyển" cần rà lại UI.** Route `/jobs/<id>/withdraw`
   đã có ở `app.py`, cần xác nhận `templates/my_applications.html` (hoặc
   trang chi tiết job) có nút gọi đúng route này chưa.

---

## 8. Câu hỏi thường gặp / xử lý sự cố

| Vấn đề | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Trang báo "Server chưa cấu hình CRAWLER_API_KEY" | Thiếu biến trong `.env` (local) hoặc Environment Variables (Vercel) | Điền `CRAWLER_API_KEY`, khởi động/redeploy lại |
| Đăng nhập báo lỗi liên quan "xác thực" (403) | Tài khoản chưa bấm link xác thực email | Bấm nút "Gửi lại email xác thực" trên trang login, hoặc kiểm tra hộp thư/spam |
| Trang job/company hiện lỗi 422 khi tải danh sách dài | Gọi backend với `limit > 200` | Backend giới hạn cứng 200/lần — dùng field `total` để đếm, dùng `offset` để lặp trang (đã fix ở `crawler_client.py`, xem `count_jobs()`/`list_company_cities()`) |
| Session tự đăng xuất giữa chừng dù mới đăng nhập | Access token (30 phút) hết hạn nhưng refresh cũng thất bại | Kiểm tra refresh token còn hạn (30 ngày) hay đã bị thu hồi (vd sau khi đổi mật khẩu ở thiết bị khác) |
| CORS lỗi khi frontend gọi backend sau khi đổi domain Vercel | `ALLOWED_ORIGINS` bên backend (Render) chưa có domain mới | Thêm domain Vercel mới vào `ALLOWED_ORIGINS`, redeploy backend |
| Link trong email "quên mật khẩu" trỏ về `localhost` | `FRONTEND_BASE_URL` chưa set trên Render | Set `FRONTEND_BASE_URL=https://<domain-vercel-thật>` trong `.env` backend |

---

## 9. Ghi chú bảo mật

- **Không còn key "toàn quyền" nào ở tầng frontend** (khác bản Supabase
  cũ) — `CRAWLER_API_KEY` chỉ là API key xác định frontend hợp lệ, mọi
  quyền hạn thật sự do JWT (gắn với 1 user cụ thể) quyết định.
- `FLASK_SECRET_KEY` ký session cookie chứa access/refresh token —
  **bắt buộc đổi giá trị thật khi deploy**, không dùng fallback dev
  trong code.
- File `.env` đã nằm trong `.gitignore`, không tự động commit.
- Đổi mật khẩu thành công → backend tự thu hồi **toàn bộ** refresh
  token hiện có của user (đăng xuất mọi thiết bị khác) — hành vi này cố
  ý, không phải bug.
