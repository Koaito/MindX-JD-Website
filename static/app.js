// MindX Career Hub — small progressive-enhancement helpers.
// Everything here is optional: if JS fails, forms fall back to their
// normal server-rendered POST + redirect behaviour.

(function () {
  "use strict";

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
})();
