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

  // ---- Fill the empty cell left by a short final row in the job grid ----
  //
  // .job-grid-3col (templates/index.html only — see public/css/04-job-
  // cards.css) uses `grid-template-columns: repeat(auto-fit, minmax(...))`
  // so the column count is decided by the BROWSER purely from available
  // width — it can render 1, 2, 3, 4+ columns depending on viewport size,
  // sidebar collapsed/expanded state, zoom level, etc. There's no single
  // "3 columns" breakpoint to hardcode in CSS. When the number of cards
  // on the page isn't a multiple of whatever that column count happens
  // to be right now, the final row falls short and leaves empty grid
  // cell(s) on the right (the gap reported on the /viec-lam listing).
  //
  // CSS alone can't fix this generically: nth-child math (e.g. 3n+1)
  // only matches a column count you've hardcoded in advance, so it
  // silently breaks the moment auto-fit resolves to a different column
  // count than the one you wrote the selector for. This instead measures
  // the grid's ACTUAL resolved column count at runtime and stretches
  // however many trailing cards are short to fill the row evenly —
  // correct at every viewport width, with nothing to keep in sync.
  function fillLastJobGridRow() {
    var grids = document.querySelectorAll(".job-grid.job-grid-3col");
    grids.forEach(function (grid) {
      var cards = Array.prototype.slice.call(grid.children);
      if (!cards.length) return;

      // Undo any span from a previous run first (e.g. after a resize that
      // changed the column count) — otherwise a leftover span from a wider
      // layout would incorrectly carry over into a narrower one.
      cards.forEach(function (card) {
        card.style.gridColumnEnd = "";
      });

      // grid-template-columns computes to a space-separated list of
      // resolved track widths (e.g. "360px 360px 360px") regardless of
      // whether the CSS used auto-fit/minmax or fixed values — splitting
      // on whitespace gives the actual current column count.
      var colCount = window.getComputedStyle(grid).gridTemplateColumns.split(" ").length;
      if (colCount <= 1) return; // single column: every card already fills the row

      var remainder = cards.length % colCount;
      if (remainder === 0) return; // last row is already full, nothing to fill

      var shortCards = cards.slice(cards.length - remainder);
      // grid-column-end: span N only accepts a whole number, so when
      // colCount doesn't divide evenly by remainder (e.g. 3 columns
      // short by 2 cards -> 1.5 each, not a valid span) the extra
      // column(s) get distributed one-at-a-time starting from the first
      // short card: floor(colCount/remainder) as the base span for
      // every short card, then +1 for as many of the leading cards as
      // there are leftover columns. E.g. 3 cols / 2 cards -> base=1,
      // leftover=1 -> [span 2, span 1]. 4 cols / 3 cards -> base=1,
      // leftover=1 -> [span 2, span 1, span 1].
      var baseSpan = Math.floor(colCount / remainder);
      var leftoverCols = colCount - baseSpan * remainder;
      shortCards.forEach(function (card, i) {
        var span = baseSpan + (i < leftoverCols ? 1 : 0);
        card.style.gridColumnEnd = "span " + span;
      });
    });
  }

  function initJobGridFill() {
    if (!document.querySelector(".job-grid.job-grid-3col")) return;
    fillLastJobGridRow();

    // Debounced resize listener — recalculates whenever the browser
    // reflows the grid into a different column count (window resize,
    // sidebar collapse/expand changing available width, zoom, etc).
    var resizeTimer;
    window.addEventListener("resize", function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(fillLastJobGridRow, 120);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initJobGridFill);
  } else {
    initJobGridFill();
  }
})();
