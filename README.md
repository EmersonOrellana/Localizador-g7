# Localizador de cuidado · Grupo 7 · Tema 7 · ARC115 · versión en la nube

La app ya no depende de una computadora en la casa. Se entra desde cualquier celular o computadora con internet, y los avisos llegan como **notificaciones del navegador**, aunque la app esté cerrada.

```
 ESP32 (GPS + Wi-Fi + botón + buzzer)
      │  HTTPS cada 30 s, y al instante con SOS o cambio de perímetro
      ▼
 Render (servidor.py, gratis) ───────────▶ Firebase Realtime Database (los datos, gratis)
      │
      ├──▶ App web: https://localizador-g7.onrender.com/ (clave de acceso)
      └──▶ Notificaciones push a cada celular que dio permiso
 GitHub Actions lo visita cada 10 min para que no se duerma
```

### Cómo funciona el perímetro por Wi-Fi
- El ESP32 mide la señal del Wi-Fi (RSSI, en dBm) cada 2 s y promedia los últimos 8 valores, porque la señal varía sola.
- Si el promedio baja del límite, se avisa "Posible salida del perímetro" y suena la alarma. Para volver a "dentro", la señal tiene que subir 4 dB por encima del límite; eso evita que la alarma se active y desactive en el borde.
- Si se pierde el Wi-Fi del todo más de 30 s, el dispositivo suena por su cuenta, porque es probable que haya salido del alcance.
- En la app, la pérdida de comunicación se clasifica según la última señal recibida:
  - si ya estaba débil, cerca del límite: "posible salida de la casa";
  - si era buena: "puede estar apagado". Así se mantiene la regla del documento de no confundir desconexión con salida.

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
