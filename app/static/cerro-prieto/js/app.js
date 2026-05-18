/**
 * Panel Cerro Prieto — d02 → rs → verificación/historial → comandos bajo demanda
 */

const API = "/api/cerro-prieto";
const REFRESH_MS = 20000;

const OBJETIVOS_DEFAULT = {
  co2: { 1: 8, 2: 10, 3: 12 },
  o2: { 1: 4, 2: 4, 3: 8 },
};
const TOL_OK = 1;
const TOL_WARN = 2;

const state = {
  data: null,
  pendingAccion: null,
  sending: false,
  comandosOpen: false,
  objetivosOpen: false,
  searchQuery: "",
  objetivos: {
    co2: { ...OBJETIVOS_DEFAULT.co2 },
    o2: { ...OBJETIVOS_DEFAULT.o2 },
  },
};

const $ = (sel) => document.querySelector(sel);

function showToast(msg, ok = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("ok", ok);
  el.classList.remove("hidden");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.classList.add("hidden"), 4500);
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function comandoPendiente(c) {
  return (c.estado ?? 0) > 0 && c.status !== 2;
}

function badgeHtml(pendiente, estadoNum) {
  const cls = pendiente ? "badge-pendiente" : "badge-ejecutado";
  const label = pendiente ? "Pendiente" : "Ejecutado";
  const num = estadoNum != null ? ` (${estadoNum})` : "";
  return `<span class="badge-estado ${cls}">${label}${num}</span>`;
}

function renderVerificacion(data) {
  const grid = $("#verificacionGrid");
  const ultimo = data.ultimo_comando || {};
  const pend = data.comando_pendiente || {};

  const item = (titulo, info) => {
    if (!info.hay_comando) {
      return (
        '<div class="status-item"><strong>' +
        escapeHtml(titulo) +
        '</strong><p class="muted" style="margin:0">Sin registro</p></div>'
      );
    }
    return (
      '<div class="status-item"><strong>' +
      escapeHtml(titulo) +
      "</strong>" +
      badgeHtml(info.pendiente, info.estado) +
      '<p class="status-cmd">' +
      escapeHtml(info.comando || "—") +
      "</p><p class=\"status-meta\">Creado: " +
      escapeHtml(info.fecha_creacion_display || "—") +
      (info.fecha_ejecucion_display
        ? " · Ejecutado: " + escapeHtml(info.fecha_ejecucion_display)
        : "") +
      "</p></div>"
    );
  };

  grid.innerHTML =
    item("Último comando registrado", ultimo) +
    item("En cola (pendiente de envío al equipo)", pend);
}


async function refreshEstadoParaConfirm() {
  const res = await fetch(`${API}/estado`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function getObjetivosFromInputs() {
  return {
    co2: {
      1: parseFloat($("#objCo2Z1").value),
      2: parseFloat($("#objCo2Z2").value),
      3: parseFloat($("#objCo2Z3").value),
    },
    o2: {
      1: parseFloat($("#objO2Z1").value),
      2: parseFloat($("#objO2Z2").value),
      3: parseFloat($("#objO2Z3").value),
    },
  };
}

function setObjetivosInputs(obj) {
  const co2 = obj?.co2 || OBJETIVOS_DEFAULT.co2;
  const o2 = obj?.o2 || OBJETIVOS_DEFAULT.o2;
  const c = (m, z, def) => m[z] ?? m[String(z)] ?? def;
  $("#objCo2Z1").value = c(co2, 1, OBJETIVOS_DEFAULT.co2[1]);
  $("#objCo2Z2").value = c(co2, 2, OBJETIVOS_DEFAULT.co2[2]);
  $("#objCo2Z3").value = c(co2, 3, OBJETIVOS_DEFAULT.co2[3]);
  $("#objO2Z1").value = c(o2, 1, OBJETIVOS_DEFAULT.o2[1]);
  $("#objO2Z2").value = c(o2, 2, OBJETIVOS_DEFAULT.o2[2]);
  $("#objO2Z3").value = c(o2, 3, OBJETIVOS_DEFAULT.o2[3]);
  state.objetivos = getObjetivosFromInputs();
  updateObjetivosResumen();
}

function evaluarLocal(valor, objetivo) {
  if (typeof valor !== "number" || Number.isNaN(valor)) {
    return { estado: "none", desviacion: null, objetivo };
  }
  const diff = Math.abs(valor - objetivo);
  let estado = "danger";
  if (diff <= TOL_OK) estado = "ok";
  else if (diff <= TOL_WARN) estado = "warn";
  return { estado, desviacion: Math.round(diff * 100) / 100, objetivo };
}

function sensorCellHtml(label, valor, meta) {
  const cls = meta.estado && meta.estado !== "none" ? `sensor-${meta.estado}` : "";
  const objTxt =
    meta.objetivo != null
      ? `<span class="sensor-obj">Obj: ${escapeHtml(meta.objetivo)}%</span>`
      : "";
  const desvTxt =
    meta.desviacion != null
      ? `<span class="sensor-desv">Δ ${escapeHtml(meta.desviacion)}%</span>`
      : "";
  const valDisplay = typeof valor === "number" ? valor : "—";
  return `<div class="sensor-cell ${cls}">
      <span class="sensor-label">${escapeHtml(label)}</span>
      <strong class="sensor-valor">${escapeHtml(valDisplay)}${typeof valor === "number" ? "%" : ""}</strong>
      ${objTxt}
      ${desvTxt}
    </div>`;
}

function entryMeta(entry) {
  if (!entry || entry.tipo === "humedad") {
    return { estado: "none", desviacion: null, objetivo: null };
  }
  const z = entry.zona;
  if (entry.tipo === "co2") return evaluarLocal(entry.valor, state.objetivos.co2[z]);
  if (entry.tipo === "o2") return evaluarLocal(entry.valor, state.objetivos.o2[z]);
  return {
    estado: entry.estado || "none",
    desviacion: entry.desviacion ?? null,
    objetivo: entry.objetivo ?? null,
  };
}

function renderD02ZonasHtml(porZona, compact) {
  if (!porZona.length) {
    return '<p class="muted">Sin datos <code>d02</code>.</p>';
  }
  if (compact) {
    return porZona
      .map((row) => {
        const z = row.zona;
        const co2 = row.co2 || {};
        const o2 = row.o2 || {};
        return `<div class="modal-zona-row">
          <span class="modal-zona-label">Z${z}</span>
          ${sensorCellHtml("CO₂", co2.valor, entryMeta(co2))}
          ${sensorCellHtml("O₂", o2.valor, entryMeta(o2))}
        </div>`;
      })
      .join("");
  }
  return porZona
    .map((row) => {
      const z = row.zona;
      const co2 = row.co2 || {};
      const o2 = row.o2 || {};
      return `<article class="zona-card">
        <h3 class="zona-title">Zona ${z}</h3>
        <div class="zona-sensors">
          ${sensorCellHtml("CO₂", co2.valor, entryMeta(co2))}
          ${sensorCellHtml("O₂", o2.valor, entryMeta(o2))}
        </div>
      </article>`;
    })
    .join("");
}

function compresorCellHtml(c) {
  const cls =
    c.estado === "ok"
      ? "compresor-on"
      : c.estado === "danger"
        ? "compresor-off"
        : "compresor-unknown";
  const val =
    c.valor != null && (typeof c.valor === "number" || typeof c.valor === "string")
      ? c.valor
      : "—";
  return `<div class="compresor-cell ${cls}">
      <span class="compresor-label">${escapeHtml(c.label)}</span>
      <strong class="compresor-estado">${escapeHtml(c.etiqueta)}</strong>
      <span class="compresor-meta">Estado ${escapeHtml(c.estado_d02)}: ${escapeHtml(val)}</span>
    </div>`;
}

function renderCompresores(d02) {
  const grid = $("#d02Compresores");
  if (!grid) return;
  const list = d02?.compresores || [];
  if (!list.length) {
    grid.innerHTML = '<p class="muted">Sin datos de compresores.</p>';
    return;
  }
  grid.innerHTML = list.map(compresorCellHtml).join("");
}

function renderD02(data) {
  const d02 = data?.d02 || {};
  const porZona = d02.por_zona || [];
  $("#d02Zonas").innerHTML = renderD02ZonasHtml(porZona, false);
  renderCompresores(d02);

  const humedades = (d02.zonas || []).filter((x) => x.tipo === "humedad");
  const humGrid = $("#d02Grid");
  if (humedades.length) {
    humGrid.classList.remove("hidden");
    humGrid.innerHTML = humedades
      .map(
        (h) => `<div class="sensor-cell sensor-neutral">
          <span class="sensor-label">${escapeHtml(h.label)}</span>
          <strong class="sensor-valor">${escapeHtml(h.valor)}%</strong>
        </div>`
      )
      .join("");
  } else {
    humGrid.classList.add("hidden");
    humGrid.innerHTML = "";
  }

  const flags = d02.flags || [];
  const wrap = $("#d02FlagsWrap");
  if (flags.length) {
    wrap.classList.remove("hidden");
    $("#d02Flags").innerHTML = flags
      .map((f) => `<li>${escapeHtml(f.label)}: <strong>${escapeHtml(f.valor)}</strong></li>`)
      .join("");
  } else {
    wrap?.classList.add("hidden");
  }
}

function renderDatosTotal(data) {
  const el = $("#datosTotalJson");
  if (!el) return;
  const total = data?.datos_total;
  if (!total) {
    el.textContent = data?.sin_datos ? "Sin trama registrada." : "{}";
    return;
  }
  try {
    el.textContent = JSON.stringify(total, null, 2);
  } catch {
    el.textContent = String(total);
  }
}

function renderRs(data) {
  const el = $("#rsBlocks");
  const blocks = data?.rs || [];
  if (!blocks.length) {
    el.innerHTML = '<p class="muted">Sin datos <code>rs</code>.</p>';
    return;
  }
  el.innerHTML = blocks
    .map(
      (b) => `<article class="rs-block">
      <h3>${escapeHtml(b.nombre)}</h3>
      <pre>${escapeHtml(b.raw || `${b.nombre}:${b.datos}&`)}</pre>
    </article>`
    )
    .join("");
}

function getD02Raw(data) {
  const raw = data?.d02_raw ?? data?.d02?.raw;
  return raw != null && String(raw).trim() !== "" ? String(raw).trim() : null;
}

function fillConfirmContext(data) {
  $("#modalContextLoading")?.classList.add("hidden");
  $("#modalD02Section")?.classList.remove("hidden");
  const raw = getD02Raw(data);
  const el = $("#modalD02");
  if (!el) return;
  el.textContent = raw ? `"d02": "${raw}"` : "Sin dato d02.";
}



function onObjetivosInputChange() {
  state.objetivos = getObjetivosFromInputs();
  updateObjetivosResumen();
  if (state.data) {
    renderD02(state.data);
    renderRs(state.data);
    renderDatosTotal(state.data);
  }
}

async function aplicarObjetivos() {
  const obj = getObjetivosFromInputs();
  const body = {
    co2: { 1: obj.co2[1], 2: obj.co2[2], 3: obj.co2[3] },
    o2: { 1: obj.o2[1], 2: obj.o2[2], 3: obj.o2[3] },
  };

  $("#btnAplicarObjetivos").disabled = true;
  try {
    try {
      const fresh = await refreshEstadoParaConfirm();
      state.data = fresh;
      renderD02(fresh);
      renderRs(fresh);
      renderDatosTotal(fresh);
    } catch {
      /* continuar encolando objetivos */
    }

    const res = await fetch(`${API}/objetivos/aplicar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    showToast(data.mensaje || "Objetivos encolados", true);
    await loadEstado();
    $("#verificacionSection")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    showToast(`Error: ${e.message}`);
  } finally {
    $("#btnAplicarObjetivos").disabled = false;
  }
}

function restaurarObjetivos() {
  setObjetivosInputs({ co2: OBJETIVOS_DEFAULT.co2, o2: OBJETIVOS_DEFAULT.o2 });
  updateObjetivosResumen();
  if (state.data) {
    renderD02(state.data);
    renderRs(state.data);
    renderDatosTotal(state.data);
  }
}

function filterAcciones(acciones) {
  const q = state.searchQuery.trim().toLowerCase();
  if (!q) return acciones;
  return acciones.filter(
    (a) =>
      (a.label || "").toLowerCase().includes(q) ||
      (a.grupo || "").toLowerCase().includes(q) ||
      (a.comando || "").toLowerCase().includes(q)
  );
}

function groupAcciones(acciones) {
  const map = new Map();
  for (const a of acciones) {
    const g = a.grupo || "Otros";
    if (!map.has(g)) map.set(g, []);
    map.get(g).push(a);
  }
  return map;
}

function renderAccionesFiltered() {
  const list = $("#accionesList");
  const all = state.data?.acciones || [];
  const filtered = filterAcciones(all);
  const countEl = $("#searchResultCount");
  const clearBtn = $("#btnClearSearch");

  if (clearBtn) {
    clearBtn.classList.toggle("hidden", !state.searchQuery.trim());
  }

  if (!all.length) {
    list.innerHTML = '<p class="muted">Sin acciones configuradas.</p>';
    countEl.textContent = "";
    return;
  }

  countEl.textContent = state.searchQuery.trim()
    ? `${filtered.length} de ${all.length} acciones`
    : `${all.length} acciones disponibles`;

  if (!filtered.length) {
    list.innerHTML = '<p class="muted">Ninguna acción coincide con la búsqueda.</p>';
    return;
  }

  const groups = groupAcciones(filtered);
  let html = "";
  for (const [grupo, items] of groups) {
    html += `<div class="accion-grupo"><h3>${escapeHtml(grupo)}</h3>`;
    for (const a of items) {
      html += `<button type="button" class="btn-accion" data-accion-id="${escapeHtml(a.id)}">
        <span class="btn-accion-label">${escapeHtml(a.label)}</span>
        <span class="btn-accion-cmd">${escapeHtml(a.comando)}</span>
      </button>`;
    }
    html += "</div>";
  }
  list.innerHTML = html;

  list.querySelectorAll(".btn-accion").forEach((btn) => {
    btn.addEventListener("click", () => openConfirm(btn.dataset.accionId));
  });
}

function renderHistorial(comandos) {
  const ul = $("#historialList");
  if (!comandos?.length) {
    ul.innerHTML = '<li class="muted">Sin comandos en el historial reciente.</li>';
    return;
  }

  ul.innerHTML = comandos
    .map((c) => {
      const pend = comandoPendiente(c);
      const estadoUi = pend ? 1 : 0;
      return `<li class="historial-item">
        <div class="historial-head">
          ${badgeHtml(pend, estadoUi)}
          <span class="historial-evento">${escapeHtml(c.evento || c.user || "")}</span>
        </div>
        <p class="cmd">${escapeHtml(c.comando)}</p>
        <p class="historial-fechas">
          <span>Creado: ${escapeHtml(c.fecha_creacion_display || c.fecha_creacion || "—")}</span>
          ${
            c.fecha_ejecucion_display || c.fecha_ejecucion
              ? `<span> · Ejecutado: ${escapeHtml(c.fecha_ejecucion_display || c.fecha_ejecucion)}</span>`
              : '<span class="muted"> · Aún no ejecutado</span>'
          }
        </p>
      </li>`;
    })
    .join("");
}

function setPanelOpen(kind, open) {
  const isCmd = kind === "comandos";
  const body = $(isCmd ? "#comandosPanelBody" : "#objetivosPanelBody");
  const btn = $(isCmd ? "#btnToggleComandos" : "#btnToggleObjetivos");
  if (!body || !btn) return;

  if (isCmd) state.comandosOpen = open;
  else state.objetivosOpen = open;

  body.classList.toggle("hidden", !open);
  btn.classList.toggle("open", open);
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  btn.querySelector(".toggle-icon").textContent = open ? "▾" : "▸";

  if (isCmd) {
    btn.querySelector(".toggle-label").textContent = open
      ? "Ocultar comandos"
      : "Enviar comando al equipo";
    if (open) {
      renderAccionesFiltered();
      setTimeout(() => $("#searchComando")?.focus(), 150);
    }
  } else {
    btn.querySelector(".toggle-label").textContent = open
      ? "Ocultar objetivos"
      : "Modificar objetivos CO₂ / O₂";
  }
}

function toggleComandosPanel() {
  setPanelOpen("comandos", !state.comandosOpen);
}

function toggleObjetivosPanel() {
  setPanelOpen("objetivos", !state.objetivosOpen);
}

function updateObjetivosResumen() {
  const o = state.objetivos;
  const el = $("#objetivosResumen");
  if (!el) return;
  el.textContent = `Objetivos — CO₂: Z1 ${o.co2[1]}% · Z2 ${o.co2[2]}% · Z3 ${o.co2[3]}%  |  O₂: Z1 ${o.o2[1]}% · Z2 ${o.o2[2]}% · Z3 ${o.o2[3]}%`;
}

async function openConfirm(accionId) {
  const accion = (state.data?.acciones || []).find((a) => a.id === accionId);
  if (!accion) return;

  state.pendingAccion = accion;
  $("#modalTitle").textContent = "¿Está seguro?";
  $("#modalAccion").textContent = accion.label;
  $("#modalComando").textContent = accion.comando;
  $("#modalUltimoDato").textContent =
    state.data?.ultima_actualizacion_display || "Sin fecha registrada";

  const loading = $("#modalContextLoading");
  if (loading) {
    loading.classList.remove("hidden");
    loading.textContent = "Cargando d02…";
  }
  $("#modalD02Section")?.classList.add("hidden");
  $("#modalD02").innerHTML = "";

  $("#confirmModal").showModal();

  try {
    const fresh = await refreshEstadoParaConfirm();
    $("#modalUltimoDato").textContent =
      fresh.ultima_actualizacion_display || fresh.ultima_actualizacion || "—";
    fillConfirmContext(fresh);
  } catch (e) {
    $("#modalContextLoading").textContent = `No se pudo actualizar: ${e.message}`;
    if (state.data) fillConfirmContext(state.data);
  }
}

async function enviarComando() {
  if (!state.pendingAccion || state.sending) return;
  state.sending = true;
  $("#modalAccept").disabled = true;
  $("#modalAccept").textContent = "Enviando…";

  try {
    try {
      const fresh = await refreshEstadoParaConfirm();
      fillConfirmContext(fresh);
      $("#modalUltimoDato").textContent =
        fresh.ultima_actualizacion_display || fresh.ultima_actualizacion || "—";
    } catch {
      /* usar snapshot ya mostrado en modal */
    }

    const res = await fetch(`${API}/comando`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accion_id: state.pendingAccion.id }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(body.detail || body.error || `HTTP ${res.status}`);
    }
    $("#confirmModal").close();
    showToast("Comando encolado correctamente", true);
    state.pendingAccion = null;
    setPanelOpen("comandos", false);
    await loadEstado();
    $("#verificacionSection")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    showToast(`Error: ${e.message}`);
  } finally {
    state.sending = false;
    $("#modalAccept").disabled = false;
    $("#modalAccept").textContent = "Sí, enviar comando";
  }
}

function renderAll(data) {
  state.data = data;
  $("#headerImei").textContent = data.imei || "—";
  $("#updatedLine").textContent = data.sin_datos
    ? "El dispositivo aún no ha reportado datos."
    : `Último dato: ${data.ultima_actualizacion_display || data.ultima_actualizacion || "—"}`;

  renderD02(data);
  renderRs(data);
  renderDatosTotal(data);
  renderVerificacion(data);
  renderHistorial(data.comandos_recientes);

  if (state.comandosOpen) {
    renderAccionesFiltered();
  }
}

async function loadEstado() {
  try {
    const res = await fetch(`${API}/estado`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderAll(data);
  } catch (e) {
    showToast(`No se pudo cargar: ${e.message}`);
  }
}

function bindEvents() {
  $("#btnRefresh").addEventListener("click", () => loadEstado());
  $("#btnToggleComandos")?.addEventListener("click", () => toggleComandosPanel());
  $("#btnToggleObjetivos")?.addEventListener("click", () => toggleObjetivosPanel());

  ["objCo2Z1", "objCo2Z2", "objCo2Z3", "objO2Z1", "objO2Z2", "objO2Z3"].forEach((id) => {
    $(`#${id}`)?.addEventListener("input", onObjetivosInputChange);
  });
  $("#btnAplicarObjetivos")?.addEventListener("click", aplicarObjetivos);
  $("#btnRestaurarObjetivos")?.addEventListener("click", restaurarObjetivos);

  let searchDebounce;
  $("#searchComando").addEventListener("input", (e) => {
    state.searchQuery = e.target.value;
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => renderAccionesFiltered(), 120);
  });

  $("#btnClearSearch").addEventListener("click", () => {
    state.searchQuery = "";
    $("#searchComando").value = "";
    renderAccionesFiltered();
    $("#searchComando").focus();
  });

  $("#modalCancel").addEventListener("click", () => $("#confirmModal").close());
  $("#confirmForm").addEventListener("submit", (e) => {
    e.preventDefault();
    enviarComando();
  });
}

bindEvents();
setObjetivosInputs({ co2: OBJETIVOS_DEFAULT.co2, o2: OBJETIVOS_DEFAULT.o2 });
updateObjetivosResumen();
loadEstado();
setInterval(() => loadEstado(), REFRESH_MS);
