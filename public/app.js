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
})();
