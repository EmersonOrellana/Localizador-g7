#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulador del prototipo · Grupo 7
Se comporta como el ESP32: envía presencia, señal Wi-Fi y posición al servidor
(local o en Render) y responde a los recordatorios. Las posiciones se marcan
como simuladas en la app.

    python simulador.py                                   # servidor local
    python simulador.py --servidor https://tu-app.onrender.com --clave TU_CLAVE

Comandos (letra + Enter):
    s  botón de pánico (SOS)          c  confirmar el recordatorio que suena
    f  alejarse (la señal Wi-Fi baja)  d  volver cerca del router
    g  perder / recuperar el GPS      x  apagar / encender el Wi-Fi (desconexión)
    q  salir
"""
import argparse
import json
import math
import random
import threading
import time
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--servidor", default="http://localhost:8000")
ap.add_argument("--clave", default="G7-clave-local")
ap.add_argument("--intervalo", type=float, default=30, help="segundos entre presencias (el diseño usa 30)")
ap.add_argument("--lat", type=float, default=13.7186)
ap.add_argument("--lng", type=float, default=-89.2009)
ap.add_argument("--ssid", default="CasaGrupo7")
args = ap.parse_args()

est = {"lejos": False, "gps": True, "wifi": True, "eventos": [], "recordatorio": "0", "paso": 0, "rapido": False,
       "rssi": -58.0}
lock = threading.Lock()


def medir():
    est["paso"] += 1
    objetivo = -86 if est["lejos"] else -58
    est["rssi"] += (objetivo - est["rssi"]) * 0.35 + random.uniform(-1.5, 1.5)   # cambia de a poco, como al caminar
    dist = 60 if est["lejos"] else 8
    ang = est["paso"] * 0.4
    lat = args.lat + dist * math.cos(ang) / 111320
    lng = args.lng + dist * math.sin(ang) / (111320 * math.cos(math.radians(args.lat)))
    return lat, lng


def enviar():
    with lock:
        lat, lng = medir()
        cuerpo = {"id": "SIM-01", "fix": est["gps"], "lat": lat, "lng": lng, "sats": random.randint(6, 10) if est["gps"] else 0,
                  "hdop": 1.1, "rssi": round(est["rssi"]), "ssid": args.ssid, "sim": True, "eventos": est["eventos"][:]}
    req = urllib.request.Request(args.servidor.rstrip("/") + "/api/dispositivo", data=json.dumps(cuerpo).encode(),
                                 headers={"Content-Type": "application/json", "X-Clave": args.clave})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            texto = r.read().decode("utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"  [sin respuesta: {e}]")
        return
    with lock:
        est["eventos"] = [e for e in est["eventos"] if e not in cuerpo["eventos"]]
        resp = dict(l.split("=", 1) for l in texto.strip().splitlines() if "=" in l)
        rec = resp.get("recordatorio", "0")
        rid = rec.split("|")[0]
        if rid != "0" and rid != est["recordatorio"]:
            print(f"\n  ♪ BUZZER: recordatorio «{rec.split('|', 1)[1]}» · escribe c para confirmar")
        est["recordatorio"] = rid
        est["rapido"] = resp.get("rapido") == "1"
        if resp.get("perimetro") == "fuera" and resp.get("silenciado") == "0":
            print("  ♪ BUZZER: alarma de perímetro (señal Wi-Fi bajo el límite)")
        if resp.get("buscar") == "1":
            print("  ♪ BUZZER: la app pidió hacer sonar el dispositivo")
        if resp.get("detener") == "1":
            print("  · Ayuda atendida desde la app: alarma detenida")
    print(f"[{resp.get('hora')}] Wi-Fi {cuerpo['rssi']} dBm (límite {resp.get('umbral')}) · perímetro {resp.get('perimetro')}"
          f"{' · calibrando' if est['rapido'] else ''}")


def bucle():
    while True:
        if est["wifi"]:
            enviar()
        espera = 3 if est["rapido"] else args.intervalo
        t0 = time.time()
        while time.time() - t0 < espera:
            time.sleep(0.2)
            if est["eventos"] and est["wifi"]:
                break


print(__doc__.split("Comandos")[1].replace("(letra + Enter):", "Comandos:"))
threading.Thread(target=bucle, daemon=True).start()
while True:
    try:
        c = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        break
    with lock:
        if c == "s":
            est["eventos"].append("sos"); print("  → SOS")
        elif c == "c":
            if est["recordatorio"] != "0":
                est["eventos"].append(f"confirmar:{est['recordatorio']}"); print("  → confirmación enviada")
            else:
                print("  No hay recordatorio sonando.")
        elif c == "f":
            est["lejos"] = True; print("  → alejándose del router: la señal bajará en las próximas presencias")
        elif c == "d":
            est["lejos"] = False; print("  → volviendo cerca del router")
        elif c == "g":
            est["gps"] = not est["gps"]; print("  → GPS", "con señal" if est["gps"] else "sin señal")
        elif c == "x":
            est["wifi"] = not est["wifi"]; print("  → Wi-Fi", "encendido" if est["wifi"] else "apagado")
        elif c == "q":
            break
