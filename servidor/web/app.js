/* Panel de Cuidado · Localizador GPS · Grupo 7 · ARC115 · v2 (nube) */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const S = { vista: "inicio", estado: null, filtro: "todas", dias: 7, editando: null, mapa: null, capas: {}, rep: null, config: null, pub: null, enApp: false };
const TITULOS = { inicio: "Panel de Cuidado", rutinas: "Rutinas Diarias", alertas: "Historial de Alertas", reportes: "Reportes Médicos", ajustes: "Ajustes" };
const IC = {
  check: '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  bell: '<svg viewBox="0 0 24 24"><path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><path d="M12 3l10 18H2zM12 10v4M12 17.5v.5"/></svg>',
  info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/></svg>',
  wifiOff: '<svg viewBox="0 0 24 24"><path d="M2 8.5a15 15 0 0 1 5-3M22 8.5a15 15 0 0 0-9.5-3.8M5 12a10 10 0 0 1 4-2.4M19 12a10 10 0 0 0-2-1.4M8.5 15.5a5 5 0 0 1 7 0M12 19.5v.5M3 3l18 18"/></svg>',
  wifi: '<svg viewBox="0 0 24 24"><path d="M2 8.5a15 15 0 0 1 20 0M5 12a10 10 0 0 1 14 0M8.5 15.5a5 5 0 0 1 7 0M12 19.5v.5"/></svg>',
  pin: '<svg viewBox="0 0 24 24"><path d="M12 21s-7-6.3-7-11.5a7 7 0 0 1 14 0C19 14.7 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
  wait: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  casa: '<svg viewBox="0 0 24 24"><path d="M3 11l9-7 9 7M5 10v10h14V10"/></svg>',
};
const ALERTA = {
  sos: { cat: "ayuda", color: "rojo", ico: "bell", titulo: "BOTÓN DE PÁNICO ACTIVADO" },
  perimetro_salida: { cat: "perimetro", color: "ambar", ico: "warn", titulo: "Posible salida del perímetro" },
  perimetro_regreso: { cat: "perimetro", color: "verde", ico: "casa", titulo: "Regresó al perímetro" },
  desconexion: { cat: "comunicacion", color: "azul", ico: "wifiOff", titulo: "Pérdida de comunicación" },
  reconexion: { cat: "comunicacion", color: "verde", ico: "wifi", titulo: "Dispositivo conectado de nuevo" },
  recordatorio_omitido: { cat: "recordatorios", color: "gris", ico: "info", titulo: "Recordatorio no confirmado" },
  recordatorio_confirmado: { cat: "recordatorios", color: "verde", ico: "check", titulo: "Rutina confirmada" },
};
const INFORMATIVAS = ["perimetro_regreso", "reconexion", "recordatorio_confirmado"];
const TIPO_RUTINA = { medicamento: "Medicamento", aseo: "Aseo personal", caminata: "Caminata", comida: "Comida", otro: "Otro" };
const ESTADO_EV = { confirmado: "Completado", sonando: "Sonando", programado: "Pendiente", omitido: "No confirmado", sin_dato: "Sin registro" };
const DIAS = ["L", "M", "X", "J", "V", "S", "D"];
const CATS = { ayuda: "Solicitud de ayuda", perimetro: "Perímetro", comunicacion: "Pérdida de comunicación", recordatorios: "Rutinas y recordatorios" };

/* ---------------- utilidades ---------------- */
async function api(ruta, opts = {}) {
  const r = await fetch(ruta, {
    method: opts.method || "GET", credentials: "same-origin",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const datos = await r.json().catch(() => ({}));
  if (r.status === 401 && !opts.sinRedirigir) { mostrarEntrada(); throw new Error("Inicia sesión"); }
  if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos;
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 3400);
}
const aFecha = (iso) => new Date(iso.length <= 10 ? iso + "T00:00:00" : iso);
const hora = (iso) => aFecha(iso).toLocaleTimeString("es-SV", { hour: "numeric", minute: "2-digit" });
function diaRel(iso) {
  const d = aFecha(iso), hoy = new Date(S.estado ? S.estado.ahora : Date.now());
  const diff = Math.round((new Date(hoy.toDateString()) - new Date(d.toDateString())) / 864e5);
  if (diff === 0) return "Hoy";
  if (diff === 1) return "Ayer";
  return d.toLocaleDateString("es-SV", { weekday: "short", day: "numeric", month: "short" });
}
function hace(seg) {
  if (seg == null) return "nunca";
  if (seg < 60) return `${seg} s`;
  if (seg < 3600) return `${Math.floor(seg / 60)} min`;
  if (seg < 86400) return `${Math.floor(seg / 3600)} h ${Math.floor((seg % 3600) / 60)} min`;
  return `${Math.floor(seg / 86400)} días`;
}
const hhmm12 = (h) => { const [a, b] = h.split(":").map(Number); return new Date(2000, 0, 1, a, b).toLocaleTimeString("es-SV", { hour: "numeric", minute: "2-digit" }); };
const nombreRutina = (r) => { const t = TIPO_RUTINA[r.tipo] || r.tipo; return (r.titulo.toLowerCase() === t.toLowerCase() ? t : `${t}: ${r.titulo}`) + (r.detalle ? ` (${r.detalle})` : ""); };
const enlaceMaps = (lat, lng) => `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;
const enlaceRuta = (lat, lng) => `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`;

/* ================= PANTALLA DE ENTRADA ================= */
function pintarPill(p) {
  const pill = $("#pillEstado");
  if (!p.visto) { pill.className = "pill-estado"; $("#pillTitulo").textContent = "El dispositivo aún no se ha conectado"; $("#pillSub").textContent = "Enciende el prototipo y conéctalo a internet."; }
  else if (p.conectado) { pill.className = "pill-estado ok"; $("#pillTitulo").textContent = "Dispositivo conectado"; $("#pillSub").textContent = `Última señal hace ${hace(p.segundos_desde)}`; }
  else { pill.className = "pill-estado mal"; $("#pillTitulo").textContent = "Dispositivo desconectado"; $("#pillSub").textContent = `Sin señal desde hace ${hace(p.segundos_desde)}. Verifica a la persona.`; }
}
async function cargarPublico() {
  try {
    S.pub = await api("/api/publico", { sinRedirigir: true });
    pintarPill(S.pub);
    $("#entradaError").hidden = true;
    return S.pub;
  } catch (e) {
    $("#pillEstado").className = "pill-estado mal";
    $("#pillTitulo").textContent = "No se pudo contactar al servidor";
    $("#pillSub").textContent = "Revisa tu conexión a internet. El servidor gratuito puede tardar un minuto en despertar.";
    return null;
  }
}
async function mostrarEntrada() {
  S.enApp = false;
  $("#app").hidden = true; $("#asistente").hidden = true; $("#entrada").hidden = false;
  const p = await cargarPublico();
  if (!p) { setTimeout(mostrarEntrada, 5000); return; }
  $("#formInicial").hidden = p.configurado;
  $("#formLogin").hidden = !p.configurado || p.sesion;
  $("#btnEntrar").hidden = !p.sesion;
}
$("#btnEntrar").addEventListener("click", () => entrarApp());
$("#formLogin").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try { await api("/api/login", { method: "POST", body: { clave: $("#lgClave").value }, sinRedirigir: true }); $("#lgClave").value = ""; entrarApp(); }
  catch (e) { const er = $("#entradaError"); er.textContent = e.message; er.hidden = false; }
});
$("#formInicial").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const er = $("#entradaError");
  if ($("#inClave").value !== $("#inClave2").value) { er.textContent = "Las claves no coinciden."; er.hidden = false; return; }
  try {
    await api("/api/configurar-inicial", { method: "POST", sinRedirigir: true, body: { clave_dispositivo: $("#inDisp").value.trim(), paciente: $("#inPaciente").value.trim(), clave_app: $("#inClave").value } });
    abrirAsistente();
  } catch (e) { er.textContent = e.message; er.hidden = false; }
});
setInterval(() => { if (!$("#entrada").hidden) cargarPublico(); }, 5000);

/* ================= ASISTENTE ================= */
let pasoActual = 1;
function abrirAsistente() {
  $("#entrada").hidden = true; $("#app").hidden = true; $("#asistente").hidden = false;
  irPaso(1);
  api("/api/perimetro/calibrar", { method: "POST" }).catch(() => {});
  cargarEstado();
}
function irPaso(n) {
  pasoActual = n;
  $$("#asistente .paso").forEach((p) => (p.hidden = Number(p.dataset.paso) !== n));
  $$("#pasos i").forEach((i, k) => i.classList.toggle("on", k < n));
  pintarModulos();
}
$("#asistente").addEventListener("click", (ev) => {
  if (ev.target.closest("[data-sig]")) irPaso(pasoActual + 1);
  if (ev.target.closest("[data-ant]")) irPaso(pasoActual - 1);
});
$("#btnTerminar").addEventListener("click", () => { try { localStorage.setItem("asistente", "hecho"); } catch (e) { /* */ } entrarApp(); });

async function entrarApp() {
  try { S.estado = await api("/api/estado"); } catch (e) { return; }
  $("#entrada").hidden = true; $("#asistente").hidden = true; $("#app").hidden = false;
  S.enApp = true;
  let inicial = "inicio";
  try { inicial = localStorage.getItem("vista") || "inicio"; } catch (e) { /* */ }
  ir(TITULOS[inicial] ? inicial : "inicio");
  pintarInicio();
  registrarSW();
}

/* ================= NAVEGACIÓN ================= */
function ir(vista) {
  S.vista = vista;
  $$(".vista").forEach((v) => (v.hidden = v.id !== "v-" + vista));
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.v === vista));
  $("#titulo").textContent = TITULOS[vista];
  window.scrollTo(0, 0);
  try { localStorage.setItem("vista", vista); } catch (e) { /* */ }
  if (vista === "inicio" && S.mapa) setTimeout(() => { S.mapa.invalidateSize(); pintarMapa(); }, 60);
  if (vista === "ajustes") api("/api/perimetro/calibrar", { method: "POST" }).catch(() => {});
  cargarVista();
}
$$("#tabs button").forEach((b) => b.addEventListener("click", () => ir(b.dataset.v)));
$("#btnAjustes").addEventListener("click", () => ir("ajustes"));
function cargarVista() {
  const f = { rutinas: cargarRutinas, alertas: cargarAlertas, reportes: cargarReportes, ajustes: cargarAjustes }[S.vista];
  if (f) f().catch((e) => toast(e.message));
}

/* ================= ESTADO / INICIO ================= */
async function cargarEstado() {
  try {
    S.estado = await api("/api/estado");
    $("#conn").hidden = true;
    if (S.enApp) pintarInicio();
    pintarModulos(false);
  } catch (e) {
    if (e.message === "Inicia sesión") return;
    const c = $("#conn"); c.hidden = false;
    c.textContent = "Sin conexión con el servidor. Reintentando…";
  }
}

function textoPerimetro(e) {
  const w = e.wifi;
  if (w.umbral == null) return "Perímetro Wi-Fi sin calibrar";
  let calidad = "Excelente";
  if (w.rssi != null) {
    if (w.rssi < -85) calidad = "Débil";
    else if (w.rssi < -70) calidad = "Regular";
  }
  const limiteTexto = e.modo_limite || "Configurado";
  return `Señal Wi-Fi: ${calidad} · límite: ${limiteTexto}`;
}

function pintarInicio() {
  const e = S.estado, d = e.dispositivo;
  $("#badgeDemo").hidden = !e.demo;
  $("#puntoAlertas").hidden = !e.alertas_pendientes.length;
  let clase = "", ico = IC.check, tit, sub, meta = [];
  if (e.sos) { clase = "alerta"; ico = IC.bell; tit = "Ayuda solicitada"; sub = `Botón de pánico · ${hora(e.sos.ts)}`; }
  else if (!d.visto) { clase = "neutro"; ico = IC.wait; tit = "Esperando al dispositivo"; sub = "Enciende el prototipo y conéctalo al Wi-Fi."; }
  else if (!d.conectado) { clase = "neutro"; ico = IC.wifiOff; tit = "Sin comunicación"; sub = "Verifica a la persona"; meta.push(`Última señal hace ${hace(d.segundos_desde)}.`); }
  else if (e.perimetro === "fuera") { clase = "aviso"; ico = IC.warn; tit = "Fuera del perímetro"; sub = "La señal Wi-Fi está bajo el límite"; meta.push(textoPerimetro(e) + (e.silenciado ? " · alarma silenciada" : "")); }
  else if (e.wifi.umbral == null) { clase = "neutro"; ico = IC.wifi; tit = "Perímetro sin calibrar"; sub = "Calíbralo con la señal del Wi-Fi de la casa"; }
  else { tit = "Paciente seguro"; sub = "Dentro del alcance del Wi-Fi"; meta.push(textoPerimetro(e)); }
  if (d.visto && d.conectado) {
    const m = [`Señal hace ${hace(d.segundos_desde)}`];
    if (d.ssid) m.push(`Wi-Fi ${d.ssid}`);
    m.push(d.fix ? `GPS ${d.sats} satélites` : "GPS sin señal");
    if (d.simulado) m.push("simulado");
    meta.push(m.join(" · "));
  }
  $("#estadoCard").className = "estado " + clase;
  $("#estadoIcono").innerHTML = ico;
  $("#estadoTitulo").textContent = tit;
  $("#estadoSub").textContent = sub;
  $("#estadoMeta").innerHTML = meta.map(esc).join("<br>");
  const b = $("#btnAtenderSOS"); b.hidden = !e.sos; b.onclick = () => atender(e.sos.id);
  $("#btnIrCalibrar").hidden = !(e.wifi.umbral == null && !e.sos);
  $("#btnIrCalibrar").onclick = () => ir("ajustes");

  // Ubicación: GPS del dispositivo y Wi-Fi (casa)
  const p = e.posicion, c = e.casa;
  if (p) {
    const viejo = d.fix ? "" : " · última conocida";
    $("#txtGps").innerHTML = `<b>GPS</b> ${p.lat.toFixed(6)}, ${p.lng.toFixed(6)}<br><span class="muted">${esc(diaRel(p.ts))} ${esc(hora(p.ts))}${viejo}${p.sim ? " · simulada" : ""}</span>`;
  } else $("#txtGps").innerHTML = "<b>GPS</b> sin posición todavía";
  $("#txtWifi").innerHTML = `<b>Wi-Fi</b> ${esc(d.ssid || "sin datos")}<br><span class="muted">${c ? `Casa en ${c.lat.toFixed(5)}, ${c.lng.toFixed(5)}` : "Ubicación de la casa sin definir"}</span>`;
  const objetivo = p || c;
  const url = objetivo ? enlaceMaps(objetivo.lat, objetivo.lng) : "https://www.google.com/maps";
  $("#lnkMaps").href = url; $("#mapaLink").href = url;
  $("#lnkRuta").href = objetivo ? enlaceRuta(objetivo.lat, objetivo.lng) : "https://www.google.com/maps";
  pintarMapa();

  const prox = e.proximas.slice(0, 4);
  $("#proximas").innerHTML = prox.length ? prox.map((r) => {
    const s = r.evento.estado;
    return `<div class="item ${s === "sonando" ? "verde" : ""}"><div><div class="t">${esc(nombreRutina(r))}</div>
      <div class="s">${esc(hhmm12(r.hora))}${s === "sonando" ? " · esperando confirmación con el botón" : ""}</div></div>
      <span class="estado-chip ch-${s}">${ESTADO_EV[s]}</span></div>`;
  }).join("") : `<div class="vacio">No quedan rutinas pendientes hoy.</div>`;
  $("#pendientes").innerHTML = e.alertas_pendientes.length ? e.alertas_pendientes.slice(0, 3).map(tarjetaAlerta).join("") : `<div class="vacio">Todo en orden. No hay alertas sin atender.</div>`;
}

/* Mapa fijo: no se puede mover ni hacer zoom; tocarlo abre Google Maps */
/* Mapa fijo centrado con botones de zoom */
function pintarMapa() {
  const e = S.estado, cont = $("#mapa");
  const p = e.posicion, c = e.casa;
  if (!window.L) { cont.textContent = p || c ? "Mapa no disponible. Toca para abrir Google Maps." : "El mapa aparecerá con la primera posición GPS o al definir la casa."; return; }
  if (!p && !c) { cont.textContent = "El mapa aparecerá con la primera posición GPS o al definir la casa."; return; }
  
  if (!S.mapa) {
    cont.textContent = "";
    // Se habilita zoomControl: true pero se mantienen bloqueados el arrastre (dragging) y zooms táctiles para mantener el centrado estricto
    S.mapa = L.map(cont, { 
      dragging: false, 
      touchZoom: false, 
      scrollWheelZoom: false, 
      doubleClickZoom: false, 
      boxZoom: false,
      keyboard: false, 
      zoomControl: true, 
      tap: false, 
      attributionControl: true, 
      zoomSnap: 0.5 
    });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(S.mapa);
  }

  const color = e.sos ? "#C8323C" : e.perimetro === "fuera" ? "#D99A0B" : "#1E7A4C";
  if (p) {
    if (!S.capas.gps) S.capas.gps = L.circleMarker([p.lat, p.lng], { radius: 9, weight: 3, color: "#fff", fillOpacity: 1, interactive: false }).addTo(S.mapa);
    S.capas.gps.setLatLng([p.lat, p.lng]).setStyle({ fillColor: color });
  }
  if (c) {
    if (!S.capas.casa) S.capas.casa = L.marker([c.lat, c.lng], { interactive: false, icon: L.divIcon({ className: "", html: `<div class="pin-casa">${IC.casa}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] }) }).addTo(S.mapa);
    S.capas.casa.setLatLng([c.lat, c.lng]);
  }

  const puntos = [p, c].filter(Boolean).map((x) => [x.lat, x.lng]);
  const clave = puntos.map((x) => x.map((v) => v.toFixed(5)).join()).join("|");

  // Re-centra automáticamente si cambia la ubicación
  if (clave !== S.capas.vista) {
    S.capas.vista = clave;
    if (puntos.length === 2 && S.mapa.distance(puntos[0], puntos[1]) > 25) {
      S.mapa.fitBounds(puntos, { padding: [36, 36], maxZoom: 18 });
    } else {
      S.mapa.setView(puntos[0], 18);
    }
  }
}

$("#btnBuscar").addEventListener("click", async () => { await api("/api/dispositivo/buscar", { method: "POST" }); toast("El dispositivo sonará en su próxima conexión."); });

/* ================= MÓDULOS COMPARTIDOS (Wi-Fi, casa, notificaciones) ================= */
function pintarModulos(conNotif = true) {
  if (conNotif) $$("[data-notif]").forEach(pintarNotif);
  if (!S.estado) return;
  $$("[data-wifi]").forEach(pintarWifi);
  $$("[data-casa]").forEach(pintarCasa);
}

const RMIN = -95, RMAX = -35;
const pos = (v) => `${Math.max(0, Math.min(100, ((v - RMIN) / (RMAX - RMIN)) * 100))}%`;
function pintarWifi(box) {
  const e = S.estado, w = e.wifi, d = e.dispositivo, mini = box.dataset.wifi === "mini";
  const actual = w.rssi != null && d.conectado;
  
  let calidad = "Sin datos";
  if (actual) {
    if (w.rssi >= -65) calidad = "Excelente";
    else if (w.rssi >= -75) calidad = "Buena";
    else if (w.rssi >= -85) calidad = "Regular";
    else calidad = "Débil";
  }

  let html = `<div class="wifi-num"><span>${esc(d.ssid || "Wi-Fi")}${actual ? "" : " · sin datos recientes"}</span><b>${actual ? calidad : "–"}</b></div>
    <div class="medidor">${w.umbral != null ? `<span class="limite" style="left:${pos(w.umbral)}" title="Límite"></span>` : ""}${actual ? `<span class="valor" style="left:${pos(w.rssi)}"></span>` : ""}</div>
    <div class="medidor-esc"><span>débil</span><span>${w.umbral != null ? "límite" : "sin límite"}</span><span>fuerte</span></div>`;
  if (!mini) {
    const cfgActual = S.config ? S.config.wifi_umbral : w.umbral;
    const presets = S.config ? S.config.presets : { casa: -67, patio: -75, calle: -82 };
    html += `${!d.conectado ? `<div class="aviso-mini">El dispositivo no está conectado. Enciéndelo para medir la señal.</div>` : w.calibrando ? `<div class="muted small">Midiendo cada 3 s durante la calibración.</div>` : ""}
      <button class="btn" data-fijar ${actual ? "" : "disabled"}>Fijar límite aquí</button>
      <div class="muted small">O elige un alcance aproximado:</div>
      <div class="presets">
        <button class="btn btn-sec ${cfgActual === presets.casa ? "on" : ""}" data-preset="casa">Solo la casa</button>
        <button class="btn btn-sec ${cfgActual === presets.patio ? "on" : ""}" data-preset="patio">Casa y patio</button>
        <button class="btn btn-sec ${cfgActual === presets.calle ? "on" : ""}" data-preset="calle">Hasta la acera</button>
      </div>`;
  } else if (w.umbral == null) {
    html += `<div class="aviso-mini">Calibra el perímetro en Ajustes para activar las alertas.</div>`;
  }
  box.innerHTML = html;
}
document.addEventListener("click", async (ev) => {
  const f = ev.target.closest("[data-fijar]"), p = ev.target.closest("[data-preset]");
  if (!f && !p) return;
  try {
    const r = await api("/api/perimetro", { method: "POST", body: f ? { modo: "actual" } : { modo: p.dataset.preset } });
    if (S.config) S.config.wifi_umbral = r.umbral;
    toast(`Límite del perímetro actualizado.`);
    await cargarEstado();
  } catch (e) { toast(e.message); }
});

function pintarCasa(box) {
  const c = S.estado.casa, p = S.estado.posicion;
  box.innerHTML = `<div class="small">${c ? `Definida en <b>${c.lat.toFixed(6)}, ${c.lng.toFixed(6)}</b> · <a href="${enlaceMaps(c.lat, c.lng)}" target="_blank" rel="noopener">ver en Maps</a>` : "Todavía no está definida."}</div>
    <div class="fila-btns"><button class="btn btn-sec" data-casa-yo>Usar mi ubicación (estoy en la casa)</button>
    <button class="btn btn-sec" data-casa-gps ${p ? "" : "disabled"}>Usar el GPS del dispositivo</button></div>`;
}
document.addEventListener("click", async (ev) => {
  if (ev.target.closest("[data-casa-gps]")) {
    try { await api("/api/casa", { method: "POST", body: { usar_gps: true } }); toast("Ubicación de la casa guardada."); cargarEstado(); } catch (e) { toast(e.message); }
  }
  if (ev.target.closest("[data-casa-yo]")) {
    if (!navigator.geolocation) { toast("Este navegador no permite obtener la ubicación."); return; }
    toast("Pidiendo permiso de ubicación…");
    navigator.geolocation.getCurrentPosition(async (g) => {
      try { await api("/api/casa", { method: "POST", body: { lat: g.coords.latitude, lng: g.coords.longitude } }); toast(`Casa guardada (precisión ${Math.round(g.coords.accuracy)} m).`); cargarEstado(); } catch (e) { toast(e.message); }
    }, (err) => toast(err.code === 1 ? "Permiso de ubicación denegado." : "No se pudo obtener la ubicación."), { enableHighAccuracy: true, timeout: 15000 });
  }
});

/* ---------------- notificaciones push ---------------- */
let swReg = null, miSub = null;
const pushSoportado = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const esIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent);
const esInstalada = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;

async function registrarSW() {
  if (!("serviceWorker" in navigator)) return null;
  try {
    swReg = swReg || await navigator.serviceWorker.register("/sw.js");
    miSub = await swReg.pushManager.getSubscription();
  } catch (e) { /* sin service worker (http sin localhost) */ }
  pintarModulos();
  return swReg;
}
function preferenciasNotif() {
  try { return JSON.parse(localStorage.getItem("notif") || "null") || { etiqueta: "Familiar", categorias: Object.keys(CATS) }; }
  catch (e) { return { etiqueta: "Familiar", categorias: Object.keys(CATS) }; }
}
function pintarNotif(box) {
  const pref = preferenciasNotif();
  let estado, clase = "";
  if (!pushSoportado()) {
    estado = esIOS() && !esInstalada() ? "En iPhone: toca Compartir → «Agregar a inicio», abre la app desde ahí y vuelve aquí." : "Este navegador no permite notificaciones push.";
    clase = "mal";
  } else if (Notification.permission === "denied") { estado = "Bloqueadas. Actívalas en la configuración del navegador para este sitio."; clase = "mal"; }
  else if (miSub) { estado = "Activadas en este dispositivo"; clase = "ok"; }
  else estado = "Desactivadas en este dispositivo";
  box.innerHTML = `<div class="notif-estado ${clase}">${esc(estado)}</div>
    <div class="dos"><label>¿Quién recibe aquí?<select data-n-etiqueta>${["Familiar", "Doctor", "Cuidador", "Otro"].map((x) => `<option ${x === pref.etiqueta ? "selected" : ""}>${x}</option>`).join("")}</select></label><span></span></div>
    <fieldset class="checks"><legend>Avisos que acepta recibir</legend>${Object.entries(CATS).map(([k, v]) => `<label><input type="checkbox" value="${k}" ${pref.categorias.includes(k) ? "checked" : ""} data-n-cat> ${v}</label>`).join("")}</fieldset>
    <div class="fila-btns">${miSub ? `<button class="btn" data-n-activar>Guardar preferencias</button><button class="btn btn-sec" data-n-probar>Enviar prueba</button><button class="btn btn-sec" data-n-quitar>Desactivar</button>`
      : `<button class="btn" data-n-activar ${pushSoportado() && Notification.permission !== "denied" ? "" : "disabled"}>Permitir notificaciones</button>`}</div>`;
}
document.addEventListener("click", async (ev) => {
  const box = ev.target.closest("[data-notif]");
  if (!box) return;
  if (ev.target.closest("[data-n-activar]")) {
    const pref = { etiqueta: $("[data-n-etiqueta]", box).value, categorias: $$("[data-n-cat]", box).filter((i) => i.checked).map((i) => i.value) };
    try { localStorage.setItem("notif", JSON.stringify(pref)); } catch (e) { /* */ }
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") { toast("No se dio permiso para notificaciones."); pintarModulos(); return; }
      const reg = await registrarSW();
      if (!reg) { toast("Las notificaciones necesitan HTTPS (la app en Render)."); return; }
      const { clave } = await api("/api/push/clave");
      miSub = (await reg.pushManager.getSubscription()) || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64aBytes(clave) });
      await api("/api/push/suscribir", { method: "POST", body: { suscripcion: miSub.toJSON(), etiqueta: pref.etiqueta, categorias: pref.categorias } });
      toast("Notificaciones activadas en este dispositivo.");
    } catch (e) { toast("No se pudieron activar: " + e.message); }
    pintarModulos(); if (S.vista === "ajustes") cargarSubs();
  }
  if (ev.target.closest("[data-n-probar]")) {
    try { await api("/api/push/prueba", { method: "POST" }); toast("Prueba enviada. Debe llegar en unos segundos."); } catch (e) { toast(e.message); }
  }
  if (ev.target.closest("[data-n-quitar]")) {
    if (miSub) { await api("/api/push/quitar", { method: "POST", body: { endpoint: miSub.endpoint } }).catch(() => {}); await miSub.unsubscribe().catch(() => {}); miSub = null; }
    toast("Notificaciones desactivadas aquí."); pintarModulos(); if (S.vista === "ajustes") cargarSubs();
  }
});
function b64aBytes(b64) {
  const s = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}

/* ================= ALERTAS ================= */
function tarjetaAlerta(a) {
  const m = ALERTA[a.tipo] || { color: "gris", ico: "info", titulo: a.tipo };
  const accion = a.atendida ? "" : `<button class="btn btn-mini ${a.tipo === "sos" ? "btn-danger" : ""}" data-atender="${a.id}">Atender</button>`;
  const mapa = a.lat != null ? ` · <a href="${enlaceMaps(a.lat, a.lng)}" target="_blank" rel="noopener">ver ubicación</a>` : "";
  return `<div class="item con-icono ${m.color}"><div class="ico">${IC[m.ico]}</div>
    <div><div class="t">${esc(m.titulo)}</div><div class="s">${esc(diaRel(a.ts))}, ${esc(hora(a.ts))}${mapa}${a.atendida && !INFORMATIVAS.includes(a.tipo) ? " · atendida" : ""}</div>
    <div class="s">${esc(a.mensaje)}</div></div><div>${accion}</div></div>`;
}
document.addEventListener("click", (ev) => { const b = ev.target.closest("[data-atender]"); if (b) atender(b.dataset.atender); });
async function atender(id) {
  await api(`/api/alertas/${id}/atender`, { method: "POST" });
  toast("Alerta marcada como atendida.");
  await cargarEstado();
  if (S.vista === "alertas") cargarAlertas();
}
async function cargarAlertas() {
  const { alertas } = await api("/api/alertas?limite=200");
  const lista = alertas.filter((a) => S.filtro === "todas" || (ALERTA[a.tipo] || {}).cat === S.filtro);
  $("#listaAlertas").innerHTML = lista.length ? lista.map(tarjetaAlerta).join("") : `<div class="vacio">No hay alertas en esta categoría.</div>`;
}
$$("#filtros .chip").forEach((c) => c.addEventListener("click", () => { S.filtro = c.dataset.f; $$("#filtros .chip").forEach((x) => x.classList.toggle("on", x === c)); cargarAlertas(); }));

/* ================= RUTINAS ================= */
async function cargarRutinas() {
  const { rutinas } = await api("/api/rutinas");
  const fh = new Date().toLocaleDateString("es-SV", { weekday: "long", day: "numeric", month: "long" });
  $("#fechaHoy").textContent = fh.charAt(0).toUpperCase() + fh.slice(1);
  const hoy = rutinas.filter((r) => r.evento);
  $("#resumenHoy").textContent = hoy.length ? `${hoy.filter((r) => r.evento.estado === "confirmado").length} de ${hoy.length} completadas hoy` : "Sin rutinas para hoy";
  $("#listaRutinas").innerHTML = rutinas.length ? rutinas.map((r) => {
    const s = r.evento ? r.evento.estado : null;
    const color = s === "confirmado" || s === "sonando" ? "verde" : s === "omitido" ? "rojo" : "";
    const dias = r.dias === "1234567" ? "Todos los días" : [...r.dias].map((n) => DIAS[n - 1]).join(" ");
    const conf = r.evento && ["sonando", "omitido", "programado"].includes(s) ? `<button class="btn btn-mini" data-confirmar="${r.evento.id}">Marcar como hecha</button>` : "";
    const quien = s === "confirmado" && r.evento.confirmado_ts ? ` · ${hora(r.evento.confirmado_ts)} (${esc(r.evento.confirmado_por)})` : "";
    return `<div class="item ${color}"><div><div class="t">${esc(nombreRutina(r))} · ${esc(hhmm12(r.hora))}</div><div class="s">${esc(dias)}${quien}</div></div>
      ${s ? `<span class="estado-chip ch-${s}">${ESTADO_EV[s]}</span>` : `<span class="estado-chip ch-sin_dato">Hoy no</span>`}
      <div class="acciones">${conf}<button class="btn btn-mini btn-sec" data-editar="${r.id}">Editar</button><button class="btn btn-mini btn-sec" data-borrar="${r.id}">Eliminar</button></div></div>`;
  }).join("") : `<div class="vacio">Todavía no hay rutinas. Agrega medicamentos, aseo, caminatas o comidas con “+ Nueva”.</div>`;
  S.rutinas = rutinas;
}
$("#listaRutinas").addEventListener("click", async (ev) => {
  const c = ev.target.closest("[data-confirmar]"), e = ev.target.closest("[data-editar]"), b = ev.target.closest("[data-borrar]");
  if (c) { await api(`/api/eventos/${c.dataset.confirmar}/confirmar`, { method: "POST" }); toast("Rutina marcada como hecha."); cargarRutinas(); cargarEstado(); }
  if (e) abrirRutina(S.rutinas.find((r) => r.id === e.dataset.editar));
  if (b && window.confirm("¿Eliminar esta rutina? Su historial se conserva en los reportes.")) { await api(`/api/rutinas/${b.dataset.borrar}`, { method: "DELETE" }); toast("Rutina eliminada."); cargarRutinas(); }
});
$("#rtDias").insertAdjacentHTML("beforeend", ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"].map((d, i) => `<label><input type="checkbox" value="${i + 1}" checked>${d}</label>`).join(""));
function abrirRutina(r) {
  S.editando = r ? r.id : null;
  $("#dlgTitulo").textContent = r ? "Editar rutina" : "Nueva rutina";
  $("#rtTipo").value = r ? r.tipo : "medicamento";
  $("#rtTitulo").value = r ? r.titulo : "";
  $("#rtDetalle").value = r ? r.detalle || "" : "";
  $("#rtHora").value = r ? r.hora : "";
  $$("#rtDias input").forEach((i) => (i.checked = r ? r.dias.includes(i.value) : true));
  $("#dlgRutina").showModal();
}
$("#btnNuevaRutina").addEventListener("click", () => abrirRutina(null));
$("#formRutina").addEventListener("submit", async (ev) => {
  if (ev.submitter && ev.submitter.value === "cancel") return;
  ev.preventDefault();
  const dias = $$("#rtDias input").filter((i) => i.checked).map((i) => i.value).join("");
  if (!dias) { toast("Elige al menos un día."); return; }
  const datos = { tipo: $("#rtTipo").value, titulo: $("#rtTitulo").value.trim(), detalle: $("#rtDetalle").value.trim(), hora: $("#rtHora").value, dias };
  try {
    if (S.editando) await api(`/api/rutinas/${S.editando}`, { method: "PUT", body: datos }); else await api("/api/rutinas", { method: "POST", body: datos });
    $("#dlgRutina").close(); toast("Rutina guardada."); cargarRutinas(); cargarEstado();
  } catch (e) { toast(e.message); }
});

/* ================= REPORTES ================= */
async function cargarReportes() {
  S.rep = await api(`/api/reportes?dias=${S.dias}`);
  const r = S.rep;
  $("#grafBarras").innerHTML = graficoBarras(r.dias);
  $("#grafLineas").innerHTML = graficoLineas(r.dias);
  const tot = r.dias.reduce((a, d) => ({ p: a.p + d.programados, c: a.c + d.confirmados }), { p: 0, c: 0 });
  const filas = r.por_tipo.map((t) => { const pct = Math.round((100 * t.confirmados) / t.total); return `<div><div class="fila"><span>${esc(t.nombre)}</span><b>${t.confirmados}/${t.total}</b></div><div class="barra"><span style="width:${pct}%"></span></div></div>`; });
  $("#totales").innerHTML = (filas.length ? filas.join("") : `<div class="vacio">Aún no hay recordatorios cumplidos u omitidos en este periodo.</div>`) +
    `<div class="fila" style="margin-top:6px"><span>Cumplimiento total</span><b>${tot.p ? Math.round((100 * tot.c) / tot.p) + " %" : "–"}</b></div><div class="fila"><span>Alertas en el periodo</span><b>${r.alertas.length}</b></div>`;
}
$$("#segPeriodo button").forEach((b) => b.addEventListener("click", () => { S.dias = Number(b.dataset.d); $$("#segPeriodo button").forEach((x) => x.classList.toggle("on", x === b)); cargarReportes(); }));
function etiquetaDia(f, i, n) { const d = aFecha(f); return n <= 7 ? d.toLocaleDateString("es-SV", { weekday: "short" }).replace(".", "") : i % 5 === 0 || i === n - 1 ? String(d.getDate()) : ""; }
function graficoBarras(dias) {
  const W = 340, H = 180, ml = 30, mb = 22, mt = 16, n = dias.length, aw = W - ml - 6, ah = H - mb - mt, paso = aw / n, bw = Math.min(26, paso * 0.62);
  const y = (v) => mt + ah - (v / 100) * ah;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumplimiento por día">`;
  for (const v of [0, 25, 50, 75, 100]) s += `<line x1="${ml}" x2="${W - 6}" y1="${y(v)}" y2="${y(v)}" stroke="#E3E8E5"/><text x="${ml - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  dias.forEach((d, i) => {
    const cx = ml + paso * i + paso / 2;
    if (d.programados) {
      const pct = Math.round((100 * d.confirmados) / d.programados);
      s += `<rect x="${cx - bw / 2}" y="${y(pct)}" width="${bw}" height="${y(0) - y(pct)}" rx="2" fill="#1E7A4C"><title>${d.fecha}: ${d.confirmados}/${d.programados}</title></rect>`;
      if (n <= 14) s += `<text x="${cx}" y="${y(pct) - 4}" text-anchor="middle" style="fill:#1E7A4C;font-weight:600">${pct}</text>`;
    } else s += `<text x="${cx}" y="${y(0) - 4}" text-anchor="middle">–</text>`;
    s += `<text x="${cx}" y="${H - 6}" text-anchor="middle">${etiquetaDia(d.fecha, i, n)}</text>`;
  });
  return s + "</svg>";
}
function graficoLineas(dias) {
  const W = 340, H = 170, ml = 26, mb = 22, mt = 10, mr = 16, n = dias.length;
  const series = [["ayuda", "#C8323C"], ["perimetro", "#D99A0B"], ["recordatorios", "#7C8790"], ["comunicacion", "#3D6FCF"]];
  const max = Math.max(2, ...dias.flatMap((d) => series.map(([k]) => d[k]))), aw = W - ml - mr, ah = H - mb - mt;
  const x = (i) => ml + (n === 1 ? aw / 2 : (aw * i) / (n - 1)), y = (v) => mt + ah - (v / max) * ah;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Alertas por día">`;
  for (const v of [...new Set([0, Math.round(max / 2), max])]) s += `<line x1="${ml}" x2="${W - mr}" y1="${y(v)}" y2="${y(v)}" stroke="#E3E8E5"/><text x="${ml - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  for (const [k, c] of series) {
    s += `<polyline fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round" points="${dias.map((d, i) => `${x(i)},${y(d[k])}`).join(" ")}"/>`;
    if (n <= 14) dias.forEach((d, i) => (s += `<circle cx="${x(i)}" cy="${y(d[k])}" r="3" fill="${c}"><title>${d.fecha}: ${d[k]}</title></circle>`));
  }
  dias.forEach((d, i) => (s += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${etiquetaDia(d.fecha, i, n)}</text>`));
  return s + "</svg>";
}
$("#btnPDF").addEventListener("click", async () => {
  if (!S.rep) await cargarReportes();
  const r = S.rep, e = S.estado || {};
  const nombres = { sos: "Botón de pánico", perimetro_salida: "Salida del perímetro (Wi-Fi)", desconexion: "Pérdida de comunicación", recordatorio_omitido: "Recordatorio no confirmado" };
  const fmt = (f) => aFecha(f).toLocaleDateString("es-SV", { day: "2-digit", month: "2-digit", year: "numeric" });
  const tot = r.dias.reduce((a, d) => ({ p: a.p + d.programados, c: a.c + d.confirmados }), { p: 0, c: 0 });
  $("#informe").innerHTML = `<div class="enc"><div><h1>Informe de cuidado · ${esc(r.paciente)}</h1><div>Periodo: ${fmt(r.desde)} al ${fmt(r.hasta)}</div></div><div style="text-align:right">Localizador GPS · Grupo 7<br>ARC115 · UES</div></div>
    ${e.demo ? "<p><b>Atención:</b> este informe incluye datos de demostración.</p>" : ""}
    <h2>Resumen</h2><table><tr><th>Actividad</th><th>Confirmadas</th><th>Programadas</th><th>Cumplimiento</th></tr>
    ${r.por_tipo.map((t) => `<tr><td>${esc(t.nombre)}</td><td>${t.confirmados}</td><td>${t.total}</td><td>${Math.round((100 * t.confirmados) / t.total)} %</td></tr>`).join("") || '<tr><td colspan="4">Sin datos</td></tr>'}
    <tr><th>Total</th><th>${tot.c}</th><th>${tot.p}</th><th>${tot.p ? Math.round((100 * tot.c) / tot.p) + " %" : "–"}</th></tr></table>
    <h2>Cumplimiento diario</h2>${graficoBarras(r.dias)}
    <h2>Detalle por día</h2><table><tr><th>Fecha</th><th>Confirmadas</th><th>No confirmadas</th><th>Pánico</th><th>Perímetro</th><th>Sin comunicación</th></tr>
    ${r.dias.map((d) => `<tr><td>${fmt(d.fecha)}</td><td>${d.confirmados}</td><td>${d.omitidos}</td><td>${d.ayuda}</td><td>${d.perimetro}</td><td>${d.comunicacion}</td></tr>`).join("")}</table>
    <h2>Alertas registradas</h2><table><tr><th>Fecha</th><th>Hora</th><th>Tipo</th><th>Detalle</th></tr>
    ${r.alertas.map((a) => `<tr><td>${fmt(a.ts)}</td><td>${esc(hora(a.ts))}</td><td>${esc(nombres[a.tipo] || a.tipo)}</td><td>${esc(a.mensaje)}</td></tr>`).join("") || '<tr><td colspan="4">Sin alertas en el periodo</td></tr>'}</table>
    <p class="pie">Generado el ${new Date().toLocaleString("es-SV")}. Presencias recibidas: ${r.presencias} (${r.con_gps} con posición GPS). El perímetro se estima con la intensidad de la señal Wi-Fi de la casa; la pérdida de comunicación no confirma por sí sola una salida. Ninguna tecnología sustituye la supervisión humana.</p>`;
  window.print();
});

/* ================= AJUSTES ================= */
async function cargarAjustes() {
  S.config = await api("/api/config");
  const c = S.config;
  if (!$("#formGeneral").contains(document.activeElement)) {
    $("#cfgPaciente").value = c.paciente; $("#cfgMin").value = c.minutos_confirmar; $("#cfgSeg").value = c.segundos_desconexion;
  }
  $("#infoServidor").textContent = `const char* SERVIDOR = "${location.origin}";\nconst char* CLAVE_DISPOSITIVO = "(la misma de CLAVE_DISPOSITIVO en Render)";`;
  $("#infoAlmacen").textContent = `Datos guardados en: ${c.almacen}${c.almacen_error ? " · último error: " + c.almacen_error : ""}`;
  $("#txtDemo").textContent = S.estado && S.estado.demo ? "Hay historial de demostración cargado. Bórralo antes de presentar resultados reales." : "Carga 14 días de historial de ejemplo para practicar la presentación. Queda marcado como demostración.";
  pintarModulos();
  await cargarSubs();
}
async function cargarSubs() {
  const { suscripciones } = await api("/api/push/lista");
  $("#listaSubs").innerHTML = suscripciones.length ? suscripciones.map((s) => `<div class="item"><div><div class="t">${esc(s.etiqueta)}</div>
      <div class="s">Recibe: ${esc((s.categorias || "").split(",").filter(Boolean).map((k) => CATS[k] || k).join(", ") || "nada")}${s.ultimo_envio ? ` · último aviso ${esc(diaRel(s.ultimo_envio))} ${esc(hora(s.ultimo_envio))} (${s.ultimo_resultado === 201 || s.ultimo_resultado === 200 ? "entregado" : "error " + s.ultimo_resultado})` : ""}</div></div>
      <button class="btn btn-mini btn-sec" data-quitar-sub="${s.id}">Quitar</button></div>`).join("")
    : `<div class="vacio">Ningún celular o computadora tiene los avisos activados. Abre la app en el celular de cada encargado y toca «Permitir notificaciones».</div>`;
}
$("#listaSubs").addEventListener("click", async (ev) => { const b = ev.target.closest("[data-quitar-sub]"); if (b) { await api(`/api/push/${b.dataset.quitarSub}`, { method: "DELETE" }); toast("Dispositivo quitado."); cargarSubs(); } });
$("#formGeneral").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await api("/api/config", { method: "PUT", body: { paciente: $("#cfgPaciente").value.trim(), minutos_confirmar: $("#cfgMin").value, segundos_desconexion: $("#cfgSeg").value } });
  toast("Ajustes guardados."); cargarEstado();
});
$("#formClave").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try { await api("/api/clave", { method: "POST", body: { actual: $("#clActual").value, nueva: $("#clNueva").value } }); ev.target.reset(); toast("Clave cambiada. Las demás sesiones se cerraron."); } catch (e) { toast(e.message); }
});
$("#btnSalir").addEventListener("click", async () => { await api("/api/salir", { method: "POST" }).catch(() => {}); mostrarEntrada(); });
$("#btnCargarDemo").addEventListener("click", async () => { await api("/api/demo/cargar", { method: "POST" }); toast("Demostración cargada."); cargarEstado(); cargarAjustes(); });
$("#btnBorrarDemo").addEventListener("click", async () => { if (!window.confirm("¿Borrar el historial de demostración? Las rutinas se conservan.")) return; await api("/api/demo/borrar", { method: "POST" }); toast("Demostración borrada."); cargarEstado(); cargarAjustes(); });

/* ================= ARRANQUE ================= */
if (new URLSearchParams(location.search).has("alerta")) history.replaceState(null, "", "/");
mostrarEntrada();
registrarSW();
setInterval(() => { if (S.enApp || !$("#asistente").hidden) cargarEstado(); }, 3000);
setInterval(() => { if (S.enApp && S.vista !== "ajustes" && !$("#dlgRutina").open) cargarVista(); }, 8000);