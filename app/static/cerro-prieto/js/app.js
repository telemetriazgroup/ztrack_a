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
  objetivosDirty: false,
  view: "vivo",
  historicoCargado: false,
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
  if (c.cancelado) return false;
  return (c.estado ?? 0) === 1 && c.status !== 2;
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

function objetivosFromApi(apiObj) {
  if (!apiObj?.co2 || !apiObj?.o2) return null;
  const n = (m, z, def) => {
    const v = m[z] ?? m[String(z)];
    const num = parseFloat(v);
    return Number.isFinite(num) ? num : def;
  };
  return {
    co2: {
      1: n(apiObj.co2, 1, OBJETIVOS_DEFAULT.co2[1]),
      2: n(apiObj.co2, 2, OBJETIVOS_DEFAULT.co2[2]),
      3: n(apiObj.co2, 3, OBJETIVOS_DEFAULT.co2[3]),
    },
    o2: {
      1: n(apiObj.o2, 1, OBJETIVOS_DEFAULT.o2[1]),
      2: n(apiObj.o2, 2, OBJETIVOS_DEFAULT.o2[2]),
      3: n(apiObj.o2, 3, OBJETIVOS_DEFAULT.o2[3]),
    },
  };
}

function objetivosResumenTexto(apiObj) {
  const o = objetivosFromApi(apiObj);
  if (!o) return "—";
  return `CO₂: Z1 ${o.co2[1]}% · Z2 ${o.co2[2]}% · Z3 ${o.co2[3]}%  |  O₂: Z1 ${o.o2[1]}% · Z2 ${o.o2[2]}% · Z3 ${o.o2[3]}%`;
}

function syncObjetivosFromApi(data, force = false) {
  if (state.objetivosDirty && !force) return;
  const parsed = objetivosFromApi(data?.objetivos);
  if (!parsed) return;
  setObjetivosInputs(parsed);
  state.objetivosDirty = false;
  updateObjetivosMeta(data?.objetivos);
}

function updateObjetivosMeta(apiObj) {
  const el = $("#objetivosMeta");
  if (!el) return;
  if (apiObj?.actualizado_display) {
    el.textContent = `Guardado: ${apiObj.actualizado_display}${apiObj.user ? ` · ${apiObj.user}` : ""}`;
  } else {
    el.textContent = "Objetivos predeterminados (aún no guardados en panel).";
  }
}

function renderHistorialObjetivos(items) {
  const ul = $("#objetivosHistorial");
  if (!ul) return;
  if (!items?.length) {
    ul.innerHTML = '<li class="muted">Sin cambios registrados.</li>';
    return;
  }
  ul.innerHTML = items
    .map((h) => {
      const ant = objetivosResumenTexto(h.anterior);
      const neu = objetivosResumenTexto(h.nuevo);
      const motivo =
        h.motivo === "aplicar"
          ? "Enviado al equipo"
          : h.motivo === "guardar"
            ? "Solo guardado"
            : h.motivo || "";
      return `<li class="objetivos-historial-item">
        <p class="historial-head">
          <span class="historial-fecha">${escapeHtml(h.fecha_display || h.fecha || "—")}</span>
          <span class="historial-user muted">${escapeHtml([motivo, h.user].filter(Boolean).join(" · "))}</span>
        </p>
        <p class="obj-hist-line"><span class="obj-hist-label">Antes:</span> ${escapeHtml(ant)}</p>
        <p class="obj-hist-line"><span class="obj-hist-label">Nuevo:</span> ${escapeHtml(neu)}</p>
      </li>`;
    })
    .join("");
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

function esReinicioLectura(valor) {
  if (typeof valor !== "number" || Number.isNaN(valor)) return false;
  return Math.abs(valor) < 1e-9 || Math.abs(valor - 25.5) < 1e-6;
}

function fmtPct(valor) {
  const n = Math.round(Number(valor) * 10) / 10;
  if (!Number.isFinite(n)) return "—";
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function valorMostrable(entry) {
  if (!entry) return null;
  const valor = entry.valor;
  if (typeof valor !== "number" || Number.isNaN(valor) || esReinicioLectura(valor)) return null;
  return valor;
}

function tendenciaHtml(tendencia) {
  if (tendencia === "sube") {
    return '<span class="tendencia tendencia-sube" title="Subiendo" aria-label="subiendo">↑</span>';
  }
  if (tendencia === "baja") {
    return '<span class="tendencia tendencia-baja" title="Bajando" aria-label="bajando">↓</span>';
  }
  return "";
}

function sensorCellHtml(label, entry) {
  const meta = entryMeta(entry);
  const valor = valorMostrable(entry);
  const cls = meta.estado && meta.estado !== "none" ? `sensor-${meta.estado}` : "";
  const objTxt =
    meta.objetivo != null
      ? `<span class="sensor-obj">Obj: ${escapeHtml(meta.objetivo)}%</span>`
      : "";
  const desvTxt =
    valor != null && meta.desviacion != null
      ? `<span class="sensor-desv">Δ ${escapeHtml(meta.desviacion)}%</span>`
      : "";
  const nota = entry?.reinicio
    ? `<span class="sensor-reinicio">Último válido${
        entry.fecha_valida_display ? ` · ${escapeHtml(entry.fecha_valida_display)}` : ""
      } · reinicio</span>`
    : "";
  const mostrado = valor == null ? "—" : `${fmtPct(valor)}%`;
  return `<div class="sensor-cell ${cls}">
      <span class="sensor-label">${escapeHtml(label)}</span>
      <strong class="sensor-valor">${mostrado}${tendenciaHtml(entry?.tendencia)}</strong>
      ${objTxt}
      ${desvTxt}
      ${nota}
    </div>`;
}

function entryMeta(entry) {
  if (!entry || entry.tipo === "humedad") {
    return { estado: "none", desviacion: null, objetivo: null };
  }
  const z = entry.zona;
  const valor = valorMostrable(entry);
  if (entry.tipo === "co2") return evaluarLocal(valor, state.objetivos.co2[z]);
  if (entry.tipo === "o2") return evaluarLocal(valor, state.objetivos.o2[z]);
  return {
    estado: entry.estado || "none",
    desviacion: entry.desviacion ?? null,
    objetivo: entry.objetivo ?? null,
  };
}

function controlBadgeHtml(control, zona) {
  const estadoN = { 1: 11, 2: 12, 3: 13 }[zona];
  const activo = control?.activo;
  const cls = activo === true ? "control-on" : activo === false ? "control-off" : "control-unknown";
  const label = control?.etiqueta || "Sin dato de control";
  const title = `Estado ${estadoN}: ${control?.valor ?? "—"} · 1 = activo`;
  return `<span class="control-badge ${cls}" title="${escapeHtml(title)}">${escapeHtml(label)}</span>`;
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
          ${controlBadgeHtml(row.control, z)}
          ${sensorCellHtml("CO₂", co2)}
          ${sensorCellHtml("O₂", o2)}
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
        <header class="zona-head">
          <h3 class="zona-title">Zona ${z}</h3>
          ${controlBadgeHtml(row.control, z)}
        </header>
        <div class="zona-sensors">
          ${sensorCellHtml("CO₂", co2)}
          ${sensorCellHtml("O₂", o2)}
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

const INYECTOR_VALVULAS = [
  { idx: 4, letra: "E", grupo: "CO₂", label: "Válvula CO₂ Zona 1" },
  { idx: 5, letra: "F", grupo: "CO₂", label: "Válvula CO₂ Zona 2" },
  { idx: 6, letra: "G", grupo: "CO₂", label: "Válvula CO₂ Zona 3" },
  { idx: 7, letra: "H", grupo: "Nitrógeno", label: "Válvula N₂ Zona 3" },
  { idx: 8, letra: "I", grupo: "Nitrógeno", label: "Válvula N₂ Zona 2" },
  { idx: 9, letra: "J", grupo: "Nitrógeno", label: "Válvula N₂ Zona 1" },
  { idx: 14, letra: "O", grupo: "Bypass", label: "Bypass de oxígeno" },
];
const INYECTOR_LETRAS = "ABCDEFGHIJKLMNOP";
const INYECTOR_USED_IDX = new Set(INYECTOR_VALVULAS.map((v) => v.idx));

function valvulaInyectorUi(bit) {
  if (bit === "0") return { estado: "ok", etiqueta: "Encendido" };
  if (bit === "1") return { estado: "danger", etiqueta: "Apagado" };
  return { estado: "none", etiqueta: "—" };
}

/** Parsea INYECTOR desde API o, si falta, desde rs / rs_raw (respaldo). */
function resolveInyectorData(data) {
  const api = data?.inyector;
  if (api && api.sin_dato === false && api.bitmap) {
    return api;
  }

  let datos = null;
  const bloque = (data?.rs || []).find(
    (b) => String(b.nombre || "").toUpperCase() === "INYECTOR"
  );
  if (bloque?.datos) {
    datos = bloque.datos;
  } else if (data?.rs_raw) {
    const m = String(data.rs_raw).match(/INYECTOR:([^&]+)/i);
    if (m) datos = m[1];
  }

  if (!datos) {
    return { sin_dato: true };
  }

  const bitmapRaw = String(datos).split(",")[0].trim();
  if (!bitmapRaw || ![...bitmapRaw].every((c) => c === "0" || c === "1")) {
    return { sin_dato: true, bitmap: bitmapRaw, error: "Bitmap inválido" };
  }

  const bitmap = bitmapRaw.padEnd(16, "0").slice(0, 16);
  const valvulas = INYECTOR_VALVULAS.map((spec) => ({
    ...spec,
    bit: bitmap[spec.idx],
    ...valvulaInyectorUi(bitmap[spec.idx]),
  }));
  const grupos = {};
  valvulas.forEach((v) => {
    if (!grupos[v.grupo]) grupos[v.grupo] = [];
    grupos[v.grupo].push(v);
  });
  const mapa_bits = [...bitmap].map((bit, i) => ({
    letra: INYECTOR_LETRAS[i],
    bit,
    usado: INYECTOR_USED_IDX.has(i),
  }));

  return { sin_dato: false, bitmap, valvulas, grupos, mapa_bits, _fuente: "cliente" };
}

function valvulaCellHtml(v) {
  const cls =
    v.estado === "ok" ? "valvula-on" : v.estado === "danger" ? "valvula-off" : "valvula-unknown";
  return `<div class="valvula-cell ${cls}">
      <span class="valvula-label">${escapeHtml(v.label)}</span>
      <strong class="valvula-estado">${escapeHtml(v.etiqueta)}</strong>
      <span class="valvula-meta">${escapeHtml(v.letra)} · bit ${escapeHtml(v.bit)}</span>
    </div>`;
}

function renderInyectores(data) {
  const wrap = $("#inyectorValvulas");
  const bitmapEl = $("#inyectorBitmap");
  const mapaEl = $("#inyectorMapa");
  if (!wrap) return;

  try {
    const inj = resolveInyectorData(data);

    if (inj.sin_dato) {
      if (bitmapEl) bitmapEl.textContent = inj.error || "Sin bloque INYECTOR en rs.";
      mapaEl?.classList.add("hidden");
      wrap.innerHTML = '<p class="muted">Sin datos de inyectores.</p>';
      return;
    }

    if (bitmapEl) {
      const extra = inj._fuente === "cliente" ? ' <span class="muted">(parseado en panel)</span>' : "";
      bitmapEl.innerHTML = `Bitmap: <code>${escapeHtml(inj.bitmap)}</code>${extra}`;
    }

    if (mapaEl && inj.mapa_bits?.length) {
      mapaEl.classList.remove("hidden");
      mapaEl.innerHTML = inj.mapa_bits
        .map((m) => {
          const cls = m.usado ? `mapa-bit-usado mapa-bit-${m.bit}` : "mapa-bit-reservado";
          return `<span class="mapa-bit ${cls}" title="${escapeHtml(m.letra)}=${escapeHtml(m.bit)}">${escapeHtml(m.letra)}<small>${escapeHtml(m.bit)}</small></span>`;
        })
        .join("");
    } else {
      mapaEl?.classList.add("hidden");
    }

    const grupos = inj.grupos || {};
    const orden = ["CO₂", "Nitrógeno", "Bypass"];
    const keys = orden.filter((g) => grupos[g]?.length);
    if (!keys.length && inj.valvulas?.length) {
      wrap.innerHTML = inj.valvulas.map(valvulaCellHtml).join("");
      return;
    }
    wrap.innerHTML = keys
      .map(
        (g) => `<div class="inyector-grupo">
        <h3 class="subheading">${escapeHtml(g)}</h3>
        <div class="valvulas-grid">${(grupos[g] || []).map(valvulaCellHtml).join("")}</div>
      </div>`
      )
      .join("");
  } catch (e) {
    wrap.innerHTML = `<p class="muted">Error al mostrar inyectores: ${escapeHtml(e.message)}</p>`;
  }
}

function renderRs(data) {
  const el = $("#rsBlocks");
  const blocks = (data?.rs || []).filter((b) => (b.nombre || "").toUpperCase() !== "INYECTOR");
  if (!blocks.length) {
    el.innerHTML = '<p class="muted">Sin datos <code>rs</code> (RIPENER / REEFER_QUEST).</p>';
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
  state.objetivosDirty = true;
  state.objetivos = getObjetivosFromInputs();
  updateObjetivosResumen();
  if (state.data) {
    renderD02(state.data);
    renderRs(state.data);
    renderInyectores(state.data);
    renderDatosTotal(state.data);
  }
}

function objetivosBody() {
  const obj = getObjetivosFromInputs();
  const body = {
    co2: { 1: obj.co2[1], 2: obj.co2[2], 3: obj.co2[3] },
    o2: { 1: obj.o2[1], 2: obj.o2[2], 3: obj.o2[3] },
  };
  const nums = [...Object.values(body.co2), ...Object.values(body.o2)];
  if (nums.some((n) => !Number.isFinite(n) || n < 0 || n > 100)) {
    throw new Error("Cada objetivo debe ser un número entre 0 y 100");
  }
  return body;
}

function aplicarRespuestaObjetivos(data) {
  if (data.objetivos) {
    syncObjetivosFromApi({ objetivos: data.objetivos }, true);
    if (state.data) {
      state.data.objetivos = data.objetivos;
      state.data.objetivos_historial = data.objetivos_historial || state.data.objetivos_historial;
      renderD02(state.data);
    }
  }
  if (data.objetivos_historial) {
    renderHistorialObjetivos(data.objetivos_historial);
  }
}

async function guardarObjetivos() {
  let body;
  try {
    body = objetivosBody();
  } catch (e) {
    showToast(e.message);
    return;
  }
  const btn = $("#btnGuardarObjetivos");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${API}/objetivos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    aplicarRespuestaObjetivos(data);
    showToast(data.mensaje || "Objetivos guardados", true);
  } catch (e) {
    showToast(`Error: ${e.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function aplicarObjetivos() {
  let body;
  try {
    body = objetivosBody();
  } catch (e) {
    showToast(e.message);
    return;
  }
  const confirmar = window.confirm(
    "Se encolarán 6 comandos de objetivo CO₂ y O₂ al equipo. ¿Enviar?"
  );
  if (!confirmar) return;

  $("#btnAplicarObjetivos").disabled = true;
  try {
    try {
      const fresh = await refreshEstadoParaConfirm();
      state.data = fresh;
      renderD02(fresh);
      renderRs(fresh);
      renderInyectores(fresh);
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
    aplicarRespuestaObjetivos(data);
    showToast(data.mensaje || "Objetivos enviados al equipo", true);
    await loadEstado();
    $("#verificacionSection")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    showToast(`Error: ${e.message}`);
  } finally {
    $("#btnAplicarObjetivos").disabled = false;
  }
}

function restaurarObjetivos() {
  state.objetivosDirty = true;
  const defs = state.data?.objetivos?.defaults;
  const parsed = objetivosFromApi(defs ? { co2: defs.co2, o2: defs.o2 } : null);
  setObjetivosInputs(parsed || { co2: OBJETIVOS_DEFAULT.co2, o2: OBJETIVOS_DEFAULT.o2 });
  updateObjetivosResumen();
  if (state.data) {
    renderD02(state.data);
    renderRs(state.data);
    renderInyectores(state.data);
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
      : "Objetivos CO₂ / O₂";
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

  syncObjetivosFromApi(data);
  renderHistorialObjetivos(data.objetivos_historial);

  renderD02(data);
  renderRs(data);
  renderInyectores(data);
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

function isoFecha(d) {
  const z = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}

function initHistoricoFechas() {
  const hasta = new Date();
  const desde = new Date();
  desde.setDate(hasta.getDate() - 1);
  const elDesde = $("#histDesde");
  const elHasta = $("#histHasta");
  if (elDesde && !elDesde.value) elDesde.value = isoFecha(desde);
  if (elHasta && !elHasta.value) elHasta.value = isoFecha(hasta);
}

function setView(name) {
  state.view = name === "historico" ? "historico" : "vivo";
  $("#viewVivo")?.classList.toggle("hidden", state.view !== "vivo");
  $("#viewHistorico")?.classList.toggle("hidden", state.view !== "historico");
  document.querySelectorAll(".view-tab").forEach((btn) => {
    const on = btn.dataset.view === state.view;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  if (state.view === "historico" && !state.historicoCargado) {
    cargarHistorico();
  }
}

function histCelda(entry) {
  const valor = valorMostrable(entry);
  const texto = valor == null ? "—" : `${fmtPct(valor)}%`;
  const flecha =
    entry?.tendencia === "sube" ? " ↑" : entry?.tendencia === "baja" ? " ↓" : "";
  const marca = entry?.reinicio ? '<small class="hist-reinicio">reinicio</small>' : "";
  return `<span class="hist-val">${escapeHtml(texto)}${flecha}</span>${marca}`;
}

function renderHistoricoTabla(data) {
  const wrap = $("#historicoTableWrap");
  const resumen = $("#historicoResumen");
  if (!wrap) return;
  const filas = data?.lecturas || [];
  const extra = data?.truncado ? ` Se muestran las ${data.limite} más recientes.` : "";
  if (resumen) {
    resumen.textContent = filas.length
      ? `${filas.length} lecturas entre ${data.desde} y ${data.hasta}.${extra}`
      : `Sin lecturas entre ${data?.desde || "—"} y ${data?.hasta || "—"}.`;
  }
  if (!filas.length) {
    wrap.innerHTML = '<p class="muted">No hay tramas con CO₂ / O₂ en ese rango.</p>';
    return;
  }
  const body = [...filas]
    .reverse()
    .map((row) => {
      const porZona = {};
      (row.zonas || []).forEach((z) => {
        porZona[z.zona] = z;
      });
      const celdas = [1, 2, 3]
        .map((z) => {
          const item = porZona[z] || {};
          return `<td>${histCelda(item.co2)}</td><td>${histCelda(item.o2)}</td>`;
        })
        .join("");
      return `<tr><th scope="row">${escapeHtml(row.fecha_display || row.fecha || "—")}</th>${celdas}</tr>`;
    })
    .join("");
  wrap.innerHTML = `<table class="historico-table">
      <thead>
        <tr>
          <th>Fecha</th>
          <th>Z1 CO₂</th><th>Z1 O₂</th>
          <th>Z2 CO₂</th><th>Z2 O₂</th>
          <th>Z3 CO₂</th><th>Z3 O₂</th>
        </tr>
      </thead>
      <tbody>${body}</tbody>
    </table>`;
}

async function cargarHistorico() {
  initHistoricoFechas();
  const desde = $("#histDesde")?.value;
  const hasta = $("#histHasta")?.value;
  const resumen = $("#historicoResumen");
  const wrap = $("#historicoTableWrap");
  if (!desde || !hasta) {
    showToast("Indique desde y hasta");
    return;
  }
  if (resumen) resumen.textContent = "Consultando…";
  if (wrap) wrap.innerHTML = '<p class="muted">Cargando histórico…</p>';
  const btn = $("#btnHistBuscar");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(
      `${API}/lecturas?desde=${encodeURIComponent(desde)}&hasta=${encodeURIComponent(hasta)}`
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    state.historicoCargado = true;
    renderHistoricoTabla(data);
  } catch (e) {
    state.historicoCargado = false;
    if (resumen) resumen.textContent = "";
    if (wrap) wrap.innerHTML = `<p class="muted">No se pudo consultar: ${escapeHtml(e.message)}</p>`;
    showToast(`Histórico: ${e.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function bindEvents() {
  $("#btnRefresh").addEventListener("click", () => loadEstado());
  $("#btnToggleComandos")?.addEventListener("click", () => toggleComandosPanel());
  $("#btnToggleObjetivos")?.addEventListener("click", () => toggleObjetivosPanel());

  ["objCo2Z1", "objCo2Z2", "objCo2Z3", "objO2Z1", "objO2Z2", "objO2Z3"].forEach((id) => {
    $(`#${id}`)?.addEventListener("input", onObjetivosInputChange);
  });
  $("#btnGuardarObjetivos")?.addEventListener("click", guardarObjetivos);
  $("#btnAplicarObjetivos")?.addEventListener("click", aplicarObjetivos);
  $("#btnRestaurarObjetivos")?.addEventListener("click", restaurarObjetivos);
  document.querySelectorAll(".view-tab").forEach((btn) => {
    btn.addEventListener("click", () => setView(btn.dataset.view));
  });
  $("#historicoForm")?.addEventListener("submit", (e) => {
    e.preventDefault();
    cargarHistorico();
  });
  initHistoricoFechas();

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
loadEstado();
setInterval(() => loadEstado(), REFRESH_MS);
