/**
 * Renderizado de tramas decodificadas (API /api/dashboard/decodificar).
 */

export function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderCanal(c) {
  const tipo = c.tipo || "?";
  let body = "";

  if (c.error) {
    body = `<p class="decode-error">${escapeHtml(c.error)}</p>`;
  } else if (tipo === "ascii") {
    body = `<p><strong>Texto:</strong> <code>${escapeHtml(c.texto)}</code></p>`;
  } else if (tipo === "csv") {
    const filas = Object.entries(c.campos || {})
      .map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(v)}</td></tr>`)
      .join("");
    body = `<table class="decode-mini-table"><tbody>${filas}</tbody></table>`;
  } else if (tipo === "thermoking_1b02") {
    const cab = c.cabecera || {};
    body = `
      <ul class="decode-list">
        <li>STX <code>${escapeHtml(cab.stx)}</code> · Versión <code>${escapeHtml(cab.version)}</code></li>
        <li>Longitud (LE): <code>${escapeHtml(cab.campo_longitud_le)}</code> · ${c.bytes_totales} bytes</li>
        ${c.prefijo_ff_ignorado ? "<li>Prefijo FF… ignorado antes de 1B02</li>" : ""}
        <li>Registros sin lectura (FE7F): <strong>${(c.registros_sin_lectura || []).length}</strong></li>
        <li>Posibles temperaturas: <strong>${(c.posibles_temperaturas || []).length}</strong></li>
      </ul>`;
    if (c.posibles_temperaturas?.length) {
      const temps = c.posibles_temperaturas
        .slice(0, 8)
        .map(
          (t) =>
            `<span class="decode-chip">@${t.offset}: ${t.posible_temperatura_c ?? "—"} °C</span>`
        )
        .join("");
      body += `<div class="decode-chips">${temps}</div>`;
    }
    if (c.texto_embebido?.length) {
      body += `<p><strong>ASCII:</strong> ${c.texto_embebido.map(escapeHtml).join(", ")}</p>`;
    }
    if (c.volcado_hex?.length) {
      body += `<details><summary>Volcado hex</summary><pre class="hex-dump">${escapeHtml(c.volcado_hex.join("\n"))}</pre></details>`;
    }
  } else if (tipo === "hex") {
    if (c.texto_embebido?.length) {
      body += `<p><strong>ASCII:</strong> ${c.texto_embebido.map(escapeHtml).join(", ")}</p>`;
    }
    if (c.volcado_hex?.length) {
      body += `<pre class="hex-dump">${escapeHtml(c.volcado_hex.join("\n"))}</pre>`;
    }
  } else {
    body = `<p>${escapeHtml(c.texto || c.descripcion || "—")}</p>`;
  }

  const preview =
    c.valor_original && c.valor_original.length > 80
      ? `${escapeHtml(c.valor_original.slice(0, 80))}…`
      : escapeHtml(c.valor_original || "");

  return `
    <article class="decode-canal">
      <header>
        <span class="decode-canal-name">${escapeHtml(c.campo)}</span>
        <span class="decode-canal-tipo">${escapeHtml(tipo)}</span>
      </header>
      ${preview ? `<p class="decode-preview">${preview}</p>` : ""}
      ${body}
    </article>`;
}

export function renderDecodedHtml(data) {
  if (!data) return "<p>Sin datos de decodificación.</p>";

  let html = "";
  if (data.resumen) {
    html += `<p class="decode-resumen">${escapeHtml(data.resumen)}</p>`;
  }
  if (data.nota) {
    html += `<p class="decode-nota">${escapeHtml(data.nota)}</p>`;
  }

  if (data.oficial?.disponible && data.oficial.ultimo) {
    html += `
      <section class="decode-section decode-oficial">
        <h4>Datos oficiales (colección OFICIAL)</h4>
        <p class="decode-meta">Colección: <code>${escapeHtml(data.oficial.coleccion)}</code></p>
        <pre class="trama-json">${escapeHtml(JSON.stringify(data.oficial.ultimo, null, 2))}</pre>
      </section>`;
  } else if (data.oficial) {
    html += `<p class="decode-meta">OFICIAL: ${escapeHtml(data.oficial.mensaje || "no disponible")}</p>`;
  }

  const canales = data.canales || [];
  if (canales.length) {
    html += `<section class="decode-section"><h4>Canales decodificados</h4>`;
    html += canales.map(renderCanal).join("");
    html += `</section>`;
  }

  return html || "<p>No hay canales para decodificar.</p>";
}
