# MindX Career Hub — Job Board + Company/Contact Database

Website nội bộ cho team Student Success: job board (Intern/Fresher) + quản lý công ty/người liên
hệ HR để hợp tác tuyển dụng, dùng chung 1 hệ thống đăng nhập với phân quyền theo role.

- **Production:** https://mind-x-jd-website.vercel.app
- **Backend API** (repo riêng `Koaito/scrap-jd`, FastAPI, deploy Render): `https://scrap-jd-api.onrender.com`

---

## 1. Website này dùng để làm gì

- **Học viên (role `user`):** tìm việc làm/thực tập phù hợp (Code, Data Analysis, Business
  Analysis), lưu job quan tâm, ứng tuyển, theo dõi/huỷ các đơn đã ứng tuyển.
- **Team SS (role `ss_team` / `admin`):** thêm/sửa job, quản lý danh sách công ty & người liên hệ
  (contact) để hợp tác tuyển dụng, xem dashboard tổng quan, xem danh sách học viên đã ứng tuyển
  vào từng job, quản lý tài khoản team SS khác (chỉ `admin`).

## 2. Kiến trúc hệ thống

| Thành phần | Công nghệ | Lưu ở đâu |
|---|---|---|
| Web server (frontend, repo này) | Flask (Python), deploy **Vercel** | — |
| Giao diện | Jinja2 templates + CSS thuần | `templates/`, `public/style.css` |
| Backend API | FastAPI ("Scrap JD"), deploy **Render** | repo riêng `Koaito/scrap-jd` |
| Đăng nhập/Đăng ký + phân quyền | JWT (access 30 phút + refresh 30 ngày) do **chính backend** phát hành | **Postgres** (Render), bảng `app_users` |
| Job / Company / Company contact | Đọc/ghi qua REST API backend | **Postgres** (Render) |
| Job đã lưu / Đơn ứng tuyển | `/me/saved-jobs`, `/me/applications` — API backend | **Postgres** (Render) |

**Không lưu gì cục bộ ở phía Flask app này** — không SQLite, không session data ngoài 2 token
(access/refresh) ký trong cookie session mặc định của Flask. Mọi dữ liệu người dùng thật sự nằm
100% ở backend.

```
Người dùng (trình duyệt)
        │
        ▼
   Flask app (app.py) — deploy Vercel
   ├── backend_auth.py ──► Backend API /auth/*, /me/* (JWT: đăng ký, đăng
   │                        nhập, đổi/quên mật khẩu, ứng tuyển, lưu job)
   └── crawler_client.py ─► Backend API /jobs, /companies,
                             /companies/{id}/contacts, /stats
                             │
                             ▼
                    Backend "Scrap JD" (FastAPI) — deploy Render
                             │
                             ▼
                        Postgres (Render)
```

### File/thư mục quan trọng

| File | Vai trò |
|---|---|
| `app.py` | Toàn bộ route (URL) của web app; quản lý session token, auto-refresh khi access token hết hạn |
| `auth.py` | `BackendUser` — lớp user cho Flask-Login, dựng từ response `GET /auth/me` |
| `backend_auth.py` | Client gọi API xác thực: register/login/refresh/change-password/forgot-password/reset-password/logout, và `/me/applications`, `/me/saved-jobs` |
| `crawler_client.py` | Client gọi API job/company/contact/stats — chuẩn hoá field backend sang tên field template dùng (`job.company`, `job.position`...) |
| `env_loader.py` | Đọc file `.env` khi chạy local (`python app.py`) — Vercel không dùng, set env trực tiếp trên dashboard |
| `templates/*.html` | Giao diện các trang (Jinja2), gồm `_pagination.html` dùng chung cho trang job/công ty |
| `public/style.css` | CSS — đặt ở `public/` (không phải `static/`) để khớp cách Vercel serve static files |
| `vercel.json` | Cấu hình deploy Vercel (`maxDuration: 30` cho `app.py`) |
| `.env.example` | Mẫu 3 biến môi trường cần set: `CRAWLER_API_URL`, `CRAWLER_API_KEY`, `FLASK_SECRET_KEY` |

**Không còn trong repo** (đã xoá 08/2026, dọn dẹp cùng đợt chuyển sang backend API thật):
`supabase_client.py`, `seed_supabase.py`, `supabase_schema.sql`, `data.py`.

**Còn sót lại, nên dọn:** thư mục `static/style.css` — không còn được Flask serve (đã đổi sang
`public/`), giữ lại dễ gây nhầm khi có người sửa nhầm file không có tác dụng.

## 3. Vai trò & phân quyền

3 role, quản lý ở backend (bảng `app_users`, cột `role`), theo thứ bậc `user < ss_team < admin`:

- **`user`** — học viên. Tự đăng ký qua `/register` (frontend) → `POST /auth/register` (backend,
  public). Bắt buộc xác thực email (bấm link trong mail) trước khi đăng nhập được.
- **`ss_team`** — nhân viên team SS. **Không** tự đăng ký qua web được; phải do `admin` tạo qua
  giao diện `/staff-accounts/add` (gọi `POST /auth/users`).
- **`admin`** — quản trị, có thêm quyền tạo/đổi role người khác (`/staff-accounts`), trigger crawl
  job tự động (route backend riêng, không liên quan frontend này).

Ở tầng frontend, decorator `@staff_required` trong `app.py` coi `ss_team` và `admin` đều là
"team SS" (property `current_user.is_staff`) — route nào cần vai trò này mà học viên cố truy cập
sẽ bị chặn.

Nếu tài khoản đang `must_change_password=True` (mật khẩu tạm do admin cấp), mọi route staff sẽ ép
chuyển hướng về `/change-password` trước, trừ chính route đó và `/logout`.

**Tạo tài khoản `admin` đầu tiên** (lúc hệ thống chưa có admin nào — "con gà quả trứng", vì
`POST /auth/users` cần JWT `admin` để gọi): chạy CLI ở phía backend (`scrap-jd`), xem README của
repo đó — `python main.py create-admin --email ... --name ...`. Sau khi có 1 admin, tạo thêm
`ss_team`/`admin` khác nên làm qua `/staff-accounts/add` trên web, không cần CLI nữa.

## 4. Danh sách tính năng

### 4.1. Dành cho học viên (`user`)

| Tính năng | Trang / URL | Mô tả |
|---|---|---|
| Đăng ký tài khoản | `/register` | Họ tên, email, mật khẩu, SĐT, track (ngành quan tâm) |
| Đăng nhập | `/login` | Bắt buộc đã xác thực email. Có nút "Gửi lại email xác thực" nếu chưa xác thực |
| Đăng xuất | `/logout` | Thu hồi refresh token phía backend |
| Quên / đặt lại mật khẩu | `/forgot-password`, `/reset-password?token=...` | 2 bước: nhập email nhận link → nhập mật khẩu mới |
| Xem danh sách job | `/` hoặc `/jobs` | Tìm kiếm theo từ khoá + lọc ngành/level/địa điểm/trạng thái, phân trang (20 job/trang, có ô "Tới trang" nhảy thẳng) |
| Xem chi tiết job | `/jobs/<id>` | Mô tả, yêu cầu, kỹ năng, lương, hạn nộp, link JD gốc |
| Lưu / bỏ lưu job | Nút "Lưu" ở trang chi tiết job | Toggle qua `POST /jobs/<id>/save` |
| Xem job đã lưu | `/saved-jobs` | — |
| Ứng tuyển job | Nút "Ứng tuyển" ở trang chi tiết | Kèm ghi chú tuỳ chọn; backend chặn nếu job không `OPEN` hoặc đã ứng tuyển rồi |
| Huỷ ứng tuyển | Nút "Huỷ ứng tuyển" ở `/my-applications` | `POST /jobs/<id>/withdraw` |
| Xem đơn đã ứng tuyển | `/my-applications` | — |

### 4.2. Dành cho team SS (`ss_team` / `admin`)

| Tính năng | Trang / URL | Mô tả |
|---|---|---|
| Dashboard tổng quan | `/dashboard` | Tổng job/công ty/học viên/đơn ứng tuyển, phân bố theo ngành/level/trạng thái/địa điểm/thành phố |
| Thêm / sửa job | `/jobs/add`, `/jobs/<id>/edit` | Chọn công ty có sẵn hoặc tạo mới ngay tại chỗ |
| Đổi trạng thái job | `/jobs/<id>/status` | `OPEN` / `EXPIRED` / `CLOSED` |
| "Xoá" job | `/jobs/<id>/delete` | **Không xoá thật** — backend không có `DELETE /jobs/{id}` (job xoá thật sẽ bị crawl lại tạo trùng). Thực chất chuyển `job_status=CLOSED`, vẫn xem được ở trang chi tiết, chỉ ẩn khỏi tìm kiếm mặc định |
| Xem ai đã ứng tuyển | Trang chi tiết job (chỉ staff) | `GET /jobs/{id}/applications`, kèm tên/email/SĐT người ứng tuyển |
| Cảnh báo job trùng | Trang chi tiết job | Tự phát hiện job khác cùng công ty + cùng vị trí |
| Quản lý công ty | `/companies` | Tìm kiếm + lọc theo thành phố, phân trang (20 công ty/trang, có ô "Tới trang") |
| Thêm / sửa công ty | `/companies/add`, `/companies/<id>/edit` | Tạo idempotent theo `tax_id` (gọi lại với tax_id đã có sẽ vá thông tin công ty cũ, không tạo trùng). Không có xoá công ty (backend không hỗ trợ) |
| Quản lý người liên hệ (contact) | Trang chi tiết công ty | Contact là bảng con của company — CRUD đầy đủ (thêm/sửa/đổi trạng thái/xoá) |
| Quản lý tài khoản team SS | `/staff-accounts`, `/staff-accounts/add` | Xem danh sách; **chỉ `admin`** thêm tài khoản mới hoặc đổi role người khác (`/staff-accounts/<id>/role`). `ss_team` xem được danh sách nhưng không sửa được |

## 5. Hướng dẫn cài đặt & chạy (cho dev)

### Bước 1 — Cấu hình biến môi trường

```bash
cp .env.example .env
```

| Biến | Bắt buộc? | Ghi chú |
|---|---|---|
| `CRAWLER_API_URL` | Không (có default) | URL backend Render, mặc định `https://scrap-jd-api.onrender.com` |
| `CRAWLER_API_KEY` | **Có** | Trùng với `API_KEY` trong `.env` của backend — thiếu sẽ lỗi ngay mọi request |
| `FLASK_SECRET_KEY` | Nên có | Ký session cookie; có fallback dev nhưng **không an toàn cho production** |

### Bước 2 — Cài thư viện & chạy

```bash
pip install -r requirements.txt
python app.py
```

Mặc định chạy ở `http://localhost:5000`.

> App này **không tự tạo tài khoản mẫu nào**. Muốn có tài khoản staff để test cục bộ, dùng tài
> khoản admin thật đăng nhập vào production rồi tạo thêm qua `/staff-accounts/add`, hoặc nhờ CLI
> `create-admin` bên backend nếu cần admin hoàn toàn mới (xem mục 3).

### Deploy production (Vercel)

1. Code phải nằm trong 1 Git repo (GitHub) — Vercel bắt buộc kết nối qua Git, không upload zip
   trực tiếp.
2. Trên Vercel: Import repo → set 3 biến môi trường ở **Project Settings → Environment
   Variables** (Vercel không đọc file `.env`).
3. Trên backend (Render): thêm domain Vercel vào `ALLOWED_ORIGINS` (CORS) và set
   `FRONTEND_BASE_URL=https://mind-x-jd-website.vercel.app` (để link email — quên mật khẩu, xác
   thực email — trỏ đúng chỗ).

## 6. Câu hỏi thường gặp / xử lý sự cố

| Vấn đề | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Trang báo "Server chưa cấu hình CRAWLER_API_KEY" | Thiếu biến trong `.env` (local) hoặc Environment Variables (Vercel) | Điền `CRAWLER_API_KEY`, khởi động/redeploy lại |
| Đăng nhập báo lỗi liên quan "xác thực" (403) | Tài khoản chưa bấm link xác thực email | Bấm nút "Gửi lại email xác thực" trên trang login, hoặc kiểm tra hộp thư/spam |
| Trang job/company hiện lỗi 422 khi tải danh sách dài | Gọi backend với `limit > 200` | Backend giới hạn cứng 200/lần — dùng field `total` để đếm, `offset` để lặp trang (đã xử lý ở `crawler_client.py`) |
| Session tự đăng xuất giữa chừng dù mới đăng nhập | Access token (30 phút) hết hạn nhưng refresh cũng thất bại | Kiểm tra refresh token còn hạn (30 ngày) hay đã bị thu hồi (vd sau khi đổi mật khẩu ở thiết bị khác) |
| CORS lỗi khi frontend gọi backend sau khi đổi domain Vercel | `ALLOWED_ORIGINS` bên backend (Render) chưa có domain mới | Thêm domain Vercel mới vào `ALLOWED_ORIGINS`, redeploy backend |
| Link trong email "quên mật khẩu"/"xác thực" trỏ về `localhost` | `FRONTEND_BASE_URL` chưa set đúng trên Render | Set `FRONTEND_BASE_URL=https://mind-x-jd-website.vercel.app` trong Environment Variables backend |

## 7. Ghi chú bảo mật

- **Không có key "toàn quyền" nào ở tầng frontend** — `CRAWLER_API_KEY` chỉ là API key xác định
  frontend hợp lệ, mọi quyền hạn thật sự do JWT (gắn với 1 user cụ thể) quyết định.
- `FLASK_SECRET_KEY` ký session cookie chứa access/refresh token — **bắt buộc đổi giá trị thật khi
  deploy**, không dùng fallback dev trong code.
- File `.env` đã nằm trong `.gitignore`, không tự động commit.
- Đổi mật khẩu thành công → backend tự thu hồi **toàn bộ** refresh token hiện có của user (đăng
  xuất mọi thiết bị khác) — hành vi này cố ý, không phải bug.
