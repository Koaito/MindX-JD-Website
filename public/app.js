// MindX Career Hub — small progressive-enhancement helpers.
// Everything here is optional: if JS fails, forms fall back to their
// normal server-rendered POST + redirect behaviour.

(function () {
  "use strict";

  // ---- CSRF token helper --------------------------------------------------
  //
  // Flask-WTF's CSRFProtect checks either the form field "csrf_token" (for
  // normal <form> POSTs, already covered by the hidden input Jinja renders
  // in every form) or the X-CSRFToken header (for fetch()/XHR POSTs, which
  // never submit that hidden field). Reads the token from the <meta
  // name="csrf-token"> tag rendered once in base.html <head>. Exposed on
  // window because _dm_import.html's inline <script> (verify field /
  // resolve duplicate company calls) runs in its own closure and can't see
  // this function otherwise — same pattern as showToast() below.
  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }
  window.getCsrfToken = getCsrfToken;

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
      headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": getCsrfToken() },
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

  // Export (09/2026, xem lịch sử trao đổi "load chậm mỗi lần chuyển
  // phân trang log") — initClientListPagination() ở trên chỉ tự quét
  // DOM 1 LẦN lúc DOMContentLoaded. templates/crawl.html giờ lazy-fetch
  // nội dung tab "status" SAU thời điểm đó (chèn bằng innerHTML khi
  // người dùng bấm sang tab lần đầu) — [data-paginate-size]/
  // [data-paginate-for] bên trong nội dung fetch thêm sẽ KHÔNG được
  // initClientListPagination() quét tới nếu chỉ chạy đúng 1 lần lúc
  // đầu, cần gọi lại thủ công sau khi chèn xong (xem
  // crawl.html::loadTabIfNeeded()).
  window.initClientListPagination = initClientListPagination;

  // ---- Tự lật tooltip "Job mới nhất"/checklist tiêu chí lên trên khi
  // gần đáy màn hình (thêm 08/2026, báo lỗi ảnh chụp) -----------------
  //
  // .potential-suggestion-tooltip mặc định mở XUỐNG DƯỚI (top: 100%,
  // xem 07-forms.css). Với các dòng ở cuối bảng/danh sách (gần cuối
  // viewport), mở xuống dưới sẽ đè lên dòng kế tiếp hoặc bị khuất sau
  // thanh phân trang. Bảng lại phân trang phía CLIENT (ẩn/hiện bằng
  // display, xem initClientListPagination) nên KHÔNG THỂ chỉ dùng CSS
  // :last-child — dòng "cuối" thực tế thay đổi theo trang đang xem, còn
  // DOM order thì cố định. Phải đo bằng JS lúc hover/focus mỗi lần: nếu
  // khoảng trống phía dưới trigger không đủ chứa tooltip thì thêm class
  // .tooltip-flip-up để CSS chuyển sang mở LÊN TRÊN (bottom: 100%).
  function initTooltipAutoFlip() {
    var SELECTOR = ".fit-chip-wrap, .potential-suggestion-wrap";

    function positionTooltip(wrap) {
      var tooltip = wrap.querySelector(".potential-suggestion-tooltip");
      if (!tooltip) return;

      // offsetHeight = 0 khi tooltip đang display:none (chưa từng hiện
      // lần nào) -> bật tạm display:block + visibility:hidden để đo
      // chiều cao thật, không gây nháy vì tắt lại ngay trước khi trả
      // quyền điều khiển display cho CSS :hover/:focus-within như cũ.
      var measuredHeight = tooltip.offsetHeight;
      if (!measuredHeight) {
        var prevDisplay = tooltip.style.display;
        tooltip.style.visibility = "hidden";
        tooltip.style.display = "block";
        measuredHeight = tooltip.offsetHeight;
        tooltip.style.display = prevDisplay;
        tooltip.style.visibility = "";
      }

      var rect = wrap.getBoundingClientRect();
      var spaceBelow = window.innerHeight - rect.bottom;
      // +16 chừa khoảng cách an toàn (margin-top: 6px của tooltip + đệm)
      if (spaceBelow < measuredHeight + 16) {
        tooltip.classList.add("tooltip-flip-up");
      } else {
        tooltip.classList.remove("tooltip-flip-up");
      }
    }

    // mouseover/focusin (bubble được) thay vì mouseenter/focus (không
    // bubble) để dùng ĐƯỢC 1 listener chung trên document, không phải
    // gắn riêng từng .fit-chip-wrap — khớp pattern event delegation đã
    // dùng cho save-job-form/email-template ở trên, không cần re-bind
    // khi initClientListPagination ẩn/hiện lại hàng.
    document.addEventListener("mouseover", function (e) {
      var wrap = e.target.closest(SELECTOR);
      if (wrap) positionTooltip(wrap);
    });
    document.addEventListener("focusin", function (e) {
      var wrap = e.target.closest(SELECTOR);
      if (wrap) positionTooltip(wrap);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTooltipAutoFlip);
  } else {
    initTooltipAutoFlip();
  }

  // ---- Popup chọn/soạn mẫu email liên hệ doanh nghiệp (thêm 08/2026) ----
  //
  // Nút ".btn-email-template" được render lặp lại ở nhiều dòng contact
  // (company_detail.html, contacts.html) — dùng event delegation trên
  // document thay vì gắn listener riêng từng nút, giống pattern submit
  // listener của save-job-form ở trên, để không phải re-bind khi
  // pagination phía client (initClientListPagination) ẩn/hiện lại hàng.
  //
  // 2 bước, không có form/route nào ở POPUP này (route CRUD thật nằm ở
  // tab "Quản lý mẫu email" /contacts?tab=quan-ly) — popup chỉ hiển thị
  // + copy:
  //   1) etListView  — danh sách mẫu (server-render, xem
  //      getEmailTemplatesData() bên dưới), mẫu khớp trạng thái contact
  //      hiện tại có gắn thẻ "Gợi ý cho trạng thái hiện tại".
  //   2) etDetailView — nội dung mẫu đã điền sẵn tên công ty/người liên
  //      hệ, sửa được trực tiếp trong <textarea>, nhưng KHÔNG lưu lại —
  //      quay lại danh sách hoặc đóng popup là mất phần đã sửa, mở lại
  //      mẫu đó lần sau luôn ra đúng bản gốc.
  //
  // 08/2026: trước đây 6 mẫu này HARDCODE cứng ngay trong file JS này
  // (biến EMAIL_TEMPLATES) — giờ persist thật ở backend (CRUD qua tab
  // "Quản lý mẫu email"), base.html render sẵn <script
  // id="emailTemplatesData" type="application/json"> chứa list mẫu hiện
  // tại (xem context_processor inject_email_templates trong app.py),
  // hàm này chỉ đọc + parse JSON đó, KHÔNG tự gọi API riêng — mọi trang
  // load base.html đều có sẵn dữ liệu này ngay lúc render, không cần
  // round-trip mạng thêm khi mở popup.
  function getEmailTemplatesData() {
    var el = document.getElementById("emailTemplatesData");
    if (!el) return [];
    try {
      var parsed = JSON.parse(el.textContent || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return []; // JSON hỏng/không nạp được — popup vẫn mở, chỉ hiện danh sách rỗng thay vì crash cả trang
    }
  }

  function initEmailTemplateModal() {
    var modal = document.getElementById("emailTemplateModal");
    if (!modal) return; // trang không load base.html đầy đủ (không nên xảy ra)

    var EMAIL_TEMPLATES = getEmailTemplatesData();

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
      if (EMAIL_TEMPLATES.length === 0) {
        var emptyLi = document.createElement("li");
        emptyLi.className = "et-template-empty";
        emptyLi.textContent = "Chưa có mẫu email nào — vào \"Quản lý mẫu email\" ở trang Danh sách contact để thêm mẫu mới.";
        listEl.appendChild(emptyLi);
        listView.style.display = "";
        detailView.style.display = "none";
        return;
      }
      EMAIL_TEMPLATES.forEach(function (tpl) {
        var li = document.createElement("li");
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "et-template-item";
        var recommendedFor = tpl.recommended_for || [];
        var isRecommended = recommendedFor.indexOf(ctx.contactStatus) !== -1;
        btn.innerHTML =
          "<strong>" + tpl.title + "</strong><span>" + (tpl.description || "") + "</span>" +
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

// ============================================================
// Hệ thống nhắn tin (thêm 08/2026) — polling khung chat (~5s) +
// badge unread sidebar (20-30s). Vòng đời polling theo đúng
// frontend-mindx-jobs-nhan-tin.md §4: chỉ chạy khi tab active, backoff
// khi lỗi liên tiếp (giãn dần, reset khi thành công lại), dừng hẳn khi
// 401 (không retry vô hạn), dọn interval khi rời trang. App này là MPA
// (mỗi trang tải lại toàn bộ, không phải SPA điều hướng nội bộ) nên
// "rời trang" đã tự dọn interval (context JS bị huỷ theo unload) —
// listener beforeunload dưới đây chỉ là phòng hờ thêm, không phải cơ
// chế dọn chính.
//
// XSS: escapeText() dưới đây BẮT BUỘC dùng textContent, CẤM innerHTML
// cho nội dung tin nhắn (do user nhập) — xem §3, §5
// frontend-mindx-jobs-nhan-tin.md.
(function () {
  "use strict";

  var CHAT_BASE_INTERVAL = 5000;   // 5s — khung chat đang mở
  var CHAT_MAX_INTERVAL = 30000;   // trần backoff
  var BADGE_BASE_INTERVAL = 20000; // 20s — badge sidebar (kế hoạch: 20-30s)
  var BADGE_MAX_INTERVAL = 45000;

  function escapeText(el, text) {
    el.textContent = text; // KHÔNG bao giờ dùng innerHTML ở đây
  }

  function formatMsgTime(iso) {
    try {
      var d = new Date(iso);
      var hh = String(d.getHours()).padStart(2, "0");
      var mm = String(d.getMinutes()).padStart(2, "0");
      var dd = String(d.getDate()).padStart(2, "0");
      var mo = String(d.getMonth() + 1).padStart(2, "0");
      return hh + ":" + mm + " " + dd + "/" + mo;
    } catch (e) {
      return "";
    }
  }

  // Vòng đời poll dùng chung cho cả 2 nơi (khung chat + badge) — nhận
  // vào 1 hàm fetchOnce(onSuccess, onError) để tránh lặp lại y hệt logic
  // backoff/pause/stop-401 2 lần.
  function createPoller(baseInterval, maxInterval, fetchOnce) {
    var interval = baseInterval;
    var timer = null;
    var stopped = false;

    function restartTimer() {
      if (timer) clearInterval(timer);
      if (stopped) return;
      timer = setInterval(tick, interval);
    }

    function tick() {
      if (stopped || document.visibilityState !== "visible") return;
      fetchOnce(
        function onSuccess() {
          if (interval !== baseInterval) {
            interval = baseInterval;
            restartTimer();
          }
        },
        function onUnauthorized() {
          stopped = true;
          if (timer) clearInterval(timer);
        },
        function onError() {
          interval = Math.min(interval * 2, maxInterval);
          restartTimer();
        }
      );
    }

    document.addEventListener("visibilitychange", function () {
      if (stopped) return;
      if (document.visibilityState === "visible") {
        tick();
        restartTimer();
      } else if (timer) {
        clearInterval(timer);
        timer = null;
      }
    });

    window.addEventListener("beforeunload", function () {
      if (timer) clearInterval(timer);
    });

    restartTimer();
    return { stop: function () { stopped = true; if (timer) clearInterval(timer); } };
  }

  function fetchJson(url, onSuccess, onUnauthorized, onError) {
    fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" }, cache: "no-store" })
      .then(function (res) {
        if (res.status === 401) { onUnauthorized(); return null; }
        if (!res.ok) throw new Error("request failed: " + res.status);
        return res.json();
      })
      .then(function (data) { if (data !== null) onSuccess(data); })
      .catch(function () { onError(); });
  }

  // ---- Khung chat: append tin mới, giữ nguyên vị trí cuộn của người đọc ----
  function initChatPolling() {
    var container = document.getElementById("chatMessages");
    if (!container) return;

    var currentUserId = container.getAttribute("data-current-user-id");
    var sinceUrlBase = container.getAttribute("data-since-url");
    var lastId = parseInt(container.getAttribute("data-last-id"), 10) || 0;

    container.scrollTop = container.scrollHeight; // cuộn xuống cuối lúc mở trang

    function appendMessage(msg) {
      var emptyState = container.querySelector(".chat-empty");
      if (emptyState) emptyState.remove();

      var row = document.createElement("div");
      row.className = "msg " + (String(msg.sender_id) === String(currentUserId) ? "msg-out" : "msg-in");
      row.setAttribute("data-id", msg.id);

      var bubble = document.createElement("div");
      bubble.className = "msg-bubble";
      escapeText(bubble, msg.content);

      var time = document.createElement("div");
      time.className = "msg-time";
      escapeText(time, formatMsgTime(msg.created_at));

      row.appendChild(bubble);
      row.appendChild(time);
      container.appendChild(row);
    }

    createPoller(CHAT_BASE_INTERVAL, CHAT_MAX_INTERVAL, function (onSuccess, onUnauthorized, onError) {
      fetchJson(
        sinceUrlBase + "?after_id=" + lastId,
        function (data) {
          var wasAtBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 40;
          data.forEach(function (msg) {
            appendMessage(msg);
            if (msg.id > lastId) lastId = msg.id;
          });
          if (data.length && wasAtBottom) container.scrollTop = container.scrollHeight;
          onSuccess();
        },
        onUnauthorized,
        onError
      );
    });
  }

  // ---- Badge unread sidebar: chạy trên MỌI trang đã đăng nhập ----
  function initUnreadBadgePolling() {
    var badge = document.getElementById("sidebarUnreadBadge");
    if (!badge) return;

    createPoller(BADGE_BASE_INTERVAL, BADGE_MAX_INTERVAL, function (onSuccess, onUnauthorized, onError) {
      fetchJson(
        "/messages/unread-count.json",
        function (data) {
          var count = data.count || 0;
          if (count > 0) {
            badge.textContent = count > 99 ? "99+" : String(count);
            badge.hidden = false;
          } else {
            badge.hidden = true;
          }
          onSuccess();
        },
        onUnauthorized,
        onError
      );
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initChatPolling();
      initUnreadBadgePolling();
    });
  } else {
    initChatPolling();
    initUnreadBadgePolling();
  }
})();
