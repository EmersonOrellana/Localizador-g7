#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor en la nube · Localizador GPS para personas con Alzheimer
Grupo 7 · Tema 7 · ARC115 · Ciclo II-2026

- Recibe la presencia y los eventos del ESP32 por internet (HTTPS en Render).
- Perímetro de cuidado por intensidad de la señal Wi-Fi (calibrado desde la app).
- Agenda de rutinas, detección de desconexión y notificaciones Web Push.
- Guarda todo en Firebase Realtime Database (o en datos.json para pruebas locales).

Variables de entorno (en Render):
  FIREBASE_URL              https://<proyecto>-default-rtdb.firebaseio.com
  FIREBASE_CUENTA_SERVICIO  contenido del JSON de la cuenta de servicio
  CLAVE_DISPOSITIVO         clave que usa el ESP32 y que se pide para configurar la app
  CONTACTO_VAPID            mailto:correo-del-grupo  (lo exigen los servicios de notificaciones)
  ZONA_HORARIA_HORAS        -6 para El Salvador
Uso local:  python servidor.py   [--puerto 8000] [--demo]
"""
import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import random
import secrets
import socket
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import webpush
from almacen import crear_almacen

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")

CLAVE_DISPOSITIVO = os.environ.get("CLAVE_DISPOSITIVO", "G7-clave-local")
CONTACTO_VAPID = os.environ.get("CONTACTO_VAPID", "mailto:grupo7-arc115@example.com")
ZONA_HORAS = float(os.environ.get("ZONA_HORARIA_HORAS", "-6"))
HISTERESIS_DB = 4          # dB que debe subir la señal para considerar el regreso
MARGEN_CALIBRACION = 3     # dB por debajo de la señal medida al fijar el límite
PRESETS_WIFI = {"casa": -67, "patio": -75, "calle": -82}

CONFIG_INICIAL = {"paciente": "Paciente", "minutos_confirmar": 15, "segundos_desconexion": 90}

TIPOS_RUTINA = {"medicamento": "Medicamento", "aseo": "Aseo personal", "caminata": "Caminata",
                "comida": "Comida", "otro": "Otro"}

# tipo -> (título de la notificación, categoría, urgencia)
TIPOS_ALERTA = {
    "sos": ("Botón de pánico activado", "ayuda", "high"),
    "perimetro_salida": ("Posible salida del perímetro", "perimetro", "high"),
    "perimetro_regreso": ("Regresó al perímetro", "perimetro", "normal"),
    "desconexion": ("Pérdida de comunicación", "comunicacion", "high"),
    "reconexion": ("Dispositivo conectado de nuevo", "comunicacion", "normal"),
    "recordatorio": ("Es hora de una rutina", "recordatorios", "normal"),
    "recordatorio_omitido": ("Recordatorio no confirmado", "recordatorios", "high"),
    "recordatorio_confirmado": ("Rutina confirmada", "recordatorios", "low"),
}
INFORMATIVAS = {"perimetro_regreso", "reconexion", "recordatorio", "recordatorio_confirmado"}
CATEGORIAS = ["ayuda", "perimetro", "comunicacion", "recordatorios"]

db = crear_almacen(BASE)
lock = threading.RLock()
PUERTO = 8000


# ------------------------------------------------------------------ utilidades
def ahora():
    return (datetime.now(timezone.utc) + timedelta(hours=ZONA_HORAS)).replace(tzinfo=None)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def nuevo_id():
    return f"{int(time.time() * 1000):013d}{secrets.token_hex(2)}"


def enlace_mapa(lat, lng):
    return f"https://maps.google.com/?q={lat:.6f},{lng:.6f}"


def cfg(clave, defecto=None):
    v = db.obtener(f"config/{clave}")
    if v is None:
        return CONFIG_INICIAL.get(clave, defecto)
    return v


def num(v, defecto):
    try:
        return float(v)
    except (TypeError, ValueError):
        return defecto


def est():
    return db.obtener("estado", {}) or {}


def set_est(**cambios):
    db.actualizar("estado", cambios)


def ultima_posicion():
    e = est()
    if e.get("pos_lat") is None:
        return None
    return {"lat": e["pos_lat"], "lng": e["pos_lng"], "ts": e.get("pos_ts"), "sats": e.get("pos_sats"),
            "sim": bool(e.get("sim"))}


def mejor_ubicacion():
    """Ubicación para notificaciones: GPS si hay, si no la casa (Wi-Fi)."""
    u = ultima_posicion()
    if u:
        return u["lat"], u["lng"]
    if cfg("casa_lat") is not None:
        return cfg("casa_lat"), cfg("casa_lng")
    return None, None


# ------------------------------------------------------------- notificaciones
def claves_vapid():
    pem = cfg("vapid_privada")
    if not pem:
        pem, _ = webpush.generar_claves_vapid()
        db.actualizar("config", {"vapid_privada": pem})
    return pem


def notificar(categoria, titulo, cuerpo, urgencia="normal", etiqueta=None, url="/"):
    subs = db.obtener("push", {}) or {}
    destinos = {k: s for k, s in subs.items() if categoria in (s.get("categorias") or "").split(",")}
    if not destinos:
        return 0
    pem = claves_vapid()
    carga = {"titulo": titulo, "cuerpo": cuerpo, "etiqueta": etiqueta or categoria, "url": url,
             "urgente": urgencia == "high", "categoria": categoria}

    def trabajo():
        for k, s in destinos.items():
            codigo, detalle = webpush.enviar(s, carga, pem, CONTACTO_VAPID, urgencia=urgencia)
            if codigo in (404, 410):
                db.borrar(f"push/{k}")        # el navegador quitó el permiso o la suscripción venció
                continue
            if codigo not in (200, 201, 202):
                print(f"[push] {s.get('etiqueta')}: {codigo} {detalle}")
            if db.obtener(f"push/{k}"):
                db.actualizar(f"push/{k}", {"ultimo_envio": iso(ahora()), "ultimo_resultado": codigo})

    threading.Thread(target=trabajo, daemon=True).start()
    return len(destinos)


def crear_alerta(tipo, mensaje, lat=None, lng=None, demo=False, ts=None, avisar=True, categorias_extra=()):
    titulo, categoria, urgencia = TIPOS_ALERTA[tipo]
    aid = nuevo_id()
    a = {"ts": ts or iso(ahora()), "tipo": tipo, "mensaje": mensaje, "atendida": tipo in INFORMATIVAS}
    if lat is not None:
        a["lat"], a["lng"] = lat, lng
    if demo:
        a["demo"] = True
        a["atendida"] = True
    if tipo != "recordatorio":           # "es hora" solo se notifica, no se guarda en el historial
        db.poner(f"alertas/{aid}", a)
    if avisar and not demo:
        paciente = cfg("paciente")
        for cat in {categoria, *categorias_extra}:
            notificar(cat, f"{titulo} · {paciente}", mensaje, urgencia, etiqueta=tipo + aid[-4:] if tipo == "sos" else tipo)
    return aid


# ------------------------------------------------------- lógica del dispositivo
def procesar_dispositivo(c, ip):
    with lock:
        now = ahora()
        e = est()
        cambios = {"ultima_vez": time.time(), "ip": ip, "sim": bool(c.get("sim")), "ssid": c.get("ssid"),
                   "rssi": c.get("rssi"), "fix": bool(c.get("fix")), "sats": int(c.get("sats") or 0)}
        fix = bool(c.get("fix"))
        if fix:
            cambios.update(pos_lat=c.get("lat"), pos_lng=c.get("lng"), pos_ts=iso(now), pos_sats=cambios["sats"])

        # Conexión: la recuperación se confirma con dos presencias seguidas
        if not e.get("conectado"):
            consecutivas = int(e.get("consecutivas", 0)) + 1
            if not e.get("desconectado_avisado") or consecutivas >= 2:
                if e.get("desconectado_avisado"):
                    crear_alerta("reconexion", f"El dispositivo volvió a comunicarse (Wi-Fi {c.get('ssid') or ''}).")
                cambios.update(conectado=True, desconectado_avisado=False, consecutivas=0)
            else:
                cambios["consecutivas"] = consecutivas

        # Perímetro por señal Wi-Fi
        umbral = cfg("wifi_umbral")
        rssi = c.get("rssi")
        perimetro = e.get("perimetro", "sin_dato")
        if umbral is None:
            perimetro = "sin_configurar"
        elif rssi is not None:
            rssi = float(rssi)
            if perimetro != "fuera" and rssi < umbral:
                perimetro = "fuera"
                cambios["silenciado"] = False
                lat, lng = (c.get("lat"), c.get("lng")) if fix else mejor_ubicacion()
                crear_alerta("perimetro_salida",
                             f"La señal Wi-Fi bajó a {rssi:.0f} dBm (límite {umbral:.0f} dBm): "
                             f"se está alejando de la casa.", lat, lng)
            elif perimetro == "fuera" and rssi >= umbral + HISTERESIS_DB:
                perimetro = "dentro"
                cambios["silenciado"] = False
                crear_alerta("perimetro_regreso", f"La señal Wi-Fi volvió a {rssi:.0f} dBm: está dentro de la casa.")
            elif perimetro not in ("dentro", "fuera"):
                perimetro = "dentro" if rssi >= umbral else perimetro
        cambios["perimetro"] = perimetro

        # Eventos del botón
        for ev in c.get("eventos") or []:
            ev = str(ev)
            if ev == "sos":
                cambios["detener"] = False
                lat, lng = (c.get("lat"), c.get("lng")) if fix else mejor_ubicacion()
                if fix:
                    fuente = "el GPS"
                elif ultima_posicion():
                    fuente = "la última posición GPS (ahora sin señal)"
                elif lat is not None:
                    fuente = "la ubicación de la casa (sin señal GPS)"
                else:
                    fuente = "nada todavía: no hay GPS ni ubicación de la casa"
                crear_alerta("sos", f"La persona presionó el botón de ayuda. Ubicación según {fuente}.", lat, lng)
            elif ev.startswith("confirmar:"):
                confirmar_evento(ev.split(":", 1)[1], "botón")
            elif ev == "cancelar" and perimetro == "fuera":
                cambios["silenciado"] = True

        # Contador diario para los reportes
        hoy = now.date().isoformat()
        r = db.obtener(f"resumen/{hoy}", {}) or {}
        db.actualizar(f"resumen/{hoy}", {"presencias": int(r.get("presencias", 0)) + 1,
                                         "con_gps": int(r.get("con_gps", 0)) + (1 if fix else 0)})
        set_est(**cambios)
        e = est()

        # Respuesta al ESP32 (texto clave=valor)
        lineas = ["ok=1", f"hora={now.strftime('%H:%M:%S')}",
                  f"umbral={int(umbral) if umbral is not None else 0}",
                  f"perimetro={perimetro}", f"silenciado={1 if e.get('silenciado') else 0}"]
        rec = evento_sonando()
        lineas.append(f"recordatorio={rec[0]}|{rec[1]}" if rec else "recordatorio=0")
        lineas.append(f"buscar={1 if e.get('buscar') else 0}")
        lineas.append(f"detener={1 if e.get('detener') else 0}")
        lineas.append(f"rapido={1 if time.time() < num(e.get('rapido_hasta'), 0) else 0}")
        set_est(buscar=False, detener=False)
        return "\n".join(lineas) + "\n"


def nombre_rutina(r):
    return r["titulo"] + (f" {r['detalle']}" if r.get("detalle") else "")


def evento_sonando():
    hoy = ahora().date().isoformat()
    rutinas = db.obtener("rutinas", {}) or {}
    sonando = [(ev.get("aviso_ts", ""), rid) for rid, ev in (db.obtener(f"eventos/{hoy}", {}) or {}).items()
               if ev.get("estado") == "sonando" and rid in rutinas]
    if not sonando:
        return None
    rid = sorted(sonando)[0][1]
    return f"{hoy}_{rid}", nombre_rutina(rutinas[rid]).replace("\n", " ")


def confirmar_evento(evento_id, por):
    try:
        fecha, rid = evento_id.split("_", 1)
    except ValueError:
        return False
    ev = db.obtener(f"eventos/{fecha}/{rid}")
    r = db.obtener(f"rutinas/{rid}")
    if not ev or not r or ev.get("estado") == "confirmado":
        return False
    db.actualizar(f"eventos/{fecha}/{rid}", {"estado": "confirmado", "confirmado_ts": iso(ahora()), "confirmado_por": por})
    crear_alerta("recordatorio_confirmado", f"Confirmado ({por}): {nombre_rutina(r)} de las {ev['hora_programada']}.")
    return True


def revisar():
    """Agenda y conexión. Corre cada 5 s y también en cada visita a /api/tick."""
    with lock:
        revisar_agenda()
        revisar_conexion()


def revisar_agenda():
    now = ahora()
    hoy = now.date().isoformat()
    hhmm = now.strftime("%H:%M")
    minutos = num(cfg("minutos_confirmar"), 15)
    dia = str(now.isoweekday())
    rutinas = db.obtener("rutinas", {}) or {}
    eventos_hoy = db.obtener(f"eventos/{hoy}", {}) or {}

    # Días anteriores que quedaron abiertos
    ultima = cfg("ultima_revision_fecha")
    if ultima and ultima != hoy:
        for fecha, evs in (db.obtener("eventos", {}) or {}).items():
            if fecha >= hoy:
                continue
            for rid, ev in evs.items():
                if ev.get("estado") == "sonando":
                    db.actualizar(f"eventos/{fecha}/{rid}", {"estado": "omitido"})
                elif ev.get("estado") == "programado":
                    db.actualizar(f"eventos/{fecha}/{rid}", {"estado": "sin_dato"})
    if ultima != hoy:
        db.actualizar("config", {"ultima_revision_fecha": hoy})

    for rid, r in rutinas.items():
        if r.get("eliminada") or not r.get("activa", True) or dia not in (r.get("dias") or ""):
            continue
        ev = eventos_hoy.get(rid)
        if ev is None:
            h, m = map(int, r["hora"].split(":"))
            programada = now.replace(hour=h, minute=m, second=0, microsecond=0)
            estado = "sin_dato" if now >= programada + timedelta(minutes=minutos) else "programado"
            ev = {"hora_programada": r["hora"], "estado": estado}
            db.poner(f"eventos/{hoy}/{rid}", ev)
        if ev["estado"] == "programado" and ev["hora_programada"] <= hhmm:
            db.actualizar(f"eventos/{hoy}/{rid}", {"estado": "sonando", "aviso_ts": iso(now)})
            crear_alerta("recordatorio", f"{TIPOS_RUTINA.get(r['tipo'], '')}: {nombre_rutina(r)} "
                                         f"({ev['hora_programada']}). El dispositivo está sonando.")
        elif ev["estado"] == "sonando" and ev.get("aviso_ts", "") <= iso(now - timedelta(minutes=minutos)):
            db.actualizar(f"eventos/{hoy}/{rid}", {"estado": "omitido"})
            lat, lng = mejor_ubicacion()
            crear_alerta("recordatorio_omitido", f"No se confirmó: {nombre_rutina(r)} de las {ev['hora_programada']} "
                                                 f"({int(minutos)} min sin respuesta).", lat, lng)


def revisar_conexion():
    e = est()
    if not e.get("conectado") or e.get("ultima_vez") is None:
        return
    if time.time() - float(e["ultima_vez"]) <= num(cfg("segundos_desconexion"), 90):
        return
    set_est(conectado=False, consecutivas=0, desconectado_avisado=True)
    hora = (datetime.fromtimestamp(float(e["ultima_vez"]), timezone.utc) + timedelta(hours=ZONA_HORAS)).strftime("%H:%M")
    umbral = cfg("wifi_umbral")
    rssi = e.get("rssi")
    lat, lng = mejor_ubicacion()
    cerca = umbral is not None and rssi is not None and (float(rssi) < umbral + 6 or e.get("perimetro") == "fuera")
    if cerca:
        msg = (f"Se perdió la señal a las {hora} cuando el Wi-Fi ya estaba débil ({float(rssi):.0f} dBm, cerca del "
               f"límite): posible salida de la casa. Verificar a la persona.")
        crear_alerta("desconexion", msg, lat, lng, categorias_extra=("perimetro",))
    else:
        msg = (f"Se perdió la señal a las {hora}. La señal Wi-Fi era buena, así que puede estar apagado o sin "
               f"energía. Verificar a la persona; esto no confirma una salida del perímetro.")
        crear_alerta("desconexion", msg, lat, lng)


def ciclo():
    while True:
        try:
            revisar()
        except Exception as ex:  # noqa: BLE001
            print("[revisión] error:", ex)
        time.sleep(5)


# ------------------------------------------------------------- consultas app
def rutinas_de(fecha):
    evs = db.obtener(f"eventos/{fecha}", {}) or {}
    filas = []
    for rid, r in (db.obtener("rutinas", {}) or {}).items():
        if r.get("eliminada"):
            continue
        d = dict(r, id=rid, activa=r.get("activa", True))
        ev = evs.get(rid)
        d["evento"] = dict(ev, id=f"{fecha}_{rid}") if ev else None
        filas.append(d)
    return sorted(filas, key=lambda x: x["hora"])


def estado_publico():
    e = est()
    seg = None if e.get("ultima_vez") is None else int(time.time() - float(e["ultima_vez"]))
    return {"configurado": bool(cfg("clave_app_hash")), "visto": seg is not None,
            "conectado": bool(e.get("conectado")), "segundos_desde": seg, "ahora": iso(ahora())}


def estado_app():
    hoy = ahora().date().isoformat()
    e = est()
    alertas = db.obtener("alertas", {}) or {}
    lista = sorted(({**a, "id": k} for k, a in alertas.items()), key=lambda a: a["ts"], reverse=True)
    sos = next((a for a in lista if a["tipo"] == "sos" and not a.get("atendida")), None)
    pendientes = [a for a in lista if not a.get("atendida")][:5]
    umbral = cfg("wifi_umbral")
    pub = estado_publico()
    return {
        **pub,
        "paciente": cfg("paciente"),
        "demo": any(a.get("demo") for a in alertas.values()),
        "dispositivo": {**pub, "rssi": e.get("rssi"), "ssid": e.get("ssid"), "simulado": bool(e.get("sim")),
                        "fix": bool(e.get("fix")), "sats": e.get("sats", 0)},
        "posicion": ultima_posicion(),
        "casa": {"lat": cfg("casa_lat"), "lng": cfg("casa_lng")} if cfg("casa_lat") is not None else None,
        "wifi": {"umbral": umbral, "rssi": e.get("rssi"), "ssid": e.get("ssid"), "histeresis": HISTERESIS_DB,
                 "calibrando": time.time() < num(e.get("rapido_hasta"), 0)},
        "perimetro": e.get("perimetro", "sin_dato"),
        "silenciado": bool(e.get("silenciado")),
        "sos": sos,
        "alertas_pendientes": pendientes,
        "proximas": [r for r in rutinas_de(hoy) if r["evento"] and r["evento"]["estado"] in ("programado", "sonando")],
        "servidor": {"url_publica": os.environ.get("RENDER_EXTERNAL_URL"), "ips": ips_locales(), "puerto": PUERTO},
    }


def reportes(dias):
    hoy = ahora().date()
    inicio = hoy - timedelta(days=dias - 1)
    fechas = [(inicio + timedelta(days=i)).isoformat() for i in range(dias)]
    por_dia = {f: {"fecha": f, "programados": 0, "confirmados": 0, "omitidos": 0, "ayuda": 0, "perimetro": 0,
                   "recordatorios": 0, "comunicacion": 0} for f in fechas}
    por_tipo = {t: {"tipo": t, "nombre": n, "confirmados": 0, "total": 0} for t, n in TIPOS_RUTINA.items()}
    rutinas = db.obtener("rutinas", {}) or {}
    eventos = db.obtener("eventos", {}) or {}
    for f in fechas:
        for rid, ev in (eventos.get(f) or {}).items():
            if ev.get("estado") not in ("confirmado", "omitido"):
                continue
            tipo = (rutinas.get(rid) or {}).get("tipo", "otro")
            d, t = por_dia[f], por_tipo.setdefault(tipo, {"tipo": tipo, "nombre": tipo, "confirmados": 0, "total": 0})
            d["programados"] += 1
            t["total"] += 1
            if ev["estado"] == "confirmado":
                d["confirmados"] += 1
                t["confirmados"] += 1
            else:
                d["omitidos"] += 1
    mapa = {"sos": "ayuda", "perimetro_salida": "perimetro", "recordatorio_omitido": "recordatorios",
            "desconexion": "comunicacion"}
    alertas = []
    for k, a in sorted((db.obtener("alertas", {}) or {}).items(), key=lambda x: x[1]["ts"]):
        f = a["ts"][:10]
        if f < inicio.isoformat():
            continue
        if a["tipo"] in mapa and f in por_dia:
            por_dia[f][mapa[a["tipo"]]] += 1
        if a["tipo"] not in INFORMATIVAS:
            alertas.append({**a, "id": k})
    res = db.obtener("resumen", {}) or {}
    return {"desde": inicio.isoformat(), "hasta": hoy.isoformat(), "paciente": cfg("paciente"),
            "dias": list(por_dia.values()), "por_tipo": [t for t in por_tipo.values() if t["total"]],
            "alertas": alertas,
            "presencias": sum(int((res.get(f) or {}).get("presencias", 0)) for f in fechas),
            "con_gps": sum(int((res.get(f) or {}).get("con_gps", 0)) for f in fechas)}


def ips_locales():
    if os.environ.get("RENDER"):
        return []
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    ips.discard("127.0.0.1")
    return sorted(ips)


def cargar_demo():
    with lock:
        rutinas = db.obtener("rutinas", {}) or {}
        if not any(not r.get("eliminada") for r in rutinas.values()):
            for t, ti, de, h in [("comida", "Desayuno", "", "07:30"), ("aseo", "Aseo personal", "", "09:00"),
                                 ("medicamento", "Donepezilo", "5 mg", "14:00"),
                                 ("caminata", "Caminata", "20 min acompañado", "15:30"),
                                 ("comida", "Cena", "", "19:00"), ("medicamento", "Memantina", "10 mg", "20:00")]:
                db.poner(f"rutinas/{nuevo_id()}", {"tipo": t, "titulo": ti, "detalle": de, "hora": h,
                                                   "dias": "1234567", "activa": True})
                time.sleep(0.002)
            rutinas = db.obtener("rutinas", {}) or {}
        rnd = random.Random(7)
        hoy = ahora().date()
        for i in range(14, 0, -1):
            f = hoy - timedelta(days=i)
            fs = f.isoformat()
            for rid, r in rutinas.items():
                if r.get("eliminada"):
                    continue
                ok = rnd.random() < 0.86
                h, m = map(int, r["hora"].split(":"))
                base = datetime(f.year, f.month, f.day, h, m)
                db.poner(f"eventos/{fs}/{rid}", {
                    "hora_programada": r["hora"], "estado": "confirmado" if ok else "omitido", "aviso_ts": iso(base),
                    "confirmado_ts": iso(base + timedelta(minutes=rnd.randint(1, 9))) if ok else None,
                    "confirmado_por": "botón" if ok else None, "demo": True})
                if not ok:
                    crear_alerta("recordatorio_omitido", f"No se confirmó: {nombre_rutina(r)} de las {r['hora']} "
                                 "(demostración).", demo=True, ts=iso(base + timedelta(minutes=15)))
            for prob, tipo, msg in [(0.35, "perimetro_salida", "La señal Wi-Fi bajó del límite (demostración)."),
                                    (0.2, "sos", "La persona presionó el botón de ayuda (demostración)."),
                                    (0.2, "desconexion", "Se perdió la señal del dispositivo (demostración).")]:
                if rnd.random() < prob:
                    t = datetime(f.year, f.month, f.day, rnd.randint(8, 20), rnd.randint(0, 59))
                    crear_alerta(tipo, msg, demo=True, ts=iso(t))
            db.actualizar(f"resumen/{fs}", {"presencias": 2600 + rnd.randint(0, 200), "con_gps": 900 + rnd.randint(0, 300),
                                            "demo": True})
        db.actualizar("config", {"demo": True})


def borrar_demo():
    with lock:
        for k, a in (db.obtener("alertas", {}) or {}).items():
            if a.get("demo"):
                db.borrar(f"alertas/{k}")
        for f, evs in (db.obtener("eventos", {}) or {}).items():
            for rid, ev in evs.items():
                if ev.get("demo"):
                    db.borrar(f"eventos/{f}/{rid}")
        for f, r in (db.obtener("resumen", {}) or {}).items():
            if r.get("demo"):
                db.borrar(f"resumen/{f}")
        db.actualizar("config", {"demo": None})


# ------------------------------------------------------------------ acceso
def hash_clave(clave, sal):
    return hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(sal), 120_000).hex()


def crear_sesion():
    token = secrets.token_urlsafe(32)
    h = hashlib.sha256(token.encode()).hexdigest()[:40]
    db.poner(f"sesiones/{h}", {"creada": iso(ahora())})
    return token


def sesion_valida(token):
    if not token:
        return False
    h = hashlib.sha256(token.encode()).hexdigest()[:40]
    s = db.obtener(f"sesiones/{h}")
    if not s:
        return False
    return s.get("creada", "") >= iso(ahora() - timedelta(days=60))


# ----------------------------------------------------------------- HTTP
class Manejador(BaseHTTPRequestHandler):
    server_version = "LocalizadorG7/2.0"

    def log_message(self, fmt, *args):
        if self.path.startswith("/api/dispositivo") and self.command == "POST":
            print(f"[{ahora().strftime('%H:%M:%S')}] ESP32 {self._ip()} -> {args[1] if len(args) > 1 else ''}")

    def _ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def _https(self):
        return self.headers.get("X-Forwarded-Proto", "") == "https"

    def _enviar(self, codigo, tipo, cuerpo, extra=None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _json(self, datos, codigo=200, extra=None):
        self._enviar(codigo, "application/json; charset=utf-8", json.dumps(datos, ensure_ascii=False).encode(), extra)

    def _texto(self, texto, codigo=200):
        self._enviar(codigo, "text/plain; charset=utf-8", texto.encode())

    def _cuerpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n or n > 100_000:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _ruta(self):
        p = urllib.parse.urlparse(self.path)
        return p.path.rstrip("/") or "/", urllib.parse.parse_qs(p.query)

    def _token(self):
        for parte in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = parte.strip().partition("=")
            if k == "sesion":
                return v
        return None

    def _cookie(self, token, dias=60):
        seguro = "; Secure" if self._https() else ""
        return {"Set-Cookie": f"sesion={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={dias * 86400}{seguro}"}

    def _estatico(self, ruta):
        if ruta == "/":
            ruta = "/index.html"
        archivo = os.path.normpath(os.path.join(WEB, ruta.lstrip("/")))
        if not archivo.startswith(WEB) or not os.path.isfile(archivo):
            return self._texto("No encontrado", 404)
        tipo = mimetypes.guess_type(archivo)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript", "application/manifest+json", "image/svg+xml"):
            tipo += "; charset=utf-8"
        with open(archivo, "rb") as f:
            datos = f.read()
        extra = {"Cache-Control": "no-cache"}
        if ruta == "/sw.js":
            extra["Service-Worker-Allowed"] = "/"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(datos)

    def do_HEAD(self):
        self.do_GET()

    # ------------------------------------------------------------ GET
    def do_GET(self):
        ruta, q = self._ruta()
        if not ruta.startswith("/api/"):
            return self._estatico(ruta)
        if ruta == "/api/tick":                       # lo visita GitHub Actions para mantenerlo despierto
            revisar()
            return self._json({"ok": True, "hora": iso(ahora())})
        if ruta == "/api/publico":
            return self._json({**estado_publico(), "sesion": sesion_valida(self._token())})
        if not sesion_valida(self._token()):
            return self._json({"error": "Inicia sesión"}, 401)
        with lock:
            if ruta == "/api/estado":
                return self._json(estado_app())
            if ruta == "/api/rutinas":
                fecha = (q.get("fecha") or [ahora().date().isoformat()])[0]
                return self._json({"fecha": fecha, "rutinas": rutinas_de(fecha)})
            if ruta == "/api/alertas":
                limite = int((q.get("limite") or ["150"])[0])
                lista = sorted(({**a, "id": k} for k, a in (db.obtener("alertas", {}) or {}).items()),
                               key=lambda a: (a["ts"], a["id"]), reverse=True)
                return self._json({"alertas": lista[:limite]})
            if ruta == "/api/reportes":
                return self._json(reportes(max(1, min(90, int((q.get("dias") or ["7"])[0])))))
            if ruta == "/api/config":
                return self._json({"paciente": cfg("paciente"), "minutos_confirmar": cfg("minutos_confirmar"),
                                   "segundos_desconexion": cfg("segundos_desconexion"), "wifi_umbral": cfg("wifi_umbral"),
                                   "casa_lat": cfg("casa_lat"), "casa_lng": cfg("casa_lng"),
                                   "presets": PRESETS_WIFI, "almacen": db.descripcion(),
                                   "almacen_error": db.ultimo_error})
            if ruta == "/api/push/clave":
                return self._json({"clave": webpush.clave_publica(claves_vapid())})
            if ruta == "/api/push/lista":
                subs = db.obtener("push", {}) or {}
                return self._json({"suscripciones": [{"id": k, "etiqueta": s.get("etiqueta"), "categorias": s.get("categorias"),
                                                      "creada": s.get("creada"), "ultimo_envio": s.get("ultimo_envio"),
                                                      "ultimo_resultado": s.get("ultimo_resultado")} for k, s in subs.items()]})
        return self._json({"error": "ruta desconocida"}, 404)

    # ------------------------------------------------------------ POST
    def do_POST(self):
        ruta, _ = self._ruta()
        c = self._cuerpo()

        if ruta == "/api/dispositivo":
            if not hmac.compare_digest(self.headers.get("X-Clave", ""), CLAVE_DISPOSITIVO):
                return self._texto("ok=0\nerror=clave\n", 401)
            return self._texto(procesar_dispositivo(c, self._ip()))

        if ruta == "/api/configurar-inicial":
            with lock:
                if cfg("clave_app_hash"):
                    return self._json({"error": "La app ya está configurada. Inicia sesión."}, 400)
                if not hmac.compare_digest(str(c.get("clave_dispositivo", "")), CLAVE_DISPOSITIVO):
                    return self._json({"error": "La clave del dispositivo no coincide con la del servidor."}, 403)
                clave = str(c.get("clave_app", ""))
                if len(clave) < 6:
                    return self._json({"error": "La clave de acceso debe tener al menos 6 caracteres."}, 400)
                sal = secrets.token_hex(16)
                db.actualizar("config", {"clave_app_sal": sal, "clave_app_hash": hash_clave(clave, sal),
                                         "paciente": (c.get("paciente") or "Paciente").strip()[:60]})
                return self._json({"ok": True}, extra=self._cookie(crear_sesion()))

        if ruta == "/api/login":
            time.sleep(0.4)
            sal, h = cfg("clave_app_sal"), cfg("clave_app_hash")
            if not h or not hmac.compare_digest(hash_clave(str(c.get("clave", "")), sal), h):
                return self._json({"error": "Clave incorrecta."}, 403)
            return self._json({"ok": True}, extra=self._cookie(crear_sesion()))

        if not sesion_valida(self._token()):
            return self._json({"error": "Inicia sesión"}, 401)

        with lock:
            if ruta == "/api/salir":
                tok = self._token()
                db.borrar(f"sesiones/{hashlib.sha256(tok.encode()).hexdigest()[:40]}")
                return self._json({"ok": True}, extra=self._cookie("", 0))
            if ruta == "/api/rutinas":
                hora = str(c.get("hora", "")).strip()
                if not c.get("titulo") or len(hora) != 5:
                    return self._json({"error": "Faltan el nombre o la hora."}, 400)
                db.poner(f"rutinas/{nuevo_id()}", {"tipo": c.get("tipo", "otro"), "titulo": c["titulo"].strip()[:60],
                                                   "detalle": (c.get("detalle") or "").strip()[:60], "hora": hora,
                                                   "dias": c.get("dias") or "1234567", "activa": True})
                revisar_agenda()
                return self._json({"ok": True})
            if ruta.startswith("/api/eventos/") and ruta.endswith("/confirmar"):
                return self._json({"ok": confirmar_evento(ruta.split("/")[3], "app")})
            if ruta.startswith("/api/alertas/") and ruta.endswith("/atender"):
                aid = ruta.split("/")[3]
                a = db.obtener(f"alertas/{aid}")
                if a:
                    db.actualizar(f"alertas/{aid}", {"atendida": True, "atendida_ts": iso(ahora())})
                    if a["tipo"] == "sos":
                        set_est(detener=True)
                    if a["tipo"] == "perimetro_salida" and est().get("perimetro") == "fuera":
                        set_est(silenciado=True)
                return self._json({"ok": bool(a)})
            if ruta == "/api/perimetro":
                modo = c.get("modo")
                e = est()
                if modo == "actual":
                    seg = time.time() - num(e.get("ultima_vez"), 0)
                    if e.get("rssi") is None or seg > 60:
                        return self._json({"error": "El dispositivo no ha enviado señal en el último minuto."}, 400)
                    umbral = round(float(e["rssi"])) - MARGEN_CALIBRACION
                elif modo in PRESETS_WIFI:
                    umbral = PRESETS_WIFI[modo]
                elif modo == "valor":
                    umbral = int(num(c.get("valor"), -75))
                else:
                    return self._json({"error": "Modo desconocido."}, 400)
                umbral = max(-95, min(-40, umbral))
                db.actualizar("config", {"wifi_umbral": umbral})
                set_est(perimetro="sin_dato", silenciado=False)
                return self._json({"ok": True, "umbral": umbral})
            if ruta == "/api/perimetro/calibrar":
                set_est(rapido_hasta=time.time() + 180)   # el ESP32 envía cada 3 s durante 3 min
                return self._json({"ok": True})
            if ruta == "/api/casa":
                if c.get("usar_gps"):
                    u = ultima_posicion()
                    if not u:
                        return self._json({"error": "El dispositivo todavía no tiene posición GPS."}, 400)
                    lat, lng = u["lat"], u["lng"]
                else:
                    lat, lng = num(c.get("lat"), None), num(c.get("lng"), None)
                    if lat is None or lng is None or abs(lat) > 90 or abs(lng) > 180:
                        return self._json({"error": "Ubicación no válida."}, 400)
                db.actualizar("config", {"casa_lat": round(lat, 6), "casa_lng": round(lng, 6)})
                return self._json({"ok": True, "lat": lat, "lng": lng})
            if ruta == "/api/push/suscribir":
                s = c.get("suscripcion") or {}
                claves = s.get("keys") or {}
                if not s.get("endpoint") or not claves.get("p256dh") or not claves.get("auth"):
                    return self._json({"error": "Suscripción incompleta."}, 400)
                pid = hashlib.sha256(s["endpoint"].encode()).hexdigest()[:20]
                cats = ",".join(x for x in (c.get("categorias") or CATEGORIAS) if x in CATEGORIAS)
                db.poner(f"push/{pid}", {"endpoint": s["endpoint"], "p256dh": claves["p256dh"], "auth": claves["auth"],
                                         "etiqueta": (c.get("etiqueta") or "Encargado").strip()[:40],
                                         "categorias": cats, "creada": iso(ahora())})
                return self._json({"ok": True, "id": pid})
            if ruta == "/api/push/prueba":
                n = 0
                for cat in CATEGORIAS:
                    n = max(n, notificar(cat, "Prueba · Localizador Grupo 7",
                                         "Las notificaciones funcionan en este dispositivo.", "normal", etiqueta="prueba"))
                if not n:
                    return self._json({"error": "Ningún dispositivo tiene notificaciones activadas."}, 400)
                return self._json({"ok": True, "destinos": n})
            if ruta == "/api/push/quitar":
                endpoint = c.get("endpoint")
                pid = c.get("id") or (hashlib.sha256(endpoint.encode()).hexdigest()[:20] if endpoint else None)
                if pid:
                    db.borrar(f"push/{pid}")
                return self._json({"ok": True})
            if ruta == "/api/dispositivo/buscar":
                set_est(buscar=True)
                return self._json({"ok": True})
            if ruta == "/api/demo/cargar":
                cargar_demo()
                return self._json({"ok": True})
            if ruta == "/api/demo/borrar":
                borrar_demo()
                return self._json({"ok": True})
            if ruta == "/api/clave":
                actual, nueva = str(c.get("actual", "")), str(c.get("nueva", ""))
                if not hmac.compare_digest(hash_clave(actual, cfg("clave_app_sal")), cfg("clave_app_hash")):
                    return self._json({"error": "La clave actual no es correcta."}, 403)
                if len(nueva) < 6:
                    return self._json({"error": "La clave nueva debe tener al menos 6 caracteres."}, 400)
                sal = secrets.token_hex(16)
                db.actualizar("config", {"clave_app_sal": sal, "clave_app_hash": hash_clave(nueva, sal)})
                db.poner("sesiones", None)
                return self._json({"ok": True}, extra=self._cookie(crear_sesion()))
        return self._json({"error": "ruta desconocida"}, 404)

    # ------------------------------------------------------------ PUT / DELETE
    def do_PUT(self):
        ruta, _ = self._ruta()
        c = self._cuerpo()
        if not sesion_valida(self._token()):
            return self._json({"error": "Inicia sesión"}, 401)
        with lock:
            if ruta.startswith("/api/rutinas/"):
                rid = ruta.split("/")[3]
                if not db.obtener(f"rutinas/{rid}"):
                    return self._json({"error": "No existe."}, 404)
                campos = {k: c[k] for k in ("tipo", "titulo", "detalle", "hora", "dias", "activa") if k in c}
                db.actualizar(f"rutinas/{rid}", campos)
                hoy = ahora().date().isoformat()
                ev = db.obtener(f"eventos/{hoy}/{rid}")
                if ev and ev.get("estado") in ("programado", "sin_dato"):
                    db.borrar(f"eventos/{hoy}/{rid}")
                revisar_agenda()
                return self._json({"ok": True})
            if ruta == "/api/config":
                cambios = {}
                if "paciente" in c:
                    cambios["paciente"] = (str(c["paciente"]).strip() or "Paciente")[:60]
                for k, minimo in (("minutos_confirmar", 1), ("segundos_desconexion", 30)):
                    if k in c:
                        cambios[k] = max(minimo, int(num(c[k], minimo)))
                db.actualizar("config", cambios)
                return self._json({"ok": True})
            if ruta.startswith("/api/push/"):
                pid = ruta.split("/")[3]
                if db.obtener(f"push/{pid}"):
                    cats = ",".join(x for x in (c.get("categorias") or []) if x in CATEGORIAS)
                    db.actualizar(f"push/{pid}", {"categorias": cats, "etiqueta": (c.get("etiqueta") or "Encargado")[:40]})
                return self._json({"ok": True})
        return self._json({"error": "ruta desconocida"}, 404)

    def do_DELETE(self):
        ruta, _ = self._ruta()
        if not sesion_valida(self._token()):
            return self._json({"error": "Inicia sesión"}, 401)
        with lock:
            if ruta.startswith("/api/rutinas/"):
                rid = ruta.split("/")[3]
                db.actualizar(f"rutinas/{rid}", {"eliminada": True})
                hoy = ahora().date().isoformat()
                ev = db.obtener(f"eventos/{hoy}/{rid}")
                if ev and ev.get("estado") in ("programado", "sonando"):
                    db.borrar(f"eventos/{hoy}/{rid}")
                return self._json({"ok": True})
            if ruta.startswith("/api/push/"):
                db.borrar(f"push/{ruta.split('/')[3]}")
                return self._json({"ok": True})
        return self._json({"error": "ruta desconocida"}, 404)


def main():
    global PUERTO
    ap = argparse.ArgumentParser(description="Servidor del Localizador GPS · Grupo 7")
    ap.add_argument("--puerto", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--demo", action="store_true", help="cargar rutinas e historial de ejemplo")
    args = ap.parse_args()
    PUERTO = args.puerto
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    mimetypes.add_type("image/svg+xml", ".svg")

    db.iniciar()
    claves_vapid()
    if args.demo:
        cargar_demo()
    threading.Thread(target=ciclo, daemon=True).start()

    srv = ThreadingHTTPServer(("0.0.0.0", PUERTO), Manejador)
    print("=" * 64)
    print(" Localizador GPS · Grupo 7")
    print(f" Datos en: {db.descripcion()}")
    if os.environ.get("RENDER_EXTERNAL_URL"):
        print(f" App pública: {os.environ['RENDER_EXTERNAL_URL']}")
    else:
        print(f" App en esta computadora: http://localhost:{PUERTO}")
        for ip in ips_locales():
            print(f" En la red local:        http://{ip}:{PUERTO}")
    print(f" Clave del dispositivo: {'(definida en CLAVE_DISPOSITIVO)' if os.environ.get('CLAVE_DISPOSITIVO') else CLAVE_DISPOSITIVO}")
    print("=" * 64)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")


if __name__ == "__main__":
    main()
