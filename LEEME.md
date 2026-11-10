# Localizador de cuidado · Grupo 7 · Tema 7 · ARC115 · versión en la nube

La app ya no depende de una computadora en la casa. Se entra desde cualquier celular o computadora con internet, y los avisos llegan como **notificaciones del navegador**, aunque la app esté cerrada.

```
 ESP32 (GPS + Wi-Fi + botón + buzzer)
      │  HTTPS cada 30 s, y al instante con SOS o cambio de perímetro
      ▼
 Render (servidor.py, gratis) ───────────▶ Firebase Realtime Database (los datos, gratis)
      │
      ├──▶ App web: https://<tu-app>.onrender.com (clave de acceso)
      └──▶ Notificaciones push a cada celular que dio permiso
 GitHub Actions lo visita cada 10 min para que no se duerma
```

## Qué cambió respecto a la versión local

| Pedido | Cómo quedó |
|---|---|
| El mapa muestra solo el GPS y el Wi-Fi | Dos marcas: el **GPS del dispositivo** y la **casa (Wi-Fi conectado)**. Ya no se dibuja el recorrido. |
| El mapa no se puede mover, pero siempre se puede abrir en Maps | Sin arrastre ni zoom. Tocar el mapa o "Abrir en Google Maps" siempre funciona: usa el GPS; sin GPS, la casa; sin ninguno, abre Maps. También hay un botón "Cómo llegar". |
| Perímetro por la intensidad del Wi-Fi, configurado al entrar | El límite se calibra en la app: "Fijar límite aquí" o uno de tres alcances. No se toca el código. |
| Que no sea local y que avise antes de entrar si el dispositivo está conectado | Está publicada en Render. La pantalla de entrada muestra el estado del dispositivo antes de pedir la clave. |
| Sin Telegram: solo pedir permiso de notificaciones | Se pidió permiso de notificaciones del navegador para emergencias, perímetro, pérdida de comunicación y rutinas. Cada encargado elige qué avisos recibe. |

### Cómo funciona el perímetro por Wi-Fi
- El ESP32 mide la señal del Wi-Fi (RSSI, en dBm) cada 2 s y promedia los últimos 8 valores, porque la señal varía sola.
- Si el promedio baja del límite, se avisa "Posible salida del perímetro" y suena la alarma. Para volver a "dentro", la señal tiene que subir 4 dB por encima del límite; eso evita que la alarma se active y desactive en el borde.
- Si se pierde el Wi-Fi del todo más de 30 s, el dispositivo suena por su cuenta, porque es probable que haya salido del alcance.
- En la app, la pérdida de comunicación se clasifica según la última señal recibida:
  - si ya estaba débil, cerca del límite: "posible salida de la casa";
  - si era buena: "puede estar apagado". Así se mantiene la regla del documento de no confundir desconexión con salida.

---

## Publicarla paso a paso (todo gratis, sin tarjeta)

### 1. GitHub
1. Crea un repositorio **público** (por ejemplo `localizador-g7`) y sube todo el contenido de esta carpeta. Tiene que ser público para que GitHub Actions sea gratis sin límite de minutos. No hay ninguna clave en los archivos.
2. **Nunca subas** el JSON de Firebase. El `.gitignore` ya lo excluye.

### 2. Firebase
1. Entra a [console.firebase.google.com](https://console.firebase.google.com) → **Agregar proyecto** (puedes desactivar Analytics).
2. **Compilación → Realtime Database → Crear base de datos** → elige una ubicación → **Comenzar en modo bloqueado**. El servidor entra como administrador, así que nadie más puede leer los datos.
3. Copia la URL de la base, por ejemplo `https://localizador-g7-default-rtdb.firebaseio.com`.
4. **⚙ Configuración del proyecto → Cuentas de servicio → Generar nueva clave privada**. Se descarga un archivo `.json`; guárdalo en un lugar seguro.

### 3. Render
1. Entra a [render.com](https://render.com) con tu cuenta de GitHub → **New → Blueprint** → elige el repositorio. Render lee `render.yaml`.
2. Llena las variables:
   - `FIREBASE_URL`: la URL del paso 2.3.
   - `FIREBASE_CUENTA_SERVICIO`: abre el `.json` con el Bloc de notas y pega **todo** su contenido.
   - `CLAVE_DISPOSITIVO`: inventa una, por ejemplo `G7-lampara-azul-2026`. La misma va en el firmware y se pide la primera vez que se entra a la app.
   - `CONTACTO_VAPID`: `mailto:` seguido del correo del grupo. Lo exigen los servicios de notificaciones.
3. **Apply**. Al terminar, Render muestra la dirección, por ejemplo `https://localizador-g7.onrender.com`.

### 4. Mantenerla despierta
En el repositorio de GitHub: **Settings → Secrets and variables → Actions → pestaña Variables → New variable**
- Nombre `URL_SERVIDOR`, valor la dirección de Render.
- Luego, en **Actions**, habilita los workflows. "Mantener despierto el servidor" corre cada 10 min.

### 5. Firmware
Abre `firmware/localizador_g7_nube/localizador_g7_nube.ino` y cambia `WIFI_SSID`, `WIFI_PASS`, `SERVIDOR` (la dirección de Render) y `CLAVE_DISPOSITIVO`. Cárgalo y mira el monitor serie: la autoprueba debe terminar con "App en nube .. OK". La primera vez puede tardar hasta un minuto si Render estaba dormido.

### 6. Primera entrada
1. Abre la dirección de Render. Escribe la clave del dispositivo, el nombre de la persona y una **clave de acceso** para los encargados.
2. El asistente pide, en orden:
   - **Notificaciones:** elige quién recibe en ese celular (familiar, doctor, cuidador) y qué avisos acepta, y toca **Permitir notificaciones**.
   - **Perímetro Wi-Fi:** con el dispositivo encendido, llévalo al borde de la zona segura (la puerta o el portón), espera unos 10 s a que se estabilice la señal y toca **Fijar límite aquí**. También puedes elegir "Solo la casa", "Casa y patio" o "Hasta la acera".
   - **Casa:** toca "Usar mi ubicación (estoy en la casa)", que pide permiso de ubicación al celular, o "Usar el GPS del dispositivo".
3. Cada encargado abre la misma dirección en su celular, entra con la clave y activa sus notificaciones en **Ajustes**.
   - **iPhone:** primero Compartir → **Agregar a inicio**, y abrir la app desde ese ícono. Requiere iOS 16.4 o más reciente.
   - **Android/Chrome:** funciona directo. También se puede instalar desde el menú → "Instalar app".

---

## Uso

| Dispositivo | Qué pasa |
|---|---|
| Hora de una rutina | Suena el buzzer y llega la notificación "Es hora de una rutina". |
| Pulsación corta | Confirma el recordatorio que suena; si no hay ninguno, envía **SOS**. |
| Pulsación larga (3 s) | Detiene la alarma. |
| La señal Wi-Fi baja del límite | Alarma de perímetro y notificación. |
| Se pierde el Wi-Fi más de 30 s | Alarma local. A los 90 s, la app avisa la pérdida de comunicación. |

En la app, **Ajustes** tiene:
- las notificaciones de ese celular y la lista de dispositivos que reciben avisos;
- el perímetro Wi-Fi, con un medidor en vivo que mide cada 3 s mientras está abierto;
- la ubicación de la casa;
- la persona y los tiempos;
- el cambio de clave;
- los datos de demostración.

## Probar en la computadora (sin Render)
```
cd servidor
pip install cryptography
python servidor.py            # datos en servidor/datos.json
python simulador.py --intervalo 5     # en otra terminal, hace de ESP32
```
Abre `http://localhost:8000`. La clave del dispositivo local es `G7-clave-local`. Comandos del simulador:
- `f`: alejarse; la señal baja.
- `d`: volver cerca del router.
- `s`: SOS.
- `c`: confirmar el recordatorio.
- `x`: apagar el Wi-Fi.
- `g`: perder el GPS.

Las notificaciones push necesitan HTTPS. En la computadora funcionan solo en `localhost` con Chrome o Edge; lo normal es probarlas ya en Render.

## Limitaciones a tener en cuenta
- **Render gratuito** se duerme tras 15 min sin visitas y tarda alrededor de 1 min en despertar. El ESP32 lo mantiene despierto mientras está encendido, y GitHub Actions cuando no lo está. GitHub puede retrasar ese aviso programado.
- **El RSSI no es una distancia exacta.** Cambia con paredes, puertas, el cuerpo de la persona y la orientación de la placa. Calibren con el dispositivo puesto como se usará y prueben caminando antes de la presentación.
- **Si el router se apaga o se reinicia,** el dispositivo hará sonar la alarma local de "sin Wi-Fi". Se silencia con una pulsación larga.
- **Las notificaciones** dependen del navegador y del sistema. El ahorro de batería de algunos Android puede retrasarlas.
- **Fuera de la casa, sin Wi-Fi,** el dispositivo no puede enviar su posición, porque no tiene datos móviles. La app muestra la última posición conocida.

## Cómo cubre los requisitos
| Requisito | Dónde |
|---|---|
| Geolocalización | GPS en el mapa y en cada alerta, con enlace a Google Maps |
| Alarma por abandono de perímetro | Señal Wi-Fi bajo el límite calibrado, más alarma local por pérdida de Wi-Fi |
| Alarmas de medicamentos, aseo y caminatas | Rutinas con hora y días: buzzer, notificación y confirmación con el botón |
| Enviar la información a doctor, familiar u otro | Notificaciones push con etiqueta y tipos de aviso por cada celular |
| Presencia cada 30 s; 90 s sin señal = desconexión | Firmware y Ajustes; no se confunde con salida |
| Recuperación con señales consecutivas | 2 presencias seguidas |
| Sin hora válida no se marca como cumplido | La hora la pone el servidor (UTC−6); si no estaba activo, queda "Sin registro" |
| Clave local de la placa | Cabecera `X-Clave` = `CLAVE_DISPOSITIVO` |
| Acceso a la información | Clave de acceso para los encargados; datos cerrados en Firebase |
