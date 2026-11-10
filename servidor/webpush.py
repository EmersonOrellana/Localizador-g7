# -*- coding: utf-8 -*-
"""
Notificaciones Web Push sin servicios externos de terceros.
Implementa el cifrado aes128gcm (RFC 8291 / RFC 8188) y la firma VAPID (RFC 8292).
Solo necesita la librería `cryptography`.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def b64u(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def b64ud(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _hkdf(salt, ikm, info, largo):
    return HKDF(algorithm=hashes.SHA256(), length=largo, salt=salt, info=info).derive(ikm)


def generar_claves_vapid():
    """Devuelve (privada_pem, publica_b64u) para guardar en la base de datos."""
    privada = ec.generate_private_key(ec.SECP256R1())
    pem = privada.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    return pem, clave_publica(pem)


def clave_publica(privada_pem: str) -> str:
    privada = serialization.load_pem_private_key(privada_pem.encode(), None)
    pub = privada.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64u(pub)


def cifrar(mensaje: bytes, p256dh: str, auth: str, salt: bytes = None, privada_temporal=None) -> bytes:
    """Cifra el mensaje para una suscripción (formato aes128gcm de un solo registro)."""
    ua_pub = b64ud(p256dh)
    secreto_auth = b64ud(auth)
    as_priv = privada_temporal or ec.generate_private_key(ec.SECP256R1())
    as_pub = as_priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    ua_clave = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub)
    compartido = as_priv.exchange(ec.ECDH(), ua_clave)
    ikm = _hkdf(secreto_auth, compartido, b"WebPush: info\x00" + ua_pub + as_pub, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    cifrado = AESGCM(cek).encrypt(nonce, mensaje + b"\x02", None)
    rs = 4096
    return salt + rs.to_bytes(4, "big") + bytes([len(as_pub)]) + as_pub + cifrado


def descifrar(cuerpo: bytes, ua_privada, auth: str) -> bytes:
    """Solo para pruebas: hace lo que haría el navegador."""
    salt, idlen = cuerpo[:16], cuerpo[20]
    as_pub = cuerpo[21:21 + idlen]
    datos = cuerpo[21 + idlen:]
    ua_pub = ua_privada.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    compartido = ua_privada.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = _hkdf(b64ud(auth), compartido, b"WebPush: info\x00" + ua_pub + as_pub, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plano = AESGCM(cek).decrypt(nonce, datos, None)
    return plano.rstrip(b"\x00")[:-1]


def jwt_vapid(endpoint: str, privada_pem: str, contacto: str) -> str:
    u = urllib.parse.urlparse(endpoint)
    encabezado = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    datos = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600,
                             "sub": contacto}, separators=(",", ":")).encode())
    mensaje = f"{encabezado}.{datos}".encode()
    privada = serialization.load_pem_private_key(privada_pem.encode(), None)
    r, s = decode_dss_signature(privada.sign(mensaje, ec.ECDSA(hashes.SHA256())))
    firma = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{encabezado}.{datos}.{b64u(firma)}"


def enviar(suscripcion: dict, carga: dict, privada_pem: str, contacto: str, urgencia="normal", ttl=86400):
    """Envía una notificación. Devuelve (codigo_http, detalle). 404/410 = suscripción vencida."""
    cuerpo = cifrar(json.dumps(carga, ensure_ascii=False).encode("utf-8"), suscripcion["p256dh"], suscripcion["auth"])
    endpoint = suscripcion["endpoint"]
    req = urllib.request.Request(endpoint, data=cuerpo, method="POST", headers={
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Urgency": urgencia,
        "Authorization": f"vapid t={jwt_vapid(endpoint, privada_pem, contacto)}, k={clave_publica(privada_pem)}",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, "enviado"
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200].decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, e.__class__.__name__
