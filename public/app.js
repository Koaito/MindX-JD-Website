// MindX Career Hub — small progressive-enhancement helpers.
// Everything here is optional: if JS fails, forms fall back to their
// normal server-rendered POST + redirect behaviour.

(function () {
  "use strict";

  // ---- Sidebar collapse/expand toggle -----------------------------------
  //
  // The actual class add happens synchronously in an inline <script> in
  // <head> (base.html), before first paint, so there's no flash-of-wrong-
  // width on reload. This block only needs to: (a) sync the button's own
  // icon/label to match current state on load, and (b) handle clicks.
  function initSidebarToggle() {
    var btn = document.getElementById("sidebarToggle");
    var ic = document.getElementById("sidebarToggleIc");
    var label = document.getElementById("sidebarToggleLabel");
    if (!btn) return;

    function isCollapsed() {
      return document.documentElement.classList.contains("sidebar-collapsed");
    }

    function syncButton() {
      var collapsed = isCollapsed();
      if (ic) ic.textContent = collapsed ? "»" : "«";
      if (label) label.textContent = collapsed ? "Mở rộng" : "Thu gọn";
      btn.setAttribute("aria-expanded", String(!collapsed));
    }

    btn.addEventListener("click", function () {
      var collapsed = document.documentElement.classList.toggle("sidebar-collapsed");
      try {
        localStorage.setItem("sidebarCollapsed", collapsed ? "1" : "0");
      } catch (e) { /* localStorage bị chặn — trạng thái vẫn đổi được, chỉ không nhớ qua lần tải trang sau */ }
      syncButton();
    });

    syncButton();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSidebarToggle);
  } else {
    initSidebarToggle();
  }

  // ---- Sidebar nav scroll memory (thêm 08/2026, staff báo bất tiện) -----
  //
  // KHÁC sidebarCollapsed ở trên (thu gọn/mở rộng cả sidebar): đây là app
  // Flask nhiều trang (MPA) — mỗi lần bấm 1 mục trong menu là tải lại
  // TOÀN BỘ trang mới, .nav (khối menu có scroll riêng — xem overflow-y:
  // auto trong 01-sidebar.css) render lại từ đầu và tự cuộn về đỉnh, dù
  // staff đang ở mục cuối danh sách (vd "Xuất / Nhập dữ liệu" dưới mục
  // "Quản trị") — phải cuộn lại từ đầu mỗi lần chuyển trang.
  //
  // Lưu scrollTop vào sessionStorage mỗi khi staff cuộn, khôi phục lại
  // ngay khi trang mới tải xong — sessionStorage (không phải localStorage)
  // vì vị trí cuộn chỉ có ý nghĩa trong phiên làm việc hiện tại, tự dọn
  // sạch khi đóng tab/trình duyệt thay vì tồn mãi.
  function initSidebarScrollMemory() {
    var nav = document.getElementById("sidebarNav");
    if (!nav) return;

    try {
      var saved = sessionStorage.getItem("sidebarNavScroll");
      if (saved !== null) nav.scrollTop = parseInt(saved, 10) || 0;
    } catch (e) { /* sessionStorage bị chặn — bỏ qua, sidebar về đầu như cũ */ }

    nav.addEventListener("scroll", function () {
      try {
        sessionStorage.setItem("sidebarNavScroll", String(nav.scrollTop));
      } catch (e) { /* bỏ qua, chỉ mất tính năng nhớ vị trí, không lỗi gì khác */ }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSidebarScrollMemory);
  } else {
    initSidebarScrollMemory();
  }

  function showToast(message, kind) {
    var stack = document.getElementById("toast-stack");
    if (!stack) return;
    var el = document.createElement("div");
    el.className = "toast toast-" + (kind === "error" ? "error" : "success");
    el.textContent = message;
    stack.appendChild(el);
    setTimeout(function () {
      el.remove();
    }, 3200);
  }

  // showToast() được dùng lại (thêm 08/2026) từ script riêng trong
  // _dm_import.html (bảng preview import — báo "còn dòng chưa xử lý
  // xong" khi bấm Xác nhận mà chưa sửa hết field lỗi) — script đó nằm
  // trong 1 IIFE khác (đóng theo <script> riêng của template), không
  // truy cập được showToast() cục bộ ở đây, nên expose ra window thay
  // vì viết lại y hệt UI toast 1 lần nữa ở template.
  window.showToast = showToast;

  // ---- Async save/unsave job (no full page reload) ----------------------
  //
  // Matches the existing <form action=".../toggle-save"> markup used on
  // index.html, job_detail.html and saved_jobs.html. We derive the JSON
  // endpoint from the existing form action so we don't need to touch every
  // template individually.
  document.addEventListener("submit", function (evt) {
    var form = evt.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (!form.classList.contains("save-job-form")) return;

    evt.preventDefault();
    var btn = form.querySelector("button[type=submit]");
    var jsonUrl = form.getAttribute("data-json-action") || form.action.replace(/\/toggle-save$/, "/toggle-save.json");

    if (btn) btn.disabled = true;

    fetch(jsonUrl, {
      method: "POST",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        var data = result.data;
        if (!result.ok || !data.ok) {
          showToast(data.message || "Có lỗi xảy ra, vui lòng thử lại.", "error");
          return;
        }
        showToast(data.message, "success");

        // Update this button's own state.
        if (btn) {
          if (form.dataset.removeOnUnsave === "true" && !data.saved) {
            // e.g. on the "Saved jobs" page, an unsaved job disappears entirely.
            var card = form.closest(".ticket, .job-row");
            if (card) card.remove();
          } else {
            btn.classList.toggle("saved", data.saved);
            if (form.dataset.swapEmphasis === "true") {
              // job_detail.html: primary button = "not yet saved" (call to
              // action), ghost button = "already saved".
              btn.classList.toggle("btn-primary", !data.saved);
              btn.classList.toggle("btn-ghost", data.saved);
            }
            btn.textContent = data.saved
              ? (form.dataset.savedLabel || "🔖 Đã lưu")
              : (form.dataset.unsavedLabel || "🔖 Lưu job");
          }
        }
      })
      .catch(function () {
        // Network/JS failure — fall back to a real form submit so the
        // action still completes via the normal server round-trip.
        form.submit();
      })
      .finally(function () {
        if (btn) btn.disabled = false;
      });
  });

  // ---- Company combobox (search + scroll) --------------------------------
  //
  // Markup: templates/_company_combobox.html (hidden input giữ giá trị thật
  // gửi lên form, input text để gõ tìm, panel .cbx-panel cuộn được).
  // Hành vi: chưa gõ gì -> mở ra hiện TOÀN BỘ danh sách (giống <select> cũ);
  // gõ -> lọc theo tên công ty (không phân biệt dấu tiếng Việt); hỗ trợ
  // ArrowUp/ArrowDown + Enter để chọn bằng bàn phím, không chỉ click chuột.
  function stripDiacritics(str) {
    return (str || "")
      .toString()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/đ/g, "d");
  }

  function initCompanyCombobox() {
    var boxes = document.querySelectorAll("[data-cbx]");
    if (!boxes.length) return;

    Array.prototype.forEach.call(boxes, function (box) {
      var input = box.querySelector("[data-cbx-input]");
      var hidden = box.querySelector("[data-cbx-value]");
      var panel = box.querySelector("[data-cbx-panel]");
      var emptyMsg = box.querySelector("[data-cbx-empty]");
      var errorMsg = box.querySelector("[data-cbx-error]");
      if (!input || !hidden || !panel) return;

      var opts = Array.prototype.slice.call(box.querySelectorAll(".cbx-opt"));
      // hasQuery = người dùng đã thực sự gõ ký tự nào chưa. Chưa gõ (kể cả
      // khi input đã có sẵn tên công ty do chọn từ trước / retry sau lỗi
      // submit) thì mở ra vẫn hiện đủ danh sách, đúng yêu cầu "chưa gõ thì
      // hiện như bình thường".
      var hasQuery = false;
      var activeEl = null;

      function visibleOpts() {
        return opts.filter(function (o) { return o.style.display !== "none"; });
      }

      function setActive(el) {
        opts.forEach(function (o) { o.classList.remove("cbx-active"); });
        activeEl = el;
        if (el) {
          el.classList.add("cbx-active");
          if (el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
        }
      }

      function applyFilter() {
        var q = hasQuery ? stripDiacritics(input.value) : "";
        var anyMatch = false;
        opts.forEach(function (o) {
          var pinned = o.dataset.pinned === "1";
          var match = q === "" || stripDiacritics(o.dataset.label).indexOf(q) !== -1;
          if (match && !pinned) anyMatch = true;
          o.style.display = (pinned || match) ? "" : "none";
        });
        if (emptyMsg) emptyMsg.hidden = !(q !== "" && !anyMatch);
        setActive(null);
      }

      function openPanel() {
        panel.hidden = false;
        box.classList.add("cbx-open");
      }

      function closePanel() {
        panel.hidden = true;
        box.classList.remove("cbx-open");
        setActive(null);
      }

      function findOptByValue(val) {
        for (var i = 0; i < opts.length; i++) {
          if (opts[i].dataset.value === val) return opts[i];
        }
        return null;
      }

      function selectOpt(opt) {
        hidden.value = opt.dataset.value;
        input.value = opt.dataset.value === "__new__" ? "" : opt.dataset.label;
        if (opt.dataset.value === "__new__") input.placeholder = opt.dataset.label;
        hasQuery = false;
        if (errorMsg) errorMsg.hidden = true;
        closePanel();
        // Báo cho script khác (vd add_job.html — hiện/ẩn khối "tạo công ty
        // mới") biết giá trị vừa đổi, giống hệt onchange của <select> cũ.
        hidden.dispatchEvent(new Event("change", { bubbles: true }));
      }

      opts.forEach(function (o) {
        // mousedown thay vì click: chạy TRƯỚC sự kiện blur của input, nếu
        // dùng click thì blur đóng panel mất trước khi click kịp bắn ra.
        o.addEventListener("mousedown", function (e) {
          e.preventDefault();
          selectOpt(o);
        });
      });

      input.addEventListener("focus", function () {
        openPanel();
        applyFilter();
      });

      input.addEventListener("input", function () {
        hasQuery = true;
        openPanel();
        applyFilter();
      });

      input.addEventListener("keydown", function (e) {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          openPanel();
          var vis = visibleOpts();
          if (!vis.length) return;
          var idx = activeEl ? vis.indexOf(activeEl) : -1;
          idx = e.key === "ArrowDown" ? Math.min(idx + 1, vis.length - 1) : Math.max(idx - 1, 0);
          setActive(vis[idx]);
        } else if (e.key === "Enter") {
          if (!panel.hidden && activeEl) {
            e.preventDefault();
            selectOpt(activeEl);
          }
        } else if (e.key === "Escape") {
          closePanel();
        }
      });

      document.addEventListener("click", function (e) {
        if (panel.hidden || box.contains(e.target)) return;
        closePanel();
        // Click ra ngoài mà không chọn gì: nếu chữ đang gõ dở không khớp
        // với công ty đã chọn trước đó, trả input về đúng giá trị đã chọn
        // (hoặc rỗng) để không lệch với hidden input thật sự gửi lên form.
        if (hidden.value === "__new__") {
          input.value = "";
        } else {
          var chosen = hidden.value ? findOptByValue(hidden.value) : null;
          input.value = chosen ? chosen.dataset.label : "";
        }
        hasQuery = false;
      });

      applyFilter();
    });

    // Hidden input không tham gia validate HTML5 "required" như <select>
    // cũ, nên tự chặn submit nếu ô công ty bắt buộc mà chưa chọn gì.
    document.addEventListener("submit", function (evt) {
      var form = evt.target;
      if (!(form instanceof HTMLFormElement)) return;
      var requiredBoxes = form.querySelectorAll("[data-cbx][data-cbx-required]");
      if (!requiredBoxes.length) return;
      var blocked = false;
      Array.prototype.forEach.call(requiredBoxes, function (box) {
        var hidden = box.querySelector("[data-cbx-value]");
        var input = box.querySelector("[data-cbx-input]");
        var errorMsg = box.querySelector("[data-cbx-error]");
        var ok = hidden && hidden.value;
        if (errorMsg) errorMsg.hidden = !!ok;
        if (!ok) {
          blocked = true;
          if (input) input.focus();
        }
      });
      if (blocked) evt.preventDefault();
    }, true);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCompanyCombobox);
  } else {
    initCompanyCombobox();
  }

  // NOTE: .job-grid / .job-grid-3col (/viec-lam) and .kpi-row (/dashboard)
  // used to need a JS pass here to stretch a short trailing row of cards
  // to fill empty space — CSS Grid's auto-fit/minmax() fixes the column
  // count from the widest row, so a shorter last row left visible empty
  // cells on the right. They're flexbox now (see public/css/04-job-
  // cards.css and public/css/08-dashboard.css): flex-wrap + flex-grow
  // makes every row, including a short last one, fill its own width
  // natively. No JS needed for this anymore.

  // ---- Phân trang client-side cho các danh sách dài trong dashboard -----
  //
  // Thêm 08/2026: nhiều panel ở /dashboard (job theo địa điểm, công ty
  // theo thành phố, JD cần đẩy/ế, khoảng lương, công ty thiếu contact/
  // mở rộng/im lặng...) liệt kê TOÀN BỘ item server trả về trong 1 lần,
  // không giới hạn — dữ liệu tăng lên là phải scroll rất dài. Khác các
  // trang list chính (companies.html, index.html) vốn đã phân trang ở
  // server (xem _pagination.html + Flask ?page=), các panel dashboard
  // này nằm rải rác trong nhiều tab/card nhỏ nên phân trang phía CLIENT
  // (ẩn/hiện bằng display) hợp lý hơn: không cần thêm route/query param
  // cho từng panel, không mất vị trí tab đang xem khi bấm trang.
  //
  // Cách dùng trong template:
  //   <div id="pg-xxx" data-paginate-size="20">
  //     ...danh sách item (mỗi item là 1 phần tử con trực tiếp)...
  //   </div>
  //   <div class="pagination-list-nav" data-paginate-for="pg-xxx"></div>
  // Nếu số item <= data-paginate-size thì không đụng gì tới DOM (không
  // tạo nav rỗng) — tránh khoảng trắng thừa khi danh sách vốn đã ngắn.
  function initClientListPagination() {
    var containers = document.querySelectorAll("[data-paginate-size]");
    Array.prototype.forEach.call(containers, function (container) {
      var pageSize = parseInt(container.getAttribute("data-paginate-size"), 10);
      if (!pageSize || pageSize < 1) pageSize = 20;

      // .children (không phải .childNodes) nên tự bỏ qua text node/khoảng
      // trắng giữa các thẻ do Jinja render ra — mỗi phần tử con trực tiếp
      // (div.bar-row hoặc tr) là đúng 1 "item" cần phân trang.
      var items = Array.prototype.slice.call(container.children);
      if (items.length <= pageSize) return; // ngắn sẵn, không cần phân trang

      var mount = document.querySelector('[data-paginate-for="' + container.id + '"]');
      var totalPages = Math.ceil(items.length / pageSize);
      var page = 1;

      function render() {
        var start = (page - 1) * pageSize;
        var end = start + pageSize;
        items.forEach(function (el, idx) {
          el.style.display = (idx >= start && idx < end) ? "" : "none";
        });
        if (mount) {
          mount.innerHTML =
            '<span class="page-btn page-prev' + (page <= 1 ? ' is-disabled' : '') + '" data-pg-action="prev">‹ Trước</span>' +
            '<span class="page-status">Trang ' + page + ' / ' + totalPages + ' (' + items.length + ' mục)</span>' +
            '<span class="page-btn page-next' + (page >= totalPages ? ' is-disabled' : '') + '" data-pg-action="next">Sau ›</span>';
        }
      }

      if (mount) {
        mount.classList.add("pagination", "pagination-list-nav");
        mount.addEventListener("click", function (e) {
          var btn = e.target.closest("[data-pg-action]");
          if (!btn || btn.classList.contains("is-disabled")) return;
          if (btn.getAttribute("data-pg-action") === "prev" && page > 1) page -= 1;
          if (btn.getAttribute("data-pg-action") === "next" && page < totalPages) page += 1;
          render();
          // Panel có thể cao hơn viewport (bảng dài) — cuộn nhẹ về đầu
          // panel khi đổi trang để người dùng không bị "lạc" ở cuối danh
          // sách cũ, nhưng "nearest" tránh giật trang nếu panel đã visible.
          container.scrollIntoView({ block: "nearest", behavior: "smooth" });
        });
      }

      render();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initClientListPagination);
  } else {
    initClientListPagination();
  }

  // ---- Popup chọn/soạn mẫu email liên hệ doanh nghiệp (thêm 08/2026) ----
  //
  // Nút ".btn-email-template" được render lặp lại ở nhiều dòng contact
  // (company_detail.html, contacts.html) — dùng event delegation trên
  // document thay vì gắn listener riêng từng nút, giống pattern submit
  // listener của save-job-form ở trên, để không phải re-bind khi
  // pagination phía client (initClientListPagination) ẩn/hiện lại hàng.
  //
  // 2 bước, không có form/route nào — chỉ hiển thị + copy:
  //   1) etListView  — danh sách 6 mẫu, mẫu khớp trạng thái contact hiện
  //      tại có gắn thẻ "Gợi ý cho trạng thái hiện tại".
  //   2) etDetailView — nội dung mẫu đã điền sẵn tên công ty/người liên
  //      hệ, sửa được trực tiếp trong <textarea>, nhưng KHÔNG lưu lại —
  //      quay lại danh sách hoặc đóng popup là mất phần đã sửa, mở lại
  //      mẫu đó lần sau luôn ra đúng bản gốc.
  var EMAIL_TEMPLATES = [
    {
      id: "intro",
      title: "Giới thiệu MindX",
      desc: "Mở lời làm quen lần đầu, đặt vấn đề hợp tác tuyển dụng Intern/Fresher.",
      recommendedFor: ["UNCONTACTED"],
      body:
        "Tiêu đề: MindX kết nối cơ hội thực tập/fresher cùng {{TEN_CONG_TY}}\n\n" +
        "{{LOI_CHAO}}\n\n" +
        "Em là {{TEN_STAFF}}, phụ trách kết nối doanh nghiệp của MindX — đơn vị đào tạo lập trình, " +
        "Data Analysis và Business Analysis cho học viên trẻ, định hướng đi thực tập/fresher ngay sau khoá học.\n\n" +
        "Em thấy {{TEN_CONG_TY}} là một trong những doanh nghiệp em rất muốn kết nối, nên xin phép chủ động liên hệ " +
        "để tìm hiểu xem hiện tại công ty có đang có nhu cầu tuyển Intern/Fresher ở mảng nào không ạ. " +
        "Nếu có, em rất mong được trao đổi thêm để giới thiệu những học viên phù hợp từ MindX.\n\n" +
        "Em cảm ơn {{TEN_NGUOI_LIEN_HE}} đã dành thời gian đọc email, rất mong nhận được phản hồi ạ.\n\n" +
        "Trân trọng,\n{{TEN_STAFF}}\nStudent Success — MindX",
    },
    {
      id: "ask_jd",
      title: "Xin JD Intern/Fresher",
      desc: "Hỏi xin mô tả công việc cụ thể để giới thiệu đúng học viên.",
      recommendedFor: ["EMAIL_SENT"],
      body:
        "Tiêu đề: Xin thông tin tuyển dụng Intern/Fresher từ {{TEN_CONG_TY}}\n\n" +
        "{{LOI_CHAO}}\n\n" +
        "Em là {{TEN_STAFF}} bên MindX, trước đó có liên hệ giới thiệu về chương trình kết nối việc làm cho học viên ạ.\n\n" +
        "Không biết hiện tại {{TEN_CONG_TY}} có JD (mô tả công việc) nào đang tuyển Intern/Fresher không ạ? " +
        "Nếu có, {{TEN_NGUOI_LIEN_HE}} gửi giúp em JD chi tiết (vị trí, yêu cầu, mức lương/trợ cấp nếu có, deadline) " +
        "để em lọc và giới thiệu đúng học viên phù hợp nhất bên MindX ạ.\n\n" +
        "Em cảm ơn {{TEN_NGUOI_LIEN_HE}} nhiều ạ!\n\n" +
        "Trân trọng,\n{{TEN_STAFF}}\nStudent Success — MindX",
    },
    {
      id: "intro_student",
      title: "Giới thiệu học viên phù hợp",
      desc: "Gửi kèm profile/CV học viên ứng với JD đã có.",
      recommendedFor: ["IN_PARTNERSHIP"],
      body:
        "Tiêu đề: MindX giới thiệu ứng viên cho vị trí Intern/Fresher tại {{TEN_CONG_TY}}\n\n" +
        "{{LOI_CHAO}}\n\n" +
        "Em là {{TEN_STAFF}} bên MindX. Dựa trên JD {{TEN_CONG_TY}} đang tuyển, em xin giới thiệu (các) học viên " +
        "sau đây — CV/profile chi tiết em đính kèm trong email này ạ:\n\n" +
        "- [Tên học viên] — [Kỹ năng/thế mạnh nổi bật, liên quan trực tiếp tới JD]\n\n" +
        "Các bạn đều đã hoàn thành chương trình đào tạo tại MindX và sẵn sàng phỏng vấn/đi làm theo lịch phía công ty. " +
        "{{TEN_NGUOI_LIEN_HE}} xem giúp em, có gì cần trao đổi thêm em luôn sẵn sàng hỗ trợ ạ.\n\n" +
        "Trân trọng,\n{{TEN_STAFF}}\nStudent Success — MindX",
    },
    {
      id: "follow_up",
      title: "Follow-up sau khi gửi profile học viên",
      desc: "Nhắc nhẹ khi chưa thấy phản hồi sau khi đã giới thiệu học viên.",
      recommendedFor: [],
      body:
        "Tiêu đề: Follow-up — hồ sơ học viên MindX gửi {{TEN_CONG_TY}}\n\n" +
        "{{LOI_CHAO}}\n\n" +
        "Em là {{TEN_STAFF}} bên MindX. Tuần trước em có gửi {{TEN_NGUOI_LIEN_HE}} profile một số học viên ứng " +
        "với vị trí Intern/Fresher bên {{TEN_CONG_TY}} đang tuyển ạ.\n\n" +
        "Em xin phép follow-up lại xem {{TEN_NGUOI_LIEN_HE}} đã có dịp xem qua chưa, và bên mình có cần em bổ sung " +
        "thêm hồ sơ hay thông tin gì không ạ. Nếu vị trí đã tuyển đủ hoặc chưa phù hợp, {{TEN_NGUOI_LIEN_HE}} phản hồi " +
        "giúp em 1 câu để em chủ động cập nhật lại phía học viên ạ.\n\n" +
        "Em cảm ơn {{TEN_NGUOI_LIEN_HE}} nhiều!\n\n" +
        "Trân trọng,\n{{TEN_STAFF}}\nStudent Success — MindX",
    },
    {
      id: "thanks",
      title: "Cảm ơn sau khi doanh nghiệp phản hồi",
      desc: "Ghi nhận + giữ nhịp trao đổi sau khi phía công ty trả lời.",
      recommendedFor: ["RESPONDED"],
      body:
        "Tiêu đề: Cảm ơn {{TEN_CONG_TY}} đã phản hồi\n\n" +
        "{{LOI_CHAO}}\n\n" +
        "Em là {{TEN_STAFF}} bên MindX, cảm ơn {{TEN_NGUOI_LIEN_HE}} đã dành thời gian phản hồi email trước của em ạ.\n\n" +
        "[Điền nội dung theo đúng những gì phía công ty vừa phản hồi — ví dụ: xác nhận lịch trao đổi tiếp theo, " +
        "thông tin JD sẽ gửi sau, hoặc bước tiếp theo hai bên đã thống nhất.]\n\n" +
        "Em sẽ theo sát và phối hợp chặt chẽ với {{TEN_NGUOI_LIEN_HE}} trong các bước tiếp theo ạ. " +
        "Rất mong được đồng hành cùng {{TEN_CONG_TY}} trong việc kết nối các bạn học viên tiềm năng.\n\n" +
        "Trân trọng,\n{{TEN_STAFF}}\nStudent Success — MindX",
    },
    {
      id: "quarterly_need",
      title: "Hỏi nhu cầu tuyển dụng tháng/quý",
      desc: "Chủ động hỏi thăm định kỳ với các đối tác đã từng hợp tác.",
      recommendedFor: [],
      body:
        "Tiêu đề: {{TEN_CONG_TY}} có đang cần tuyển Intern/Fresher không ạ?\n\n" +
        "{{LOI_CHAO}}\n\n" +
        "Em là {{TEN_STAFF}} bên MindX. Lâu rồi em chưa có dịp cập nhật lại với {{TEN_NGUOI_LIEN_HE}}, " +
        "không biết thời gian tới {{TEN_CONG_TY}} có kế hoạch tuyển thêm Intern/Fresher ở mảng nào không ạ?\n\n" +
        "Nếu có, em rất mong được {{TEN_NGUOI_LIEN_HE}} chia sẻ sớm để em chuẩn bị và giới thiệu học viên phù hợp " +
        "kịp tiến độ tuyển dụng bên mình ạ. Em luôn sẵn sàng hỗ trợ bất cứ khi nào công ty cần ạ.\n\n" +
        "Trân trọng,\n{{TEN_STAFF}}\nStudent Success — MindX",
    },
  ];

  function initEmailTemplateModal() {
    var modal = document.getElementById("emailTemplateModal");
    if (!modal) return; // trang không load base.html đầy đủ (không nên xảy ra)

    var listView = document.getElementById("etListView");
    var listSub = document.getElementById("etListSub");
    var listEl = document.getElementById("etTemplateList");
    var detailView = document.getElementById("etDetailView");
    var detailTitle = document.getElementById("etDetailTitle");
    var bodyTextarea = document.getElementById("etTemplateBody");
    var closeBtn = document.getElementById("etModalClose");
    var backBtn = document.getElementById("etBackBtn");
    var copyBtn = document.getElementById("etCopyBtn");

    // Ngữ cảnh của LẦN BẤM GẦN NHẤT — nạp lại mỗi lần mở popup, không giữ
    // trạng thái cũ giữa các lần mở khác nhau.
    var ctx = { companyName: "", contactName: "", contactTitle: "", contactStatus: "" };

    function fillPlaceholders(text) {
      var contactName = ctx.contactName || "Anh/Chị phụ trách tuyển dụng";
      var greeting = "Kính gửi " + contactName + (ctx.contactTitle ? " (" + ctx.contactTitle + ")" : "") + ",";
      var staffName = (document.body.getAttribute("data-staff-name") || "").trim() || "[Tên bạn]";
      var companyName = ctx.companyName || "[Tên công ty]";
      return text
        .split("{{LOI_CHAO}}").join(greeting)
        .split("{{TEN_CONG_TY}}").join(companyName)
        .split("{{TEN_NGUOI_LIEN_HE}}").join(contactName)
        .split("{{CHUC_DANH}}").join(ctx.contactTitle || "")
        .split("{{TEN_STAFF}}").join(staffName);
    }

    function renderList() {
      listSub.textContent = ctx.companyName
        ? "Chọn 1 mẫu để soạn email gửi cho " + ctx.contactName + " (" + ctx.companyName + ")."
        : "Chọn 1 mẫu để bắt đầu soạn email.";
      listEl.innerHTML = "";
      EMAIL_TEMPLATES.forEach(function (tpl) {
        var li = document.createElement("li");
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "et-template-item";
        var isRecommended = tpl.recommendedFor.indexOf(ctx.contactStatus) !== -1;
        btn.innerHTML =
          "<strong>" + tpl.title + "</strong><span>" + tpl.desc + "</span>" +
          (isRecommended ? '<span class="et-suggested-tag">Gợi ý cho trạng thái hiện tại</span>' : "");
        btn.addEventListener("click", function () {
          openDetail(tpl);
        });
        li.appendChild(btn);
        listEl.appendChild(li);
      });
      listView.style.display = "";
      detailView.style.display = "none";
    }

    function openDetail(tpl) {
      detailTitle.textContent = tpl.title;
      bodyTextarea.value = fillPlaceholders(tpl.body);
      listView.style.display = "none";
      detailView.style.display = "";
      bodyTextarea.focus();
    }

    function openModal(trigger) {
      ctx.companyName = trigger.getAttribute("data-company-name") || "";
      ctx.contactName = trigger.getAttribute("data-contact-name") || "";
      ctx.contactTitle = trigger.getAttribute("data-contact-title") || "";
      ctx.contactStatus = trigger.getAttribute("data-contact-status") || "";
      renderList();
      modal.style.display = "flex";
    }

    function closeModal() {
      modal.style.display = "none";
      // Reset về danh sách cho lần mở SAU (ở contact khác) không bị dính
      // trạng thái "đang xem chi tiết" của lần trước.
      listView.style.display = "";
      detailView.style.display = "none";
    }

    document.addEventListener("click", function (evt) {
      var trigger = evt.target.closest(".btn-email-template");
      if (trigger) {
        openModal(trigger);
      }
    });

    closeBtn.addEventListener("click", closeModal);
    backBtn.addEventListener("click", renderList);
    modal.addEventListener("click", function (evt) {
      if (evt.target === modal) closeModal(); // click ra ngoài nội dung popup
    });
    document.addEventListener("keydown", function (evt) {
      if (evt.key === "Escape" && modal.style.display !== "none") closeModal();
    });

    copyBtn.addEventListener("click", function () {
      var text = bodyTextarea.value;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(
          function () { showToast("Đã copy nội dung mẫu email!", "success"); },
          function () { fallbackCopy(); }
        );
      } else {
        fallbackCopy();
      }

      function fallbackCopy() {
        // Trình duyệt cũ/không cấp quyền Clipboard API — chọn sẵn text để
        // người dùng tự Ctrl+C, vẫn tốt hơn báo lỗi không làm gì được.
        bodyTextarea.focus();
        bodyTextarea.select();
        try {
          document.execCommand("copy");
          showToast("Đã copy nội dung mẫu email!", "success");
        } catch (e) {
          showToast("Không tự copy được — nội dung đã bôi đen sẵn, bấm Ctrl+C.", "error");
        }
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initEmailTemplateModal);
  } else {
    initEmailTemplateModal();
  }
})();
