const $ = s => document.querySelector(s);
const api = (u, o) => fetch(u, o).then(async r => {
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `Error ${r.status}`);
  return d;
});

let TID = null, TIMER = null, ESTILOS = [];

const ETAPAS = [
  ["Revisando los archivos", 0.02],
  ["Sincronizando la cámara", 0.06],
  ["Extrayendo el audio", 0.10],
  ["Detectando dónde hablás", 0.18],
  ["Transcribiendo el stream", 0.45],
  ["Eligiendo los mejores momentos", 0.55],
  ["Generando los clips", 1.00],
];

// ───────────────────────────────── arranque
async function iniciar() {
  const d = await api("/api/inicio");
  ESTILOS = d.estilos;

  $("#cuenta").textContent = d.api_key ? `cuenta ${d.api_key}` : "sin API key";

  const alertas = [];
  if (d.falta.length)
    alertas.push(`<div class="aviso error">Falta <b>${d.falta.join(", ")}</b> en la carpeta <code>tools\\</code>.</div>`);
  if (!d.api_key)
    alertas.push(`<div class="aviso">Falta la API key. Creá un archivo <code>.env</code> en la carpeta del
      proyecto con la línea <code>${d.var_key}=sk-ant-...</code> y recargá esta página.
      Usá la cuenta que quieras que pague estos análisis.</div>`);
  $("#alertas").innerHTML = alertas.join("");

  if (d.videos.length) {
    $("#recientes").innerHTML = "<span class='pista' style='width:100%'>Videos que encontré:</span>" +
      d.videos.map(v => `<span class="chip" data-ruta="${esc(v.ruta)}"><b>${esc(v.nombre)}</b> · ${v.gb} GB</span>`).join("");
    $("#recientes").querySelectorAll(".chip").forEach(c =>
      c.onclick = () => ponerPantalla(c.dataset.ruta));
  }
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ───────────────────────────────── elegir archivos
async function ponerPantalla(ruta) {
  $("#pantalla").value = ruta;
  try {
    const r = await api("/api/elegir-pareja", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ruta })
    });
    if (r.pareja) {
      $("#camara").value = r.pareja;
      $("#pista-camara").textContent = "Encontré el archivo de cámara automáticamente.";
    }
  } catch (e) { /* si no hay endpoint, no pasa nada */ }
}

async function buscarArchivo(que, boton) {
  const b = $(boton);
  const antes = b.textContent;
  b.disabled = true;
  b.textContent = "Abriendo...";
  try {
    const r = await api(`/api/elegir?que=${que}`, { method: "POST" });
    if (r.ruta) {
      $(que === "pantalla" ? "#pantalla" : "#camara").value = r.ruta;
      if (r.pareja) {
        $("#camara").value = r.pareja;
        $("#pista-camara").textContent = "Encontré el archivo de cámara automáticamente.";
      } else if (que === "camara") {
        $("#pista-camara").textContent = "";
      }
    }
  } catch (e) { alert(e.message); }
  b.disabled = false;
  b.textContent = antes;
}

$("#btn-elegir").onclick = () => buscarArchivo("pantalla", "#btn-elegir");
$("#btn-elegir-cam").onclick = () => buscarArchivo("camara", "#btn-elegir-cam");

$("#n-clips").oninput = e => $("#n-clips-val").value = e.target.value;
$("#silencios").onchange = e =>
  $("#fila-nivel").classList.toggle("oculto", !e.target.checked);

// ───────────────────────────────── generar
$("#btn-generar").onclick = async () => {
  const pantalla = $("#pantalla").value.trim();
  if (!pantalla) return alert("Elegí el video del gameplay.");
  $("#btn-generar").disabled = true;
  try {
    const r = await api("/api/trabajo", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pantalla,
        camara: $("#camara").value.trim() || null,
        n_clips: +$("#n-clips").value,
        estilo: $("#estilo").value,
        cortar_silencios: $("#silencios").checked,
        nivel_silencio: document.querySelector('input[name="nivel"]:checked').value,
        gancho: $("#gancho").checked,
        nivel_zoom: document.querySelector("input[name=zoom]:checked").value,
      })
    });
    TID = r.id;
    mostrar("progreso");
    seguir();
  } catch (e) {
    alert(e.message);
    $("#btn-generar").disabled = false;
  }
};

$("#btn-cancelar").onclick = () => TID && api(`/api/cancelar/${TID}`, { method: "POST" });
$("#btn-nuevo").onclick = () => { clearInterval(TIMER); mostrar("config"); $("#btn-generar").disabled = false; };
$("#btn-carpeta").onclick = () => api(`/api/abrir/${TID}`, { method: "POST" });

function mostrar(cual) {
  for (const p of ["config", "progreso", "clips"])
    $(`#paso-${p}`).classList.toggle("oculto", p !== cual);
}

// ───────────────────────────────── seguimiento
function seguir() {
  clearInterval(TIMER);
  TIMER = setInterval(refrescar, 900);
  refrescar();
}

async function refrescar() {
  if (!TID) return;
  let e;
  try { e = await api(`/api/estado/${TID}`); } catch { return; }

  const p = Math.round((e.progreso || 0) * 100);
  $("#barra-relleno").style.width = p + "%";
  $("#porcentaje").textContent = p + "%";
  $("#mensaje").textContent = e.mensaje || "";

  $("#etapas").innerHTML = ETAPAS.map(([nombre, hasta], i) => {
    const desde = i ? ETAPAS[i - 1][1] : 0;
    const cls = e.progreso >= hasta ? "hecho" : (e.progreso >= desde ? "actual" : "");
    return `<li class="${cls}">${nombre}</li>`;
  }).join("");

  const datos = [];
  if (e.duracion) datos.push(`<b>${(e.duracion / 60).toFixed(0)}</b> min de stream`);
  if (e.habla_pct) datos.push(`hablás el <b>${e.habla_pct}%</b>`);
  if (e.n_palabras) datos.push(`<b>${e.n_palabras.toLocaleString("es")}</b> palabras`);
  if (e.offset_camara) datos.push(`cámara corregida <b>${Math.round(e.offset_camara * 1000)} ms</b>`);
  if (e.uso_llm) {
    const costo = (e.uso_llm.costo_usd || 0) + (e.uso_gancho?.costo_usd || 0);
    datos.push(`IA: <b>$${costo.toFixed(3)}</b> en este stream`);
  }
  $("#datos-stream").innerHTML = datos.join("");

  const avisos = [e.info?.aviso, e.info?.aviso_vfr, e.sync?.nota].filter(Boolean);
  if (avisos.length)
    $("#datos-stream").innerHTML += avisos
      .map(a => `<div class="aviso" style="width:100%;margin:10px 0 0">${esc(a)}</div>`).join("");

  if (e.error) {
    $("#mensaje").innerHTML = `<span style="color:var(--rojo)">${esc(e.error)}</span>`;
    clearInterval(TIMER);
    $("#btn-generar").disabled = false;
  }

  if (e.clips?.length && (e.fase === "terminado" || e.clips.some(c => c.estado === "listo"))) {
    pintarClips(e);
    if (e.fase === "terminado" || e.fase === "cancelado") clearInterval(TIMER);
  }
  if (e.fase === "terminado") mostrar("clips");
}

// ───────────────────────────────── clips
function pintarClips(e) {
  const listos = e.clips.filter(c => c.estado === "listo").length;
  $("#titulo-clips").textContent = `${listos} ${listos === 1 ? "clip listo" : "clips listos"}`;
  $("#grilla").innerHTML = e.clips.map(c => {
    const t = new Date(c.inicio * 1000).toISOString().slice(11, 19);
    if (c.estado !== "listo")
      return `<div class="clip ${c.estado === "error" ? "fallado" : "pendiente"}">
        <div class="clip-cuerpo"><div class="clip-tit">${esc(c.titulo || "Clip")}</div>
        <div class="clip-meta">${t} · ${c.duracion}s</div>
        ${c.estado === "error" ? `<div class="clip-porque">No se pudo generar: ${esc(c.error || "")}</div>` : ""}
        </div></div>`;
    const jpg = c.archivo.replace(/\.mp4$/, ".jpg");
    return `<div class="clip">
      <video src="/api/video/${TID}/${encodeURIComponent(c.archivo)}"
             poster="/api/miniatura/${TID}/${encodeURIComponent(jpg)}" controls preload="none"></video>
      <div class="clip-cuerpo">
        <div class="clip-tit">${esc(c.titulo || "Clip")}</div>
        <div class="clip-meta">
          <span class="puntaje ${c.puntaje < 75 ? "medio" : ""}">${c.puntaje}</span>
          <span class="categoria">${esc(c.categoria || "")}</span>
          <span>${t} · ${c.duracion}s · ${c.peso_mb || "?"} MB</span>
        </div>
        <div class="clip-porque">${esc(c.por_que || "")}</div>
        ${c.gancho?.texto ? `<div class="clip-porque" style="color:var(--amarillo)">
           ⚡ arranca con: ${c.gancho.tipo === "reaccion" ? "una reacción sin palabras"
             : `"${esc(c.gancho.texto)}"`} <span style="opacity:.75">
           (${c.gancho.dur}s${c.gancho.fuerza ? " · fuerza " + c.gancho.fuerza : ""}${
             c.gancho.por_que ? " · " + esc(c.gancho.por_que) : ""})</span></div>` : ""}
        ${c.gancho?.cartel ? `<div class="clip-porque" style="color:var(--amarillo)">
           🪧 cartel: <b>${esc(c.gancho.cartel)}</b></div>` : ""}
        ${c.silencios?.cortes ? `<div class="clip-porque" style="color:var(--verde)">
           ${c.silencios.cortes} ${c.silencios.cortes === 1 ? "pausa sacada" : "pausas sacadas"}
           (${c.silencios.quitado}s, ${Math.round(c.silencios.proporcion * 100)}%)${
             c.duracion_final ? ` · queda en ${Math.round(c.duracion_final)}s` : ""}</div>` : ""}
        <div class="clip-acciones">
          <a href="/api/video/${TID}/${encodeURIComponent(c.archivo)}"
             download="${esc(c.archivo)}">Descargar</a>
          <button data-n="${c.n}" class="editar">Subtítulos</button>
        </div>
      </div></div>`;
  }).join("");
  $("#grilla").querySelectorAll(".editar").forEach(b =>
    b.onclick = () => abrirEditor(+b.dataset.n));
}

// ───────────────────────────────── editor de subtítulos
let CUES = null, CLIP_N = null;

async function abrirEditor(n) {
  CLIP_N = n;
  const c = await api(`/api/clip/${TID}/${n}`);
  CUES = c.cues || [];
  $("#modal-titulo").textContent = c.titulo || `Clip ${n}`;
  $("#modal-estado").textContent = "";
  $("#editor").innerHTML = CUES.map((cue, i) => `
    <div class="cue">
      <span class="cue-t">${(cue[0].a - c.inicio).toFixed(1)}s</span>
      ${cue.map((w, j) => `<span class="palabra ${w.p < 0.5 ? "dudosa" : ""}"
        contenteditable="true" data-i="${i}" data-j="${j}">${esc(w.t)}</span>`).join("")}
    </div>`).join("");
  $("#modal").classList.remove("oculto");
}

$("#modal-cerrar").onclick = () => $("#modal").classList.add("oculto");
$("#modal").onclick = e => { if (e.target.id === "modal") $("#modal").classList.add("oculto"); };

$("#btn-guardar").onclick = async () => {
  $("#editor").querySelectorAll(".palabra").forEach(el => {
    CUES[+el.dataset.i][+el.dataset.j].t = el.textContent.trim();
  });
  const cues = CUES.map(c => c.filter(w => w.t));
  $("#btn-guardar").disabled = true;
  $("#modal-estado").textContent = "Rehaciendo el clip, aguantá...";
  try {
    await api(`/api/clip/${TID}/${CLIP_N}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cues })
    });
    $("#modal").classList.add("oculto");
    refrescar();
  } catch (e) {
    $("#modal-estado").textContent = e.message;
  }
  $("#btn-guardar").disabled = false;
};

iniciar();
