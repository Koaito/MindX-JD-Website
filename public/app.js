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

  // NOTE: .job-grid / .job-grid-3col (/viec-lam) and .kpi-row (/dashboard)
  // used to need a JS pass here to stretch a short trailing row of cards
  // to fill empty space — CSS Grid's auto-fit/minmax() fixes the column
  // count from the widest row, so a shorter last row left visible empty
  // cells on the right. They're flexbox now (see public/css/04-job-
  // cards.css and public/css/08-dashboard.css): flex-wrap + flex-grow
  // makes every row, including a short last one, fill its own width
  // natively. No JS needed for this anymore.
})();
