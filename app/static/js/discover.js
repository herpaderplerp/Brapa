// Discovery results map: drop markers at ride starts, draw the search bbox,
// fit bounds. Reads window.__discover = { markers, bbox, center }.
(function () {
  const cfg = window.__discover || {};
  const el = document.getElementById("map");
  if (!el) return;

  const map = L.map("map");
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap",
  }).addTo(map);

  const bounds = [];

  if (cfg.bbox && cfg.bbox.length === 4) {
    const [minLon, minLat, maxLon, maxLat] = cfg.bbox;
    L.rectangle(
      [[minLat, minLon], [maxLat, maxLon]],
      { color: "#ff5a36", weight: 1, fill: false, dashArray: "4" }
    ).addTo(map);
    bounds.push([minLat, minLon], [maxLat, maxLon]);
  }

  (cfg.markers || []).forEach((m) => {
    if (m.lat == null || m.lon == null) return;
    const marker = L.marker([m.lat, m.lon]).addTo(map);
    marker.bindPopup(`<a href="${m.url}">${m.title}</a>`);
    bounds.push([m.lat, m.lon]);
  });

  if (bounds.length) map.fitBounds(bounds, { padding: [20, 20] });
  else if (cfg.center) map.setView(cfg.center, 11);
  else map.setView([0, 0], 2);

  // "Search this map area" → set bbox from viewport and submit the form.
  const btn = document.getElementById("search-here");
  if (btn) {
    btn.addEventListener("click", () => {
      const b = map.getBounds();
      const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
        .map((n) => n.toFixed(6))
        .join(",");
      const form = document.querySelector('form[action="/discover"]');
      form.querySelector('input[name="bbox"]').value = bbox;
      form.querySelector('input[name="q"]').value = "";
      form.submit();
    });
  }
})();
