# -*- coding: utf-8 -*-
"""
Almacén de datos. Todo vive en memoria para responder rápido y cada cambio se
copia en segundo plano a:
  - Firebase Realtime Database (en la nube), si están las variables FIREBASE_URL y
    FIREBASE_CUENTA_SERVICIO (o FIREBASE_SECRETO), o
  - un archivo local datos.json, para probar en la computadora.
El servidor es el único que escribe, así que la copia en memoria siempre manda.
"""
import base64
import copy
import json
import os
import queue
import threading
import time
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def _partes(ruta):
    return [p for p in ruta.strip("/").split("/") if p]


class Almacen:
    def __init__(self):
        self.datos = {}
        self.lock = threading.RLock()
        self.cola = queue.Queue()
        self.ultimo_error = None

    # ---------------- lectura y escritura en memoria
    def obtener(self, ruta="", defecto=None):
        with self.lock:
            nodo = self.datos
            for p in _partes(ruta):
                if not isinstance(nodo, dict) or p not in nodo:
                    return defecto
                nodo = nodo[p]
            return copy.deepcopy(nodo)

    def _nodo_padre(self, ruta, crear=True):
        partes = _partes(ruta)
        nodo = self.datos
        for p in partes[:-1]:
            if not isinstance(nodo.get(p), dict):
                if not crear:
                    return None, partes[-1]
                nodo[p] = {}
            nodo = nodo[p]
        return nodo, partes[-1]

    def poner(self, ruta, valor):
        with self.lock:
            padre, clave = self._nodo_padre(ruta)
            if valor is None:
                padre.pop(clave, None)
            else:
                padre[clave] = copy.deepcopy(valor)
            self.cola.put(("PUT" if valor is not None else "DELETE", ruta, valor))

    def actualizar(self, ruta, cambios):
        with self.lock:
            partes = _partes(ruta)
            nodo = self.datos
            for p in partes:
                if not isinstance(nodo.get(p), dict):
                    nodo[p] = {}
                nodo = nodo[p]
            for k, v in cambios.items():
                if v is None:
                    nodo.pop(k, None)
                else:
                    nodo[k] = copy.deepcopy(v)
            self.cola.put(("PATCH", ruta, cambios))

    def borrar(self, ruta):
        self.poner(ruta, None)

    # ---------------- persistencia
    def iniciar(self):
        self.cargar()
        threading.Thread(target=self._trabajador, daemon=True).start()

    def cargar(self):
        raise NotImplementedError

    def _trabajador(self):
        raise NotImplementedError

    def descripcion(self):
        return ""


class AlmacenLocal(Almacen):
    def __init__(self, archivo):
        super().__init__()
        self.archivo = archivo

    def descripcion(self):
        return f"archivo local {self.archivo}"

    def cargar(self):
        if os.path.exists(self.archivo):
            with open(self.archivo, encoding="utf-8") as f:
                self.datos = json.load(f)

    def _trabajador(self):
        while True:
            self.cola.get()
            time.sleep(1.0)          # agrupa varios cambios en una sola escritura
            while not self.cola.empty():
                self.cola.get_nowait()
            with self.lock:
                texto = json.dumps(self.datos, ensure_ascii=False)
            tmp = self.archivo + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(texto)
            os.replace(tmp, self.archivo)


class AlmacenFirebase(Almacen):
    def __init__(self, url, cuenta_servicio=None, secreto=None):
        super().__init__()
        self.url = url.rstrip("/")
        self.cuenta = cuenta_servicio
        self.secreto = secreto
        self._token = None
        self._vence = 0

    def descripcion(self):
        return f"Firebase {self.url}"

    # Acceso como administrador: con la cuenta de servicio se pide un token OAuth.
    def _auth(self):
        if self.secreto:
            return {"auth": self.secreto}
        if time.time() > self._vence - 120:
            ahora = int(time.time())
            enc = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=")
            datos = base64.urlsafe_b64encode(json.dumps({
                "iss": self.cuenta["client_email"],
                "scope": "https://www.googleapis.com/auth/firebase.database https://www.googleapis.com/auth/userinfo.email",
                "aud": "https://oauth2.googleapis.com/token", "iat": ahora, "exp": ahora + 3600,
            }).encode()).rstrip(b"=")
            mensaje = enc + b"." + datos
            clave = serialization.load_pem_private_key(self.cuenta["private_key"].encode(), None)
            firma = base64.urlsafe_b64encode(clave.sign(mensaje, padding.PKCS1v15(), hashes.SHA256())).rstrip(b"=")
            cuerpo = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                             "assertion": (mensaje + b"." + firma).decode()}).encode()
            with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=cuerpo),
                                        timeout=15) as r:
                resp = json.loads(r.read())
            self._token = resp["access_token"]
            self._vence = time.time() + int(resp.get("expires_in", 3600))
        return {"access_token": self._token}

    def _peticion(self, metodo, ruta, valor=None):
        url = f"{self.url}/{ruta.strip('/')}.json?" + urllib.parse.urlencode(self._auth())
        datos = None if valor is None else json.dumps(valor, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=datos, method=metodo, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"null")

    def cargar(self):
        self.datos = self._peticion("GET", "") or {}

    def _trabajador(self):
        while True:
            metodo, ruta, valor = self.cola.get()
            for intento in range(5):
                try:
                    self._peticion(metodo, ruta, valor)
                    self.ultimo_error = None
                    break
                except Exception as e:  # noqa: BLE001
                    self.ultimo_error = f"{e.__class__.__name__}: {e}"
                    print(f"[Firebase] error al guardar {ruta} (intento {intento + 1}): {self.ultimo_error}")
                    time.sleep(2 * (intento + 1))


def crear_almacen(carpeta_base):
    url = os.environ.get("FIREBASE_URL", "").strip()
    if url:
        secreto = os.environ.get("FIREBASE_SECRETO", "").strip() or None
        cuenta = None
        texto = os.environ.get("FIREBASE_CUENTA_SERVICIO", "").strip()
        if texto:
            if not texto.startswith("{"):
                if os.path.isfile(texto):
                    with open(texto, encoding="utf-8") as f:
                        texto = f.read()
                else:
                    texto = base64.b64decode(texto).decode("utf-8")
            cuenta = json.loads(texto)
        if not (cuenta or secreto):
            raise SystemExit("Falta FIREBASE_CUENTA_SERVICIO (o FIREBASE_SECRETO) junto a FIREBASE_URL.")
        return AlmacenFirebase(url, cuenta, secreto)
    return AlmacenLocal(os.path.join(carpeta_base, "datos.json"))
