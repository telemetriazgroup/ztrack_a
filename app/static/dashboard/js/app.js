/**
 * ZTRACK — Panel de flota (consume /api/dashboard/*)
 * Fechas: hora almacenada en BD = reloj GMT-5 (America/Lima), sin conversión UTC.
 */

import { renderDecodedHtml } from "./decode-ui.js";

const API_BASE = "";
const TZ_LABEL = "GMT-5";

const state = {
  tipo: "TermoKing",
  dispositivos: [],
  selectedImei: null,
  zonaHoraria: TZ_LABEL,
  loading: false,
  refreshTimer: null,
  comandosPage: 1,
  comandosMeta: { total: 0, total_pages: 0, page: 1 },
  tramaView: "json",
  decodeCache: {},
  currentTramaRaw: null,
  equipoDirty: false,
};

const COMANDOS_PAGE_SIZE = 10;
const MOBILE_BREAKPOINT = 768;

const $ = (sel) => document.querySelector(sel);

function isMobileView() {
  return window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`).matches;
}

function showToast(msg, ok = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("ok", ok);
  el.classList.remove("hidden");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.classList.add("hidden"), 4000);
}

/**
 * Muestra fecha en GMT-5: prioriza display del API; si no, parsea ISO sin desplazar zona.
 */
function formatDate(iso, displayFromApi) {
  if (displayFromApi) return displayFromApi;
  if (!iso) return "—";
  const m = String(iso).match(
    /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})/
  );
  if (m) {
    const [, y, mo, d, h, mi, s] = m;
    return `${d}/${mo}/${y} ${h}:${mi}:${s} ${state.zonaHoraria || TZ_LABEL}`;
  }
  try {
    const d = new Date(iso);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString("es-PE", {
        timeZone: "America/Lima",
        dateStyle: "short",
        timeStyle: "medium",
      }) + ` ${TZ_LABEL}`;
    }
  } catch {
    /* ignore */
  }
  return iso;
}

function formatUltimoDato(device) {
  return formatDate(device?.ultimo_dato, device?.ultimo_dato_display);
}

function statusLabel(status) {
  const map = {
    online: "Online",
    wait: "En espera",
    offline: "Offline",
  };
  return map[status] || status;
}

function badgeClass(status) {
  return `badge badge-${status}`;
}

function getFilters() {
  return {
    onlineH: parseFloat($("#onlineH").value) || 1,
    waitH: parseFloat($("#waitH").value) || 24,
    search: ($("#searchImei").value || "").trim().toLowerCase(),
    status: $("#filterStatus").value,
  };
}

function filteredDevices() {
  const { search, status } = getFilters();
  return state.dispositivos.filter((d) => {
    if (status !== "all" && d.status !== status) return false;
    if (search) {
      const hay = [
        d.imei,
        d.numero_telemetria,
        d.cliente,
      ]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(search));
      if (!hay) return false;
    }
    return true;
  });
}

function renderStats(totales) {
  $("#statOnline").textContent = totales.online ?? 0;
  $("#statWait").textContent = totales.wait ?? 0;
  $("#statOffline").textContent = totales.offline ?? 0;
  $("#statTotal").textContent = totales.registros ?? 0;
}

function updateSearchUi(list) {
  const search = getFilters().search;
  const total = state.dispositivos.length;
  const shown = list.length;
  const countEl = $("#searchResultCount");
  const clearBtn = $("#btnClearSearch");

  if (clearBtn) {
    clearBtn.classList.toggle("hidden", !search);
  }

  if (!total && state.loading) {
    countEl.textContent = "Cargando…";
    return;
  }
  if (!total) {
    countEl.textContent = "Sin dispositivos en esta flota.";
    return;
  }
  if (search) {
    countEl.textContent =
      shown === 1
        ? `1 resultado de ${total}`
        : `${shown} resultados de ${total}`;
  } else {
    countEl.textContent = `${shown} dispositivo${shown === 1 ? "" : "s"}`;
  }
}

function syncStatusChips() {
  const status = $("#filterStatus").value;
  document.querySelectorAll(".status-chip").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.status === status);
  });
}

function setFilterStatus(status) {
  $("#filterStatus").value = status;
  syncStatusChips();
  renderDeviceLists();
}

function renderDeviceCards() {
  const container = $("#deviceCardList");
  if (!container) return;

  const list = filteredDevices();

  if (!list.length) {
    const search = getFilters().search;
    const msg = search
      ? `No hay IMEI que coincidan con «${search}».`
      : "No hay dispositivos con este filtro de estado.";
    container.innerHTML = `<p class="list-empty" role="status">${escapeHtml(msg)}</p>`;
    updateSearchUi(list);
    return;
  }

  container.innerHTML = list
    .map(
      (d) => `
    <button type="button" class="device-card ${d.imei === state.selectedImei ? "selected" : ""}"
      data-imei="${escapeAttr(d.imei)}" role="listitem">
      <span class="${badgeClass(d.status)}">${statusLabel(d.status)}</span>
      <div class="device-card-main">
        <p class="device-card-imei">${escapeHtml(d.imei)}</p>
        <p class="device-card-meta">${escapeHtml(d.cliente || "Sin cliente")}${d.numero_telemetria ? ` · ${escapeHtml(d.numero_telemetria)}` : ""}</p>
        <p class="device-card-meta">${escapeHtml(formatUltimoDato(d))}</p>
        <p class="device-card-meta">IP: ${escapeHtml(d.last_ip || "—")} · ${d.secured ? "Seguro" : "Sin cifrar"}</p>
      </div>
      <span class="device-card-arrow" aria-hidden="true">›</span>
    </button>`
    )
    .join("");

  container.querySelectorAll(".device-card").forEach((card) => {
    card.addEventListener("click", () => selectDevice(card.dataset.imei));
  });

  updateSearchUi(list);
}

function renderTable() {
  const tbody = $("#deviceTableBody");
  const list = filteredDevices();

  if (!list.length) {
    tbody.innerHTML =
      '<tr><td colspan="8" class="empty">No hay dispositivos que coincidan con el filtro.</td></tr>';
    updateSearchUi(list);
    return;
  }

  tbody.innerHTML = list
    .map(
      (d) => `
    <tr data-imei="${escapeAttr(d.imei)}" class="${d.imei === state.selectedImei ? "selected" : ""}">
      <td><span class="${badgeClass(d.status)}">${statusLabel(d.status)}</span></td>
      <td class="imei-cell">${escapeHtml(d.imei)}</td>
      <td>${escapeHtml(d.numero_telemetria || "—")}</td>
      <td>${escapeHtml(d.cliente || "—")}</td>
      <td>${escapeHtml(formatUltimoDato(d))}</td>
      <td>${escapeHtml(d.last_ip || "—")}</td>
      <td><span class="${d.secured ? "secured-yes" : "secured-no"}">${d.secured ? "Sí" : "No"}</span></td>
      <td><button type="button" class="btn btn-ghost btn-view" data-imei="${escapeAttr(d.imei)}">Ver</button></td>
    </tr>`
    )
    .join("");

  tbody.querySelectorAll("tr[data-imei]").forEach((row) => {
    row.addEventListener("click", () => selectDevice(row.dataset.imei));
  });

  tbody.querySelectorAll(".btn-view").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      selectDevice(btn.dataset.imei);
    });
  });

  updateSearchUi(list);
}

function renderDeviceLists() {
  renderTable();
  renderDeviceCards();
}

function openDetailMobile() {
  if (!isMobileView()) return;
  $("#detailPanel")?.classList.add("detail-open");
  $("#detailBackdrop")?.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function closeDetailMobile() {
  $("#detailPanel")?.classList.remove("detail-open");
  $("#detailBackdrop")?.classList.add("hidden");
  document.body.style.overflow = "";
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(s) {
  return escapeHtml(s).replace(/'/g, "&#39;");
}

function setComandosUi({ loading, empty, rows, pager }) {
  const loadingEl = $(".comandos-loading");
  const emptyEl = $(".comandos-empty");
  const tableEl = $(".comandos-table");
  const pagerEl = $("#comandosPager");
  const body = $("#detailComandosBody");

  loadingEl.classList.toggle("hidden", !loading);
  emptyEl.classList.toggle("hidden", loading || !empty);
  tableEl.classList.toggle("hidden", loading || empty);
  pagerEl.classList.toggle("hidden", loading || empty);

  if (rows && rows.length) {
    body.innerHTML = rows
      .map(
        (c) => `
      <tr>
        <td>${escapeHtml(c.fecha_ejecucion_display || formatDate(c.fecha_ejecucion))}</td>
        <td class="cmd-text">${escapeHtml(c.comando || "—")}</td>
        <td>${escapeHtml(c.user || "—")}</td>
      </tr>`
      )
      .join("");
  } else {
    body.innerHTML = "";
  }

  if (pager) {
    const { page, total_pages, total } = pager;
    $("#comandosPagerInfo").textContent =
      total_pages > 0
        ? `Página ${page} de ${total_pages} (${total} comandos)`
        : "Sin comandos";
    $("#comandosPrev").disabled = page <= 1;
    $("#comandosNext").disabled = page >= total_pages;
  }
}

function renderComandosPayload(data) {
  const comandos = data?.comandos || [];
  if (!comandos.length && (data?.total || 0) === 0) {
    setComandosUi({ loading: false, empty: true, rows: [] });
    $("#comandosPager").classList.add("hidden");
    return;
  }
  setComandosUi({
    loading: false,
    empty: false,
    rows: comandos,
    pager: {
      page: data.page || 1,
      total_pages: data.total_pages || 1,
      total: data.total || comandos.length,
    },
  });
}

async function loadComandos(imei, page = 1) {
  if (!imei) return;
  state.comandosPage = page;
  setComandosUi({ loading: true, empty: false, rows: [] });
  $("#comandosPager").classList.add("hidden");

  try {
    const params = new URLSearchParams({
      tipo: state.tipo,
      page: String(page),
      page_size: String(COMANDOS_PAGE_SIZE),
      dias: "90",
    });
    const res = await fetch(
      `${API_BASE}/api/dashboard/dispositivo/${encodeURIComponent(imei)}/comandos?${params}`
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.zona_horaria) state.zonaHoraria = data.zona_horaria;
    state.comandosMeta = {
      total: data.total ?? 0,
      total_pages: data.total_pages ?? 0,
      page: data.page ?? page,
    };
    if (state.selectedImei === imei) {
      renderComandosPayload(data);
    }
  } catch (e) {
    console.error(e);
    setComandosUi({ loading: false, empty: true, rows: [] });
    $(".comandos-empty").textContent = `No se pudieron cargar comandos: ${e.message}`;
    $("#comandosPager").classList.add("hidden");
  }
}

function setTramaView(view) {
  state.tramaView = view;
  document.querySelectorAll(".trama-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });
  $("#detailTramaJsonWrap").classList.toggle("hidden", view !== "json");
  $("#detailTramaDecodedWrap").classList.toggle("hidden", view !== "decoded");
  if (view === "decoded" && state.currentTramaRaw) {
    loadDecodedView(state.currentTramaRaw);
  }
}

async function loadDecodedView(trama) {
  const cacheKey = `${state.tipo}:${trama.i || state.selectedImei}:${JSON.stringify(trama).length}`;
  $("#decodeLoading").classList.remove("hidden");
  $("#detailTramaDecoded").innerHTML = "";

  if (state.decodeCache[cacheKey]) {
    $("#decodeLoading").classList.add("hidden");
    $("#detailTramaDecoded").innerHTML = renderDecodedHtml(state.decodeCache[cacheKey]);
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/dashboard/decodificar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        trama: { ...trama, i: trama.i || state.selectedImei },
        tipo: state.tipo,
        imei: trama.i || state.selectedImei,
        incluir_oficial: true,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.decodeCache[cacheKey] = data;
    $("#detailTramaDecoded").innerHTML = renderDecodedHtml(data);
  } catch (e) {
    $("#detailTramaDecoded").innerHTML = `<p class="decode-error">Error: ${escapeHtml(e.message)}</p>`;
  } finally {
    $("#decodeLoading").classList.add("hidden");
  }
}

function renderTramaJson(trama) {
  if (!trama) {
    $("#detailTrama").textContent =
      "Sin trama en colección (aún no reportó o batch pendiente).";
    state.currentTramaRaw = null;
    return;
  }
  const copy = { ...trama };
  if (copy.fecha_display) {
    copy.fecha_local = copy.fecha_display;
    delete copy.fecha_display;
  }
  if (copy.received_at_display) {
    copy.received_at_local = copy.received_at_display;
    delete copy.received_at_display;
  }
  state.currentTramaRaw = trama;
  $("#detailTrama").textContent = JSON.stringify(copy, null, 2);
}

function equipoResumenHistorial(snap) {
  if (!snap) return "—";
  if (snap.tipos) {
    const tk = snap.tipos.TermoKing?.activo ? "TK" : "";
    const tun = snap.tipos.Tunel?.activo ? "Tunel" : "";
    return [tk, tun].filter(Boolean).join(" + ") || "Sin conexión";
  }
  const parts = [];
  if (snap.numero_telemetria) parts.push(`Nº ${snap.numero_telemetria}`);
  if (snap.cliente) parts.push(snap.cliente);
  if (snap.notas) parts.push(`Notas: ${snap.notas}`);
  return parts.length ? parts.join(" · ") : "—";
}

function renderEquipoTipos(catalogo) {
  const el = $("#equipoTipos");
  if (!el) return;
  const tipos = catalogo?.tipos || {};
  const chip = (t, label) => {
    const on = tipos[t]?.activo;
    const ult = tipos[t]?.ultima_conexion_display || "—";
    return `<span class="tipo-chip ${on ? "tipo-on" : "tipo-off"}">${label}: ${on ? "inscrito" : "no"} · ${escapeHtml(ult)}</span>`;
  };
  el.innerHTML = chip("TermoKing", "TermoKing") + chip("Tunel", "Túnel");
}

function renderEquipoHistorial(items) {
  const ul = $("#equipoHistorial");
  if (!ul) return;
  if (!items?.length) {
    ul.innerHTML = '<li class="muted">Sin cambios registrados.</li>';
    return;
  }
  ul.innerHTML = items
    .map((h) => {
      const ant = equipoResumenHistorial(h.anterior);
      const neu = equipoResumenHistorial(h.nuevo);
      return `<li class="equipo-historial-item">
        <p class="historial-head">
          <span class="historial-fecha">${escapeHtml(h.fecha_display || h.fecha || "—")}</span>
          <span class="historial-motivo muted">${escapeHtml(h.motivo || "")}</span>
          <span class="historial-user muted">${escapeHtml(h.user || "")}</span>
        </p>
        <p class="eq-hist-line"><span class="eq-hist-label">Antes:</span> ${escapeHtml(ant)}</p>
        <p class="eq-hist-line"><span class="eq-hist-label">Nuevo:</span> ${escapeHtml(neu)}</p>
      </li>`;
    })
    .join("");
}

function fillEquipoFicha(device) {
  const cat = device?.catalogo;
  $("#equipoImei").value = device?.imei || "";
  if (!state.equipoDirty) {
    $("#equipoNumero").value = cat?.numero_telemetria || device?.numero_telemetria || "";
    $("#equipoCliente").value = cat?.cliente || device?.cliente || "";
    $("#equipoNotas").value = cat?.notas || "";
  }
  renderEquipoTipos(cat);
  const meta = $("#equipoMeta");
  if (meta) {
    meta.textContent = cat?.actualizado_display
      ? `Guardado: ${cat.actualizado_display}${cat.user ? ` · ${cat.user}` : ""}`
      : "Aún no inscrito en catálogo (se registrará al guardar o al recibir telemetría).";
  }
}

async function loadEquipoFicha(imei) {
  if (!imei) return;
  try {
    const res = await fetch(`${API_BASE}/api/dashboard/equipos/${encodeURIComponent(imei)}`);
    if (res.status === 404) {
      fillEquipoFicha({ imei, catalogo: null });
      renderEquipoHistorial([]);
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const dev = state.dispositivos.find((d) => d.imei === imei);
    if (dev) {
      dev.catalogo = data.equipo;
      dev.numero_telemetria = data.equipo?.numero_telemetria || "";
      dev.cliente = data.equipo?.cliente || "";
    }
    state.equipoDirty = false;
    fillEquipoFicha({ imei, catalogo: data.equipo });
    renderEquipoHistorial(data.historial || []);
  } catch (e) {
    console.error(e);
    renderEquipoHistorial([]);
  }
}

async function guardarEquipoFicha() {
  const imei = state.selectedImei;
  if (!imei) return;
  const body = {
    numero_telemetria: ($("#equipoNumero").value || "").trim(),
    cliente: ($("#equipoCliente").value || "").trim(),
    notas: ($("#equipoNotas").value || "").trim(),
    user: "dashboard_panel",
  };
  $("#btnGuardarEquipo").disabled = true;
  try {
    const res = await fetch(`${API_BASE}/api/dashboard/equipos/${encodeURIComponent(imei)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    state.equipoDirty = false;
    const dev = state.dispositivos.find((d) => d.imei === imei);
    if (dev && data.equipo) {
      dev.catalogo = data.equipo;
      dev.numero_telemetria = data.equipo.numero_telemetria || "";
      dev.cliente = data.equipo.cliente || "";
      renderDeviceLists();
    }
    fillEquipoFicha({ imei, catalogo: data.equipo });
    renderEquipoHistorial(data.historial || []);
    showToast(data.mensaje || "Ficha guardada", true);
  } catch (e) {
    showToast(`Error al guardar: ${e.message}`);
  } finally {
    $("#btnGuardarEquipo").disabled = false;
  }
}

function renderDetail(device) {
  if (!device) {
    $("#detailPlaceholder").classList.remove("hidden");
    $("#detailContent").classList.add("hidden");
    return;
  }

  $("#detailPlaceholder").classList.add("hidden");
  $("#detailContent").classList.remove("hidden");
  $("#detailImei").textContent = device.imei;
  const badge = $("#detailBadge");
  badge.textContent = statusLabel(device.status);
  badge.className = badgeClass(device.status);

  const tz = state.zonaHoraria || TZ_LABEL;
  $("#detailMeta").innerHTML = `
    <dt>Último dato</dt><dd>${escapeHtml(formatUltimoDato(device))}</dd>
    <dt>IP</dt><dd>${escapeHtml(device.last_ip || "—")}</dd>
    <dt>Seguro</dt><dd>${device.secured ? "Sí" : "No (legacy)"}</dd>
    <dt>Tipo</dt><dd>${escapeHtml(device.tipo || state.tipo)}</dd>
    <dt>Zona horaria</dt><dd>${escapeHtml(tz)}</dd>
  `;

  setTramaView("json");
  renderTramaJson(device.ultima_trama);

  state.comandosPage = 1;
  state.equipoDirty = false;
  fillEquipoFicha(device);
  loadEquipoFicha(device.imei);
  loadComandos(device.imei, 1);
}

function selectDevice(imei) {
  state.selectedImei = imei;
  state.comandosPage = 1;
  renderDeviceLists();
  const device = state.dispositivos.find((d) => d.imei === imei);
  renderDetail(device);
  if (device && isMobileView()) {
    openDetailMobile();
  }
}

function tryOpenExactImei() {
  const search = getFilters().search;
  if (!search) return;
  const exact = state.dispositivos.find(
    (d) => (d.imei || "").toLowerCase() === search
  );
  if (exact) {
    selectDevice(exact.imei);
    $("#searchImei").blur();
  }
}

async function loadFlota() {
  if (state.loading) return;
  state.loading = true;
  document.querySelector(".list-section")?.classList.add("loading");

  const { onlineH, waitH } = getFilters();
  const params = new URLSearchParams({
    tipo: state.tipo,
    online_h: String(onlineH),
    wait_h: String(waitH),
    incluir_trama: "true",
  });

  try {
    const res = await fetch(`${API_BASE}/api/dashboard/flota?${params}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || `HTTP ${res.status}`);
    }
    const data = await res.json();

    if (data.zona_horaria) state.zonaHoraria = data.zona_horaria;

    state.dispositivos = data.dispositivos || [];
    renderStats(data.totales || {});

    const umb = data.umbrales || {};
    const refDisplay =
      data.referencia_servidor_display ||
      formatDate(data.referencia_servidor);
    $("#metaRef").textContent = `Actualizado: ${refDisplay}`;
    $("#metaCol").textContent = data.coleccion
      ? `${data.coleccion} · Online ≤ ${umb.online_hasta_horas}h · Wait ≤ ${umb.wait_hasta_horas}h · ${state.zonaHoraria}`
      : state.zonaHoraria;

    if (
      state.selectedImei &&
      !state.dispositivos.some((d) => d.imei === state.selectedImei)
    ) {
      state.selectedImei = null;
      state.comandosPage = 1;
    }

    renderDeviceLists();
    if (state.selectedImei) {
      const dev = state.dispositivos.find((d) => d.imei === state.selectedImei);
      renderDetail(dev);
    }
  } catch (e) {
    console.error(e);
    showToast(`Error al cargar: ${e.message}`);
    $("#deviceTableBody").innerHTML =
      '<tr><td colspan="8" class="empty">Error al conectar con la API.</td></tr>';
    const cardList = $("#deviceCardList");
    if (cardList) {
      cardList.innerHTML =
        '<p class="list-empty">Error al conectar con la API.</p>';
    }
    $("#searchResultCount").textContent = "Error de conexión";
  } finally {
    state.loading = false;
    document.querySelector(".list-section")?.classList.remove("loading");
  }
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      state.tipo = tab.dataset.tipo;
      state.selectedImei = null;
      state.comandosPage = 1;
      state.decodeCache = {};
      closeDetailMobile();
      renderDetail(null);
      loadFlota();
    });
  });
}

function setupAutoRefresh() {
  const tick = () => {
    if ($("#autoRefresh").checked) loadFlota();
  };
  clearInterval(state.refreshTimer);
  state.refreshTimer = setInterval(tick, 30000);
}

function bindEvents() {
  $("#btnRefresh").addEventListener("click", () => loadFlota());
  $("#autoRefresh").addEventListener("change", setupAutoRefresh);

  ["onlineH", "waitH"].forEach((id) => {
    $(`#${id}`).addEventListener("change", () => loadFlota());
  });

  let searchDebounce;
  $("#searchImei").addEventListener("input", () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => renderDeviceLists(), 150);
  });

  $("#searchImei").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      tryOpenExactImei();
    }
  });

  $("#btnClearSearch")?.addEventListener("click", () => {
    $("#searchImei").value = "";
    renderDeviceLists();
    $("#searchImei").focus();
  });

  document.querySelectorAll(".status-chip").forEach((chip) => {
    chip.addEventListener("click", () => setFilterStatus(chip.dataset.status));
  });

  $("#filterStatus").addEventListener("change", () => {
    syncStatusChips();
    renderDeviceLists();
  });

  $("#btnDetailBack")?.addEventListener("click", () => {
    closeDetailMobile();
    state.selectedImei = null;
    renderDeviceLists();
    renderDetail(null);
  });

  $("#detailBackdrop")?.addEventListener("click", () => {
    $("#btnDetailBack")?.click();
  });

  window.addEventListener("resize", () => {
    if (!isMobileView()) {
      closeDetailMobile();
    }
  });

  $("#comandosPrev").addEventListener("click", () => {
    if (!state.selectedImei || state.comandosPage <= 1) return;
    loadComandos(state.selectedImei, state.comandosPage - 1);
  });

  $("#comandosNext").addEventListener("click", () => {
    if (!state.selectedImei) return;
    if (state.comandosPage >= state.comandosMeta.total_pages) return;
    loadComandos(state.selectedImei, state.comandosPage + 1);
  });

  document.querySelectorAll(".trama-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const view = btn.dataset.view;
      setTramaView(view);
    });
  });

  ["equipoNumero", "equipoCliente", "equipoNotas"].forEach((id) => {
    $(`#${id}`)?.addEventListener("input", () => {
      state.equipoDirty = true;
    });
  });
  $("#btnGuardarEquipo")?.addEventListener("click", () => guardarEquipoFicha());

  document.addEventListener("keydown", (e) => {
    if (e.key === "r" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      loadFlota();
    }
  });
}

async function init() {
  setupTabs();
  bindEvents();
  syncStatusChips();
  setupAutoRefresh();
  await loadFlota();
}

init();
