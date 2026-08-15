# Audit & Hướng dẫn sử dụng — MindX Career Hub

> Tài liệu này mô tả kiến trúc, tính năng và cách vận hành website MindX
> Career Hub, dành cho các thành viên trong team (dev, team SS) tham khảo
> và sử dụng. Cập nhật lần gần nhất theo bản code đã chuyển sang
> **Supabase** cho Auth + Job + Contact.

---

## 1. Website này dùng để làm gì

MindX Career Hub là một web app nội bộ giúp:

- **Học viên (student):** tìm việc làm/thực tập phù hợp (Code, Data
  Analysis, Business Analysis), lưu job quan tâm, ứng tuyển, theo dõi
  trạng thái các đơn đã ứng tuyển.
- **Team SS (staff):** thu thập & quản lý job từ nhiều nguồn, quản lý
  danh sách công ty/người liên hệ (contact) để hợp tác tuyển dụng, xem
  dashboard tổng quan, và xem danh sách học viên đã ứng tuyển vào từng
  job để hỗ trợ kết nối.

---

## 2. Kiến trúc hệ thống

| Thành phần | Công nghệ | Lưu ở đâu |
|---|---|---|
| Web server | Flask (Python) | — |
| Giao diện | Jinja2 templates + CSS thuần | `templates/`, `static/` |
| Đăng nhập/Đăng ký + phân quyền | **Supabase Auth** (email/password) | Supabase (`auth.users`) |
| Hồ sơ + role (student/staff) | Bảng `profiles` | **Supabase Postgres** |
| Job (tin tuyển dụng) | Bảng `jobs` | **Supabase Postgres** (đã có sẵn) |
| Contact (công ty/người liên hệ) | Bảng `contacts` | **Supabase Postgres** (đã có sẵn) |
| Job đã lưu / Đơn ứng tuyển | `SavedJob`, `JobApplication` | **SQLite cục bộ** (`mindx.db`) |

**Vì sao tách như vậy:** tài khoản, job, contact là dữ liệu dùng chung,
cần đồng bộ real-time và có thể quản lý qua Supabase Dashboard, nên đặt
trên Supabase. Job đã lưu/đơn ứng tuyển gắn chặt với logic phiên đăng
nhập của riêng app này nên vẫn giữ ở SQLite cho gọn — không ảnh hưởng gì
đến cách người dùng sử dụng, hoàn toàn "vô hình" với họ.

### Sơ đồ luồng dữ liệu (tổng quan)

```
Người dùng (trình duyệt)
        │
        ▼
   Flask app (app.py)
   ├── auth.py ───────► Supabase Auth (đăng ký/đăng nhập/đăng xuất)
   ├── data.py ───────► Supabase Postgres: bảng jobs, contacts, profiles
   └── SQLAlchemy ────► SQLite (mindx.db): SavedJob, JobApplication
```

### File/thư mục quan trọng

| File | Vai trò |
|---|---|
| `app.py` | Toàn bộ route (URL) của web app |
| `auth.py` | Đăng ký/đăng nhập/đăng xuất qua Supabase Auth, class `AuthUser` |
| `data.py` | Đọc/ghi bảng `jobs`, `contacts` trên Supabase |
| `supabase_client.py` | Khởi tạo 2 client Supabase (anon + service_role) |
| `seed_supabase.py` | Script tạo sẵn tài khoản staff (chạy 1 lần, thủ công) |
| `supabase_schema.sql` | Câu lệnh SQL tạo bảng `profiles` + RLS |
| `templates/*.html` | Giao diện các trang |
| `mindx.db` | Database SQLite cục bộ (tự tạo khi chạy app lần đầu) |
| `.env` | Biến môi trường / API key (không commit lên git) |

---

## 3. Vai trò & phân quyền

Có 2 role, lưu ở cột `role` trong bảng `profiles` trên Supabase:

- **`student`** — tài khoản tự đăng ký qua trang `/register`.
- **`staff`** — tài khoản team SS, **không** tự đăng ký được qua web;
  phải tạo trước bằng script `seed_supabase.py` (xem mục 6).

Route nào yêu cầu `staff` sẽ được đánh dấu bằng decorator
`@staff_required` trong `app.py` — nếu học viên cố truy cập sẽ bị đá về
trang chủ kèm thông báo lỗi.

---

## 4. Danh sách tính năng

### 4.1. Dành cho học viên (student)

| Tính năng | Trang / URL | Mô tả |
|---|---|---|
| Đăng ký tài khoản | `/register` | Nhập họ tên, email, mật khẩu, SĐT, track (Code/Data/BA). Tạo xong tự đăng nhập luôn (trừ khi Supabase đang bật xác nhận email). |
| Đăng nhập | `/login` | Email + mật khẩu. |
| Đăng xuất | `/logout` | — |
| Xem danh sách job | `/` hoặc `/jobs` | Có tìm kiếm theo từ khóa (công ty/vị trí/kỹ năng) + lọc theo ngành, level, địa điểm, trạng thái. |
| Xem chi tiết job | `/jobs/<id>` | Mô tả công việc, yêu cầu, kỹ năng, lương, hạn nộp, link JD gốc. |
| Lưu / bỏ lưu job | Nút "Lưu" trên trang chi tiết job | Toggle — bấm lại để bỏ lưu. |
| Xem job đã lưu | `/saved-jobs` | Danh sách job đã bấm "Lưu". |
| Ứng tuyển job | Nút "Ứng tuyển" trên trang chi tiết job | Có thể kèm ghi chú; mỗi học viên chỉ ứng tuyển 1 lần / job. |
| Xem đơn đã ứng tuyển | `/my-applications` | Danh sách job đã ứng tuyển kèm trạng thái. |

### 4.2. Dành cho team SS (staff)

| Tính năng | Trang / URL | Mô tả |
|---|---|---|
| Dashboard tổng quan | `/dashboard` | Thống kê số job/contact/học viên/đơn ứng tuyển, phân bổ theo ngành/level/trạng thái/địa điểm/thành phố. |
| Xem danh sách job | `/jobs` | Giống học viên, cộng thêm quyền thao tác. |
| Thêm job mới | `/jobs/add` | Form nhập đầy đủ thông tin job. |
| Cập nhật trạng thái job | Trên trang chi tiết job | Đổi giữa: Còn tuyển / Hết hạn / Chưa xác minh / Đã gửi cho học viên. |
| Xóa job | Trên trang chi tiết job | Xóa khỏi bảng `jobs`. |
| Xem ai đã ứng tuyển | Trang chi tiết job (chỉ staff thấy) | Danh sách học viên đã ứng tuyển kèm tên, email, SĐT (lấy từ bảng `profiles`). |
| Cảnh báo trùng job | Trang chi tiết job | Tự động phát hiện nếu có job khác cùng công ty + cùng vị trí. |
| Quản lý danh sách contact | `/contacts` | Tìm kiếm + lọc theo thành phố, trạng thái, mức độ phù hợp. |
| Thêm contact mới | `/contacts/add` | Thông tin công ty + người liên hệ tuyển dụng. |
| Cập nhật trạng thái contact | Trên trang danh sách contact | Đổi trạng thái liên hệ (Chưa liên hệ → ... → Đã giới thiệu học viên). |
| Xóa contact | Trên trang danh sách contact | — |

---

## 5. Hướng dẫn cài đặt & chạy (cho dev)

### Bước 1 — Chuẩn bị Supabase

1. Vào Supabase Dashboard của project → **SQL Editor** → chạy file
   `supabase_schema.sql` để tạo bảng `profiles` (nếu chưa có).
2. Đảm bảo project đã có sẵn 2 bảng `jobs` và `contacts` (nếu tên bảng/cột
   khác, sửa hằng số `JOBS_TABLE`/`CONTACTS_TABLE` và tên cột tương ứng
   trong `data.py`).
3. Vào **Settings → API**, lấy 3 giá trị:
   - `Project URL`
   - `anon public` key
   - `service_role` key (⚠️ giữ bí mật, không chia sẻ qua chat/git)

### Bước 2 — Cấu hình project

```bash
cp .env.example .env
# rồi mở .env, điền SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY
```

### Bước 3 — Cài thư viện

```bash
pip install -r requirements.txt
```

### Bước 4 — (Tuỳ chọn) tạo tài khoản staff

```bash
python seed_supabase.py
```

In ra danh sách email/mật khẩu vừa tạo — đổi mật khẩu sau khi đăng nhập
lần đầu.

### Bước 5 — Chạy app

```bash
python app.py
```

Mặc định chạy ở `http://localhost:5000`.

> **Lưu ý:** Supabase mặc định bật "Confirm email". Nếu muốn đăng ký
> xong đăng nhập được ngay (môi trường dev/test), vào **Authentication →
> Providers → Email** trên Supabase Dashboard và tắt "Confirm email".

---

## 6. Quản lý tài khoản staff

Vì `/register` chỉ tạo tài khoản `student`, tài khoản `staff` phải được
tạo bằng 1 trong 2 cách:

1. **Chạy `seed_supabase.py`** — cách nhanh nhất, tạo sẵn danh sách trong
   file (sửa list `STAFF_ACCOUNTS` trong file này nếu muốn thêm người).
2. **Thủ công trên Supabase Dashboard** — tạo user ở Authentication →
   Users, sau đó vào Table Editor → bảng `profiles`, thêm dòng tương ứng
   với `id` = id của user vừa tạo và `role = 'staff'`.

---

## 7. Câu hỏi thường gặp / xử lý sự cố

| Vấn đề | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Đăng ký xong không đăng nhập được, báo "kiểm tra email" | Supabase đang bật xác nhận email | Tắt "Confirm email" (dev) hoặc bấm link xác nhận trong email đã nhận |
| Trang báo lỗi "Server chưa cấu hình SUPABASE_SERVICE_ROLE_KEY" | Thiếu key trong `.env` | Điền `SUPABASE_SERVICE_ROLE_KEY` vào `.env`, khởi động lại app |
| Dashboard hiện "Tổng học viên: None" | Chưa cấu hình service_role key | Giống trên |
| Job/Contact không hiện dù đã thêm trên Supabase Studio | Sai tên bảng/cột so với `data.py` | Kiểm tra lại `JOBS_TABLE`/`CONTACTS_TABLE` và tên cột trong `data.py` |
| Lỗi "Host not in allowlist" khi gọi Supabase | Đang chạy trong môi trường có giới hạn mạng (sandbox) | Chạy ở máy local/server thật, không giới hạn domain `supabase.co` |

---

## 8. Ghi chú bảo mật

- **`service_role` key có toàn quyền** đọc/ghi mọi bảng, bỏ qua RLS —
  chỉ dùng ở phía server (file `.env`), tuyệt đối không đưa vào code
  frontend, không commit lên git, không gửi qua chat/email không mã hoá.
- Nếu nghi ngờ key đã bị lộ (vd lỡ dán vào chat, commit nhầm lên git
  công khai), vào **Settings → API → Reset service_role secret** ngay
  và cập nhật lại `.env`.
- File `.env` đã được thêm vào `.gitignore`, không tự động commit.
