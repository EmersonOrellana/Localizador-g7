/*
  ================================================================
  Localizador GPS para personas con Alzheimer · Grupo 7 · Tema 7 · ARC115
  Firmware para la app en la nube (Render + Firebase)
  ================================================================

  HARDWARE
    GPS NEO-6M  TX -> GPIO16 (RX2)   RX -> GPIO17 (TX2)   VCC -> 3V3   GND -> GND
    Pulsador    GPIO18 y GND (patas en diagonal, pull-up interno)
    Buzzer      S -> GPIO19   + -> 3V3   - -> GND

  LIBRERÍA: TinyGPSPlus (Mikal Hart). Lo demás viene con el soporte de ESP32.

  PERÍMETRO POR SEÑAL WI-FI
    El perímetro NO se configura aquí: se calibra desde la app (Ajustes o al
    configurar por primera vez). El servidor manda el límite en dBm y el ESP32:
      - mide la señal del Wi-Fi cada 2 s y usa el promedio de los últimos 8 valores,
      - si el promedio baja del límite, suena la alarma y avisa de inmediato,
      - si pierde el Wi-Fi por completo más de 30 s, suena la alarma local
        (probablemente salió del alcance de la casa).

  BOTÓN
    Corta: confirma el recordatorio que suena; si no hay ninguno, envía SOS.
    Larga (3 s): detiene la alarma que esté sonando.

  MONITOR SERIE 115200 ("Nueva línea"):
    t autoprueba · s SOS · c confirmar · x detener alarma · e estado
    g NMEA crudo · p LAT LNG simular posición (p solo = GPS real) · h ayuda
*/

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <TinyGPSPlus.h>

// ===================== CONFIGURACIÓN =====================
const char* WIFI_SSID = "TU_RED_WIFI";
const char* WIFI_PASS = "TU_CLAVE";
// Dirección de la app en Render (sin "/" al final). En Ajustes de la app aparece.
const char* SERVIDOR = "https://localizador-g7.onrender.com";
const char* CLAVE_DISPOSITIVO = "LA_MISMA_DE_RENDER";   // variable CLAVE_DISPOSITIVO en Render
const char* ID_DISPOSITIVO = "G7-01";

#define PIN_GPS_RX 16
#define PIN_GPS_TX 17
#define PIN_BOTON  18
#define PIN_BUZZER 19

const bool BUZZER_PASIVO       = false;  // true si solo suena con tone()
const bool BUZZER_SUENA_EN_LOW = false;  // true si tu módulo suena con LOW

const unsigned long INTERVALO_PRESENCIA_MS = 30000;  // diseño: 30 s
const unsigned long INTERVALO_RAPIDO_MS    = 3000;   // durante la calibración desde la app
const unsigned long SIN_WIFI_ALARMA_MS     = 30000;  // sin Wi-Fi este tiempo = alarma local
const unsigned long PULSACION_LARGA_MS     = 3000;
const int HISTERESIS_DB = 4;
// ==========================================================

TinyGPSPlus gps;
HardwareSerial gpsSerial(2);

bool verNMEA = false, simActiva = false;
double simLat = 0, simLng = 0;

// Señal Wi-Fi promediada
const int N_RSSI = 8;
int rssiMuestras[N_RSSI];
int rssiN = 0, rssiPos = 0;
float rssiProm = 0;
unsigned long wifiPerdidoDesde = 0;

// Lo que dice el servidor
bool servidorOk = false;
unsigned long ultimaRespuesta = 0;
String horaServidor = "--:--:--";
int umbral = 0;                       // 0 = perímetro sin calibrar
String perimetroServidor = "sin_dato";
bool silenciadoServidor = false, modoRapido = false;
String recordatorioId = "0", recordatorioTitulo = "", recordatorioConfirmadoLocal = "";

// Alarmas locales
unsigned long sosHasta = 0, buscarHasta = 0;
bool fueraLocal = false, silenciadoLocal = false;

// Eventos pendientes
bool pendSOS = false, pendCancelar = false;
String pendConfirmar = "";
unsigned long ultimoEnvio = 0, proximoIntento = 0;

bool servidorReciente();

// ---------------------------------------------------------------
//  BUZZER no bloqueante
// ---------------------------------------------------------------
const uint16_t P_CORTO[]  = {80};
const uint16_t P_OK[]     = {80, 80, 80};
const uint16_t P_ERROR[]  = {700};
const uint16_t P_SOS[]    = {150,100,150,100,150,300, 400,100,400,100,400,300, 150,100,150,100,150,1000};
const uint16_t P_ZONA[]   = {600, 400};
const uint16_t P_RECORD[] = {250,120,250,120,250,2500};
const uint16_t P_BUSCAR[] = {100, 100};

enum Sonido { NINGUNO, S_SOS, S_ZONA, S_RECORD, S_BUSCAR, S_AVISO };
Sonido sonidoActual = NINGUNO;
const uint16_t* patPasos = nullptr;
uint8_t patN = 0, patIdx = 0;
bool patRepetir = false;
unsigned long patT = 0;

void buzzerOn()  { if (BUZZER_PASIVO) tone(PIN_BUZZER, 2200); else digitalWrite(PIN_BUZZER, BUZZER_SUENA_EN_LOW ? LOW : HIGH); }
void buzzerOff() { if (BUZZER_PASIVO) noTone(PIN_BUZZER);     else digitalWrite(PIN_BUZZER, BUZZER_SUENA_EN_LOW ? HIGH : LOW); }
void sonar(const uint16_t* p, uint8_t n, bool rep) { patPasos = p; patN = n; patIdx = 0; patRepetir = rep; patT = millis(); buzzerOn(); }
#define SONAR(p, rep) sonar(p, sizeof(p) / sizeof(p[0]), rep)
void callar() { patPasos = nullptr; buzzerOff(); }

void actualizarBuzzer() {
  if (!patPasos) return;
  if (millis() - patT >= patPasos[patIdx]) {
    patT = millis();
    if (++patIdx >= patN) {
      if (!patRepetir) { callar(); if (sonidoActual == S_AVISO) sonidoActual = NINGUNO; return; }
      patIdx = 0;
    }
    if (patIdx % 2 == 0) buzzerOn(); else buzzerOff();
  }
}
void aviso(const uint16_t* p, uint8_t n) { if (sonidoActual == NINGUNO || sonidoActual == S_AVISO) { sonidoActual = S_AVISO; sonar(p, n, false); } }
#define AVISO(p) aviso(p, sizeof(p) / sizeof(p[0]))

bool fueraDelPerimetro() {
  // Sin Wi-Fi mucho tiempo: probablemente salió del alcance de la casa
  if (wifiPerdidoDesde && millis() - wifiPerdidoDesde > SIN_WIFI_ALARMA_MS && umbral != 0) return true;
  if (servidorReciente()) return perimetroServidor == "fuera" && !silenciadoServidor;
  return fueraLocal;
}

void decidirSonido() {
  unsigned long now = millis();
  Sonido quiero = NINGUNO;
  if (sosHasta && (long)(sosHasta - now) > 0) quiero = S_SOS;
  else if (fueraDelPerimetro() && !silenciadoLocal) quiero = S_ZONA;
  else if (recordatorioId != "0" && recordatorioId != recordatorioConfirmadoLocal) quiero = S_RECORD;
  else if (buscarHasta && (long)(buscarHasta - now) > 0) quiero = S_BUSCAR;
  if (quiero == sonidoActual) return;
  if (quiero == NINGUNO && sonidoActual == S_AVISO) return;
  sonidoActual = quiero;
  switch (quiero) {
    case S_SOS:    SONAR(P_SOS, true); break;
    case S_ZONA:   SONAR(P_ZONA, true); break;
    case S_RECORD: SONAR(P_RECORD, true); break;
    case S_BUSCAR: SONAR(P_BUSCAR, true); break;
    default:       callar();
  }
}

// ---------------------------------------------------------------
//  GPS
// ---------------------------------------------------------------
void alimentarGPS() {
  while (gpsSerial.available()) { char c = gpsSerial.read(); if (verNMEA) Serial.write(c); gps.encode(c); }
}
bool hayFixReal() { return gps.location.isValid() && gps.location.age() < 5000; }
bool posicionActual(double &lat, double &lng) {
  if (simActiva) { lat = simLat; lng = simLng; return true; }
  if (hayFixReal()) { lat = gps.location.lat(); lng = gps.location.lng(); return true; }
  return false;
}
void esperar(unsigned long ms) { unsigned long t0 = millis(); while (millis() - t0 < ms) { alimentarGPS(); delay(2); } }
bool servidorReciente() { return servidorOk && millis() - ultimaRespuesta < INTERVALO_PRESENCIA_MS * 2 + 10000; }

// ---------------------------------------------------------------
//  SEÑAL WI-FI (perímetro)
// ---------------------------------------------------------------
void medirWiFi() {
  if (WiFi.status() != WL_CONNECTED) {
    if (!wifiPerdidoDesde) { wifiPerdidoDesde = millis(); Serial.println("[Wi-Fi] Se perdió la conexión."); }
    rssiN = 0; rssiPos = 0;
    return;
  }
  if (wifiPerdidoDesde) { Serial.println("[Wi-Fi] Conectado de nuevo."); wifiPerdidoDesde = 0; silenciadoLocal = false; }
  rssiMuestras[rssiPos] = WiFi.RSSI();
  rssiPos = (rssiPos + 1) % N_RSSI;
  if (rssiN < N_RSSI) rssiN++;
  long suma = 0;
  for (int i = 0; i < rssiN; i++) suma += rssiMuestras[i];
  rssiProm = (float)suma / rssiN;

  if (umbral == 0) { fueraLocal = false; return; }
  bool antes = fueraLocal;
  if (!fueraLocal && rssiProm < umbral) fueraLocal = true;
  else if (fueraLocal && rssiProm >= umbral + HISTERESIS_DB) { fueraLocal = false; silenciadoLocal = false; }
  if (antes != fueraLocal) {
    Serial.printf("[Perímetro] %s (señal %.0f dBm, límite %d)\n", fueraLocal ? "Fuera" : "Dentro", rssiProm, umbral);
    proximoIntento = 0;
    ultimoEnvio = 0;          // avisar al servidor ya
  }
}

// ---------------------------------------------------------------
//  COMUNICACIÓN CON EL SERVIDOR (HTTPS)
// ---------------------------------------------------------------
void conectarWiFi(bool esperarConexion) {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  if (!esperarConexion) return;
  Serial.printf("  Conectando a \"%s\"", WIFI_SSID);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) { esperar(300); Serial.print("."); }
  Serial.println();
}

String valor(const String& resp, const char* clave) {
  String k = String(clave) + "=";
  int i = resp.indexOf(k);
  if (i < 0) return String("");
  int f = resp.indexOf('\n', i);
  return resp.substring(i + k.length(), f < 0 ? resp.length() : f);
}

bool enviarPresencia() {
  if (WiFi.status() != WL_CONNECTED) { servidorOk = false; return false; }
  double lat = 0, lng = 0;
  bool fix = posicionActual(lat, lng);
  String eventos = "";
  if (pendSOS) eventos += "\"sos\"";
  if (pendConfirmar.length()) { if (eventos.length()) eventos += ","; eventos += "\"confirmar:"; eventos += pendConfirmar; eventos += "\""; }
  if (pendCancelar) { if (eventos.length()) eventos += ","; eventos += "\"cancelar\""; }

  char json[420];
  snprintf(json, sizeof(json),
    "{\"id\":\"%s\",\"fix\":%s,\"lat\":%.6f,\"lng\":%.6f,\"sats\":%u,\"hdop\":%.1f,\"rssi\":%.0f,\"ssid\":\"%s\",\"sim\":%s,\"eventos\":[%s]}",
    ID_DISPOSITIVO, fix ? "true" : "false", lat, lng,
    (unsigned)(gps.satellites.isValid() ? gps.satellites.value() : 0), gps.hdop.isValid() ? gps.hdop.hdop() : 0.0,
    rssiN ? rssiProm : (float)WiFi.RSSI(), WiFi.SSID().c_str(), simActiva ? "true" : "false", eventos.c_str());

  WiFiClientSecure cliente;
  cliente.setInsecure();               // suficiente para el prototipo
  HTTPClient http;
  http.begin(cliente, String(SERVIDOR) + "/api/dispositivo");
  http.setTimeout(20000);              // el servidor gratuito puede tardar en despertar
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Clave", CLAVE_DISPOSITIVO);
  int codigo = http.POST((uint8_t*)json, strlen(json));
  String resp = codigo > 0 ? http.getString() : String("");
  http.end();

  if (codigo == 401) { Serial.println("[Servidor] Clave incorrecta: revisa CLAVE_DISPOSITIVO."); servidorOk = false; return false; }
  if (codigo != 200) { Serial.printf("[Servidor] Sin respuesta (%d). Revisa SERVIDOR o espera a que despierte.\n", codigo); servidorOk = false; return false; }

  pendSOS = false; pendConfirmar = ""; pendCancelar = false;
  servidorOk = true;
  ultimaRespuesta = millis();
  horaServidor = valor(resp, "hora");
  umbral = valor(resp, "umbral").toInt();
  String per = valor(resp, "perimetro");
  if (per == "dentro") silenciadoLocal = false;
  perimetroServidor = per;
  silenciadoServidor = valor(resp, "silenciado") == "1";
  modoRapido = valor(resp, "rapido") == "1";

  String r = valor(resp, "recordatorio");
  int barra = r.indexOf('|');
  String nuevoId = barra > 0 ? r.substring(0, barra) : String("0");
  if (nuevoId != "0" && nuevoId != recordatorioId) {
    recordatorioTitulo = r.substring(barra + 1);
    Serial.print("[Recordatorio] "); Serial.print(recordatorioTitulo); Serial.println(" · presiona el botón para confirmar.");
  }
  recordatorioId = nuevoId;
  if (recordatorioId == "0") recordatorioConfirmadoLocal = "";
  if (valor(resp, "buscar") == "1") { buscarHasta = millis() + 10000; Serial.println("[App] Hacer sonar 10 s."); }
  if (valor(resp, "detener") == "1") { sosHasta = 0; Serial.println("[App] Ayuda atendida: alarma detenida."); }
  return true;
}

// ---------------------------------------------------------------
//  BOTÓN
// ---------------------------------------------------------------
void activarSOS() {
  pendSOS = true; sosHasta = millis() + 20000;
  Serial.println("\n[SOS] Botón de pánico. Enviando...");
  decidirSonido(); proximoIntento = 0;
}
void confirmarRecordatorio() {
  pendConfirmar = recordatorioId; recordatorioConfirmadoLocal = recordatorioId;
  Serial.print("[Recordatorio] Confirmado: "); Serial.println(recordatorioTitulo);
  decidirSonido(); AVISO(P_OK); proximoIntento = 0;
}
void detenerAlarmas() {
  sosHasta = 0; buscarHasta = 0; silenciadoLocal = true; pendCancelar = true;
  Serial.println("[Alarma] Detenida desde el dispositivo.");
  decidirSonido(); AVISO(P_CORTO); proximoIntento = 0;
}
void pulsacionCorta() {
  if (recordatorioId != "0" && recordatorioId != recordatorioConfirmadoLocal) confirmarRecordatorio();
  else activarSOS();
}
bool btnLectura = HIGH, btnEstable = HIGH, btnLargo = false;
unsigned long btnCambio = 0, btnDesde = 0;
void leerBoton() {
  bool l = digitalRead(PIN_BOTON);
  if (l != btnLectura) { btnLectura = l; btnCambio = millis(); }
  if (millis() - btnCambio > 30 && l != btnEstable) {
    btnEstable = l;
    if (btnEstable == LOW) { btnDesde = millis(); btnLargo = false; }
    else if (!btnLargo) pulsacionCorta();
  }
  if (btnEstable == LOW && !btnLargo && millis() - btnDesde >= PULSACION_LARGA_MS) { btnLargo = true; detenerAlarmas(); }
}

// ---------------------------------------------------------------
//  AUTOPRUEBA
// ---------------------------------------------------------------
void autoprueba() {
  bool okBoton = false, okGPS = false, okWiFi = false, okServ = false;
  Serial.println("\n================ AUTOPRUEBA ================");
  Serial.println("[1/5] BUZZER: deben sonar 3 pitidos.");
  callar(); sonidoActual = NINGUNO;
  for (int i = 0; i < 3; i++) { buzzerOn(); esperar(120); buzzerOff(); esperar(150); }

  Serial.println("[2/5] PULSADOR: presiónalo en los próximos 10 s...");
  if (digitalRead(PIN_BOTON) == LOW) Serial.println("  X: se lee presionado sin tocarlo. Revisa patas en diagonal y que no esté en GPIO2.");
  else {
    unsigned long t0 = millis();
    while (millis() - t0 < 10000) { alimentarGPS(); if (digitalRead(PIN_BOTON) == LOW) { okBoton = true; break; } delay(5); }
    if (okBoton) { buzzerOn(); esperar(60); buzzerOff(); Serial.println("  OK"); while (digitalRead(PIN_BOTON) == LOW) esperar(10); }
    else Serial.println("  X: no se detectó. Revisa GPIO18 y que la otra pata vaya a GND.");
    btnEstable = btnLectura = HIGH;
  }

  Serial.println("[3/5] GPS: escuchando 5 s...");
  uint32_t ok0 = gps.passedChecksum(), c0 = gps.charsProcessed();
  esperar(5000);
  uint32_t ok = gps.passedChecksum() - ok0, chars = gps.charsProcessed() - c0;
  okGPS = ok > 0;
  if (chars == 0) Serial.println("  X: no llegan datos. Revisa GPS TX -> GPIO16, GND y VCC.");
  else if (!okGPS) Serial.println("  X: datos ilegibles. Revisa la velocidad (9600) y los cables.");
  else Serial.printf("  OK: %u frases · %u satélites · %s\n", (unsigned)ok, (unsigned)(gps.satellites.isValid() ? gps.satellites.value() : 0),
                     hayFixReal() ? "con posición" : "sin posición aún (normal bajo techo)");

  Serial.println("[4/5] WI-FI:");
  conectarWiFi(true);
  okWiFi = WiFi.status() == WL_CONNECTED;
  if (okWiFi) { Serial.print("  OK: "); Serial.print(WiFi.SSID()); Serial.printf(" · señal %d dBm\n", (int)WiFi.RSSI()); medirWiFi(); }
  else Serial.println("  X: no se conectó. Revisa WIFI_SSID y WIFI_PASS (solo 2.4 GHz).");

  Serial.println("[5/5] SERVIDOR EN LA NUBE (puede tardar hasta 1 min si estaba dormido):");
  for (int i = 0; okWiFi && i < 3 && !okServ; i++) { okServ = enviarPresencia(); if (!okServ) esperar(5000); }
  if (okServ) {
    Serial.print("  OK · hora "); Serial.print(horaServidor);
    if (umbral) Serial.printf(" · límite del perímetro %d dBm\n", umbral); else Serial.println(" · perímetro sin calibrar: hazlo en la app");
  }

  Serial.println("---------------- RESUMEN ----------------");
  Serial.println("  Buzzer ....... confirma con tu oído");
  Serial.printf("  Pulsador ..... %s\n", okBoton ? "OK" : "FALLA");
  Serial.printf("  GPS .......... %s\n", okGPS ? "OK" : "FALLA");
  Serial.printf("  Wi-Fi ........ %s\n", okWiFi ? "OK" : "FALLA");
  Serial.printf("  App en nube .. %s\n", okServ ? "OK" : "FALLA");
  Serial.println("==========================================");
  ultimoEnvio = millis();
  if (okBoton && okGPS && okServ) AVISO(P_OK); else { sonidoActual = S_AVISO; SONAR(P_ERROR, false); }
}

// ---------------------------------------------------------------
//  MONITOR SERIE
// ---------------------------------------------------------------
void ayuda() {
  Serial.println("\nComandos: t autoprueba · s SOS · c confirmar · x detener alarma · e estado");
  Serial.println("          g NMEA crudo · p LAT LNG simular posición · h ayuda");
  Serial.println("Botón: corto = confirmar recordatorio o SOS · largo 3 s = detener alarma\n");
}
void imprimirEstado() {
  double lat, lng;
  bool hay = posicionActual(lat, lng);
  Serial.printf("[Estado %s] Wi-Fi %s %.0f dBm (límite %d) | ", horaServidor.c_str(),
                WiFi.status() == WL_CONNECTED ? WiFi.SSID().c_str() : "DESCONECTADO", rssiProm, umbral);
  if (hay) Serial.printf("GPS %.6f, %.6f%s", lat, lng, simActiva ? " (sim)" : ""); else Serial.print("GPS sin posición");
  Serial.printf(" | app %s | %s", servidorReciente() ? "OK" : "SIN CONEXIÓN", fueraDelPerimetro() ? "FUERA" : "dentro");
  if (recordatorioId != "0") Serial.printf(" | recordatorio: %s", recordatorioTitulo.c_str());
  Serial.println();
}
void leerSerial() {
  if (!Serial.available()) return;
  String l = Serial.readStringUntil('\n'); l.trim();
  if (!l.length()) return;
  char c = tolower(l[0]);
  String arg = l.substring(1); arg.trim();
  switch (c) {
    case 't': autoprueba(); break;
    case 's': activarSOS(); break;
    case 'c': if (recordatorioId != "0") confirmarRecordatorio(); else Serial.println("No hay recordatorio sonando."); break;
    case 'x': detenerAlarmas(); break;
    case 'e': imprimirEstado(); break;
    case 'g': verNMEA = !verNMEA; break;
    case 'p': {
      int esp = arg.indexOf(' ');
      if (!arg.length() || esp < 0) { simActiva = false; Serial.println("[Sim] Usando GPS real."); }
      else { simLat = arg.substring(0, esp).toDouble(); simLng = arg.substring(esp + 1).toDouble(); simActiva = true;
             Serial.printf("[Sim] Posición simulada %.6f, %.6f\n", simLat, simLng); proximoIntento = 0; ultimoEnvio = 0; }
      break;
    }
    default: ayuda();
  }
}

// ---------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(PIN_BOTON, INPUT_PULLUP);
  pinMode(PIN_BUZZER, OUTPUT);
  buzzerOff();
  gpsSerial.setRxBufferSize(1024);
  gpsSerial.begin(9600, SERIAL_8N1, PIN_GPS_RX, PIN_GPS_TX);
  Serial.println("\nLocalizador GPS · Grupo 7 · ARC115 · versión nube");
  autoprueba();
  ayuda();
}

void loop() {
  alimentarGPS();
  leerBoton();
  leerSerial();
  unsigned long now = millis();

  static unsigned long tWifi = 0;
  if (now - tWifi >= 2000) { tWifi = now; medirWiFi(); if (WiFi.status() != WL_CONNECTED) conectarWiFi(false); }

  bool hayEventos = pendSOS || pendConfirmar.length() || pendCancelar;
  unsigned long intervalo = modoRapido ? INTERVALO_RAPIDO_MS : INTERVALO_PRESENCIA_MS;
  if (ultimoEnvio == 0 || now - ultimoEnvio >= intervalo || (hayEventos && (long)(now - proximoIntento) >= 0)) {
    ultimoEnvio = now;
    if (!enviarPresencia() && hayEventos) proximoIntento = now + 5000;
  }

  if (sosHasta && (long)(now - sosHasta) >= 0) sosHasta = 0;
  if (buscarHasta && (long)(now - buscarHasta) >= 0) buscarHasta = 0;
  decidirSonido();
  actualizarBuzzer();

  static unsigned long tEst = 0;
  if (!verNMEA && now - tEst >= 10000) { tEst = now; imprimirEstado(); }
}
