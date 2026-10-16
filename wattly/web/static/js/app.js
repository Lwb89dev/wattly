/* WATTLY app behaviour: theme, upload, bulk auto-import, band editor,
   confirm dialogs, compare selectors. Strings come from the i18n catalog
   injected by base.html as window.WATTLY_I18N.
   Progressive enhancement — everything works (less conveniently) without JS. */
(function () {
  "use strict";

  var I18N = window.WATTLY_I18N || {};
  function _(key, params) {
    var s = I18N[key] || key;
    if (params) {
      Object.keys(params).forEach(function (k) {
        s = s.replace("{" + k + "}", params[k]);
      });
    }
    return s;
  }

  /* ---------------- theme ---------------- */
  function currentTheme() {
    return document.documentElement.dataset.theme || "light";
  }

  function setTheme(theme, persist) {
    document.documentElement.dataset.theme = theme;
    if (persist) {
      localStorage.setItem("wattly-theme", theme);
      fetch("/settings/theme", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "theme=" + encodeURIComponent(theme === "auto" ? "auto" : theme),
      }).catch(() => {});
    }
    if (window.Wattly && Wattly.charts) Wattly.charts.refresh();
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action='theme-toggle']");
    if (btn) setTheme(currentTheme() === "dark" ? "light" : "dark", true);
  });

  /* ---------------- flash auto-hide ---------------- */
  window.setTimeout(() => {
    document.querySelectorAll("[data-autohide]").forEach((el) => {
      el.style.transition = "opacity .4s";
      el.style.opacity = "0";
      window.setTimeout(() => el.remove(), 420);
    });
  }, 5200);

  /* ---------------- confirm dialogs ---------------- */
  document.addEventListener("submit", (e) => {
    const form = e.target.closest("form[data-confirm]");
    if (form && !window.confirm(form.dataset.confirm)) e.preventDefault();
  });

  /* ---------------- band editor ---------------- */
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-add-band]")) {
      const tpl = document.getElementById("band-row-template");
      const rows = document.getElementById("band-rows");
      if (tpl && rows) rows.appendChild(tpl.content.cloneNode(true));
    }
    const rm = e.target.closest("[data-remove-band]");
    if (rm) rm.closest(".band-row").remove();
  });

  /* ---------------- dropzone upload ---------------- */
  const dz = document.getElementById("dropzone");
  if (dz) initDropzone(dz);

  function statusBadge(item, text, kind) {
    let status = item.querySelector(".upload-status");
    if (!status) {
      status = document.createElement("span");
      status.className = "upload-status";
      item.appendChild(status);
    }
    status.textContent = text;
    status.className = "upload-status badge badge-" + kind;
    return status;
  }

  function initDropzone(zone) {
    const input = document.getElementById("file-input");
    const results = document.getElementById("upload-results");
    const url = zone.dataset.uploadUrl;

    zone.addEventListener("click", () => input.click());
    zone.addEventListener("dragover", (e) => {
      e.preventDefault();
      zone.classList.add("dragging");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("dragging");
      handleFiles(e.dataTransfer.files);
    });
    input.addEventListener("change", () => handleFiles(input.files));

    function handleFiles(files) {
      Array.from(files).forEach((f) => uploadOne(f));
      input.value = "";
    }

    function uploadOne(file) {
      const item = document.createElement("div");
      item.className = "upload-item";
      item.innerHTML =
        '<span class="spinner"></span><span class="upload-name"></span>' +
        '<span class="upload-status dim"></span>';
      item.querySelector(".upload-name").textContent = file.name;
      results.prepend(item);

      const fd = new FormData();
      fd.append("file", file);
      fetch(url, { method: "POST", body: fd })
        .then((r) => r.json().then((data) => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
          item.querySelector(".spinner").remove();
          if (!ok || !data.ok) {
            statusBadge(item, data.error || _("js.upload_failed"), "error");
            return;
          }
          item.dataset.docId = data.doc_id;
          if (data.duplicate) {
            statusBadge(item, _("js.already_imported"), "warn");
          } else {
            statusBadge(item, _("js.extracted_review"), "ok");
          }
          const link = document.createElement("a");
          link.className = "btn btn-sm btn-primary";
          link.style.marginLeft = "auto";
          link.href = "/import/review/" + data.doc_id;
          link.textContent = _("js.review");
          item.appendChild(link);
          bumpPending(1);
        })
        .catch(() => {
          const sp = item.querySelector(".spinner");
          if (sp) sp.remove();
          statusBadge(item, _("js.network_error"), "error");
        });
    }
  }

  /* ---------------- bulk auto-import ---------------- */
  const autoCard = document.getElementById("auto-import-card");
  if (autoCard) {
    const btn = document.getElementById("auto-import-btn");
    const out = document.getElementById("auto-results");
    let pending = parseInt(autoCard.dataset.pending || "0", 10);

    function bumpPending(delta) {
      pending = Math.max(0, pending + delta);
      const badge = btn.querySelector(".badge");
      if (badge) badge.textContent = pending;
      if (pending === 0) btn.setAttribute("disabled", "");
    }

    window.bumpPending = bumpPending;

    btn.addEventListener("click", () => {
      if (btn.hasAttribute("disabled")) return;
      btn.setAttribute("disabled", "");
      const spinner = document.createElement("span");
      spinner.className = "spinner";
      spinner.style.marginRight = "8px";
      btn.prepend(spinner);

      fetch(autoCard.dataset.url, { method: "POST" })
        .then((r) => r.json())
        .then((data) => {
          spinner.remove();
          if (!data.ok) {
            btn.removeAttribute("disabled");
            out.innerHTML =
              '<div class="alert alert-error" style="margin-top:14px">' +
              (data.error || _("js.network_error")) + "</div>";
            return;
          }
          renderAutoResults(data);
          // refresh the uploads table so linked bills appear
          window.setTimeout(() => window.location.reload(), 2500);
        })
        .catch(() => {
          spinner.remove();
          btn.removeAttribute("disabled");
          out.innerHTML =
            '<div class="alert alert-error" style="margin-top:14px">' +
            _("js.network_error") + "</div>";
        });
    });

    function renderAutoResults(data) {
      const imported = (data.imported || []).length;
      const review = (data.review || []).length;
      const dup = (data.duplicates || []).length;
      const failed = (data.errors || []).length;

      const banner = document.createElement("div");
      banner.className = "alert alert-" + (imported > 0 ? "success" : "info");
      banner.style.marginTop = "14px";
      banner.innerHTML = "<span>" + _("js.auto_done", { ok: imported, review: review, dup: dup }) +
        (failed ? " · " + failed + " ✗" : "") + "</span>";
      out.appendChild(banner);

      (data.imported || []).forEach((r) => markItem(r.doc_id, _("imp.auto_imported"), "ok"));
      (data.review || []).forEach((r) => markItem(r.doc_id, _("imp.auto_needs_review"), "warn"));
      (data.duplicates || []).forEach((r) => markItem(r.doc_id, _("imp.auto_duplicate"), "warn"));
      (data.errors || []).forEach((r) => markItem(r.doc_id, _("imp.auto_failed"), "error"));

      const newPending = parseInt(data.pending || "0", 10);
      pending = newPending;
      const badge = btn.querySelector(".badge");
      if (badge) badge.textContent = newPending;
      if (newPending === 0) btn.setAttribute("disabled", "");
      else btn.removeAttribute("disabled");
    }

    function markItem(docId, text, kind) {
      const item = document.querySelector('.upload-item[data-doc-id="' + docId + '"]');
      if (item) {
        item.querySelectorAll(".btn").forEach((b) => b.remove());
        statusBadge(item, text, kind);
      }
    }
  }

  /* ---------------- compare selectors ---------------- */
  document.querySelectorAll(".selector").forEach((sel) => {
    const kindSelect = sel.querySelector(".kind-select");
    const slot = sel.querySelector(".value-slot");
    const name = slot.dataset.name;
    const initial = slot.dataset.value || "";
    const months = JSON.parse(sel.dataset.months || "[]");
    const providers = JSON.parse(sel.dataset.providers || "[]");

    const builders = {
      month: () => selectControl(months, initial, _("js.month_placeholder")),
      provider: () => selectControl(providers, initial, _("js.provider_placeholder")),
      quarter: () => textControl(initial, _("js.quarter_placeholder")),
      year: () => textControl(initial, String(new Date().getFullYear())),
      season: () =>
        selectControl(
          [["winter", _("cmp.season_winter")], ["spring", _("cmp.season_spring")],
           ["summer", _("cmp.season_summer")], ["autumn", _("cmp.season_autumn")]],
          initial, "summer"
        ),
      range: () => rangeControl(initial),
    };

    function hidden(value) {
      const h = document.createElement("input");
      h.type = "hidden";
      h.name = name;
      h.value = value;
      return h;
    }

    function textControl(value, placeholder) {
      const wrap = document.createElement("div");
      wrap.appendChild(hidden(value));
      const input = document.createElement("input");
      input.type = "text";
      input.value = value;
      input.placeholder = placeholder;
      input.addEventListener("input", () => (wrap.querySelector("input[type=hidden]").value = input.value));
      wrap.appendChild(input);
      return wrap;
    }

    function selectControl(options, value, freePlaceholder) {
      const wrap = document.createElement("div");
      wrap.appendChild(hidden(value));
      const s = document.createElement("select");
      let matched = false;
      options.forEach((opt) => {
        const [val, label] = Array.isArray(opt) ? opt : [opt, opt];
        const o = document.createElement("option");
        o.value = val;
        o.textContent = label;
        if (String(val) === String(value)) {
          o.selected = true;
          matched = true;
        }
        s.appendChild(o);
      });
      if (!matched && value) {
        const o = document.createElement("option");
        o.value = value;
        o.textContent = value;
        o.selected = true;
        s.appendChild(o);
      }
      s.addEventListener("change", () => (wrap.querySelector("input[type=hidden]").value = s.value));
      wrap.appendChild(s);
      return wrap;
    }

    function rangeControl(value) {
      const [from = "", to = ""] = String(value).split(":");
      const wrap = document.createElement("div");
      wrap.style.display = "flex";
      wrap.style.gap = "10px";
      const h = hidden(value);
      const a = document.createElement("input");
      const b = document.createElement("input");
      [a, b].forEach((i) => (i.type = "date"));
      a.value = from;
      b.value = to;
      const sync = () => (h.value = a.value + ":" + b.value);
      a.addEventListener("input", sync);
      b.addEventListener("input", sync);
      wrap.appendChild(h);
      wrap.appendChild(a);
      wrap.appendChild(b);
      return wrap;
    }

    function render() {
      const kind = kindSelect.value;
      slot.querySelectorAll("input, select, div").forEach((n) => n.remove());
      const label = document.createElement("label");
      label.textContent = _("js.value");
      slot.appendChild(label);
      slot.appendChild((builders[kind] || builders.month)());
    }

    kindSelect.addEventListener("change", render);
    render();
  });
})();
