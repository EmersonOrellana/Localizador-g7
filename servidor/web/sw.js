/* Service worker: muestra las notificaciones push aunque la app esté cerrada */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (e) { d = { titulo: "Localizador", cuerpo: event.data && event.data.text() }; }
  const opciones = {
    body: d.cuerpo || "",
    icon: "/icono-192.png",
    badge: "/icono-192.png",
    tag: d.etiqueta || "aviso",
    renotify: true,
    requireInteraction: !!d.urgente,
    vibrate: d.urgente ? [300, 120, 300, 120, 600] : [150],
    data: { url: d.url || "/" },
  };
  event.waitUntil(self.registration.showNotification(d.titulo || "Localizador de cuidado", opciones));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil((async () => {
    const ventanas = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const v of ventanas) { if ("focus" in v) return v.focus(); }
    return self.clients.openWindow(url);
  })());
});
