(() => {
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) { tg.ready(); tg.expand(); }
  const initData = tg ? tg.initData : "";

  const $ = (id) => document.getElementById(id);
  let meta = null;
  let draft = null;
  let selectedFiles = [];

  // ---------- helpers ----------
  async function api(path, opts = {}) {
    const headers = Object.assign({ "X-Telegram-Init-Data": initData }, opts.headers || {});
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).detail || msg; } catch (_) {}
      throw new Error(msg);
    }
    return res.json();
  }
  function busy(text) { $("overlay-text").textContent = text || ""; $("overlay").classList.toggle("hidden", !text); }
  function show(id) { document.querySelectorAll(".screen").forEach((s) => s.classList.add("hidden")); $(id).classList.remove("hidden"); window.scrollTo(0, 0); }
  function alertErr(e) { const m = e && e.message ? e.message : String(e); if (tg && tg.showAlert) tg.showAlert(m); else alert(m); }
  function imgUrl(img) { return `/api/drafts/${draft.id}/images/${img.id}`; }

  // ---------- шаг 1 ----------
  $("photos").addEventListener("change", (ev) => {
    selectedFiles = Array.from(ev.target.files || []).slice(0, 6);
    const box = $("thumbs"); box.innerHTML = "";
    selectedFiles.forEach((f) => { const img = document.createElement("img"); img.src = URL.createObjectURL(f); box.appendChild(img); });
  });

  $("btn-build").addEventListener("click", async () => {
    if (!selectedFiles.length) return alertErr(new Error("Добавьте хотя бы одно фото"));
    const fd = new FormData();
    selectedFiles.forEach((f) => fd.append("photos", f, f.name || "photo.jpg"));
    fd.append("note", $("note").value);
    fd.append("purchase_price", $("purchase_price").value || "0");
    busy(meta && meta.image_search ? "Claude смотрит фото и ищет картинки…" : "Claude смотрит фото…");
    try {
      draft = await api("/api/drafts", { method: "POST", body: fd });
      renderPreview();
      show("screen-preview");
    } catch (e) { alertErr(e); } finally { busy(""); }
  });

  // ---------- шаг 2 ----------
  function fillSelect(sel, entries, selectedIds, multiple) {
    sel.innerHTML = "";
    if (!multiple) { const o = document.createElement("option"); o.value = ""; o.textContent = "— не выбрана —"; sel.appendChild(o); }
    entries.forEach((e) => {
      const o = document.createElement("option"); o.value = e.id; o.textContent = e.title;
      o.selected = selectedIds.includes(e.id); sel.appendChild(o);
    });
  }

  function renderPreview() {
    $("uncertainties").textContent = draft.uncertainties ? "Claude не уверен: " + draft.uncertainties : "";
    $("uncertainties").classList.toggle("hidden", !draft.uncertainties);
    const box = $("preview-images"); box.innerHTML = "";
    draft.images.forEach((img) => {
      const wrap = document.createElement("div"); wrap.className = "thumb" + (img.selected ? "" : " off");
      const el = document.createElement("img"); el.src = imgUrl(img);
      const badge = document.createElement("span"); badge.className = "badge"; badge.textContent = img.kind === "web" ? "интернет" : "моё";
      wrap.appendChild(el); wrap.appendChild(badge);
      wrap.addEventListener("click", () => { img.selected = !img.selected; wrap.classList.toggle("off", !img.selected); });
      box.appendChild(wrap);
    });
    $("f-title").value = draft.title;
    fillSelect($("f-category"), meta.categories, draft.category_id ? [draft.category_id] : [], false);
    fillSelect($("f-collections"), meta.collections, draft.collection_ids, true);
    $("f-purchase").value = draft.purchase_price || "";
    $("f-retail").value = draft.retail_price || "";
    $("f-qty").value = draft.quantity;
    $("f-sku").textContent = draft.sku;
    $("f-description").value = draft.description_html;
    $("correction").value = "";
    $("btn-publish").textContent = meta.dry_run ? "Проверить (тестовый режим, в магазин не пишем)" : "Опубликовать в InSales";
  }

  function collectPatch() {
    return {
      title: $("f-title").value.trim(),
      description_html: $("f-description").value,
      category_id: $("f-category").value ? Number($("f-category").value) : null,
      collection_ids: Array.from($("f-collections").selectedOptions).map((o) => Number(o.value)),
      purchase_price: Number($("f-purchase").value || 0),
      retail_price: Number($("f-retail").value || 0),
      quantity: Number($("f-qty").value || 0),
      images: draft.images,
    };
  }

  async function savePatch() {
    const patch = collectPatch();
    // Если закупка изменилась, сервер пересчитает розницу сам: не слать старую розницу.
    if (patch.purchase_price !== draft.purchase_price) delete patch.retail_price;
    draft = await api(`/api/drafts/${draft.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
  }

  $("f-purchase").addEventListener("change", async () => {
    try { busy("Пересчёт цены…"); await savePatch(); renderPreview(); } catch (e) { alertErr(e); } finally { busy(""); }
  });

  $("btn-revise").addEventListener("click", async () => {
    const correction = $("correction").value.trim();
    if (!correction) return;
    busy("Claude вносит правку…");
    try {
      await savePatch();
      draft = await api(`/api/drafts/${draft.id}/revise`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ correction }) });
      renderPreview();
    } catch (e) { alertErr(e); } finally { busy(""); }
  });

  $("btn-publish").addEventListener("click", async () => {
    busy("Отправляем в InSales…");
    try {
      await savePatch();
      draft = await api(`/api/drafts/${draft.id}/publish`, { method: "POST" });
      $("done-title").textContent = draft.status === "dry_run" ? "Тестовый прогон прошёл" : "Товар создан";
      $("done-text").textContent = draft.status === "dry_run"
        ? "INSALES_DRY_RUN=true: карточка собрана, в магазин ничего не записано. Payload в логах сервера."
        : `«${draft.title}», артикул ${draft.sku}, цена ${draft.retail_price} ₽` + (meta.create_hidden ? ". Товар создан скрытым, включите его в админке." : "");
      const a = $("done-link");
      if (draft.admin_url && draft.admin_url.startsWith("http")) { a.href = draft.admin_url; a.textContent = "Открыть в админке InSales"; a.classList.remove("hidden"); }
      else a.classList.add("hidden");
      show("screen-done");
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    } catch (e) { alertErr(e); } finally { busy(""); }
  });

  $("btn-cancel").addEventListener("click", async () => {
    try { await api(`/api/drafts/${draft.id}`, { method: "DELETE" }); } catch (_) {}
    resetInput(); show("screen-input");
  });

  // ---------- шаг 3 ----------
  $("btn-another").addEventListener("click", () => { resetInput(); show("screen-input"); });

  function resetInput() {
    draft = null; selectedFiles = [];
    $("photos").value = ""; $("thumbs").innerHTML = ""; $("note").value = ""; $("purchase_price").value = "";
  }

  // ---------- старт ----------
  (async () => {
    try {
      meta = await api("/api/meta");
      const parts = [];
      if (meta.dry_run) parts.push("тестовый режим");
      if (!meta.image_search) parts.push("поиск фото в интернете выключен");
      if (!meta.categories.length) parts.push("категории не загружены");
      $("status-line").textContent = parts.join(" · ");
    } catch (e) {
      $("status-line").textContent = "Нет доступа: " + e.message;
      $("btn-build").disabled = true;
    }
  })();
})();
