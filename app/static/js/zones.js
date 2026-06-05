// Privacy-zone picker: click the map to set a centre, slider sets the radius,
// a live circle previews the zone, and existing zones render as static circles.
(function () {
  const mapEl = document.getElementById("map");
  if (!mapEl || typeof L === "undefined") return;

  const existing = window.__existingZones || [];

  const street = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap",
  });
  const map = L.map("map", { layers: [street] });

  const bounds = [];
  existing.forEach((z) => {
    L.circle([z.lat, z.lon], { radius: z.r, color: "#888", fillColor: "#888", fillOpacity: 0.2 })
      .addTo(map)
      .bindPopup(z.label);
    bounds.push([z.lat, z.lon]);
  });

  function fitView() {
    if (bounds.length) map.fitBounds(bounds, { maxZoom: 13, padding: [40, 40] });
    else map.setView([45.4, -75.7], 11); // arbitrary default until the user pans
  }

  // The map's height is vh-based and it sits below dynamic content, so its real
  // size isn't known the instant L.map() runs (and under hx-boosted navigation
  // the container is laid out after init). A ResizeObserver fires as soon as the
  // container gets its true size — and on any later change — keeping Leaflet's
  // internal size in sync so it never renders oversized/offset until a refresh.
  // The first callback owns the initial fit, once the size is actually known.
  if (typeof ResizeObserver !== "undefined") {
    let first = true;
    new ResizeObserver(() => {
      map.invalidateSize();
      if (first) {
        first = false;
        fitView();
      }
    }).observe(mapEl);
  } else {
    fitView();
    requestAnimationFrame(() => map.invalidateSize());
    window.addEventListener("load", () => map.invalidateSize(), { once: true });
  }

  const latIn = document.getElementById("zone-lat");
  const lonIn = document.getElementById("zone-lon");
  const radius = document.getElementById("zone-radius");
  const radiusOut = document.getElementById("radius-out");
  const save = document.getElementById("zone-save");
  const hint = document.getElementById("zone-hint");
  if (!radius) return; // at-limit page renders no form

  let marker = null;
  let preview = null;

  function redraw() {
    if (!marker) return;
    const ll = marker.getLatLng();
    if (preview) map.removeLayer(preview);
    preview = L.circle(ll, {
      radius: Number(radius.value),
      color: "#ff5a36",
      fillColor: "#ff5a36",
      fillOpacity: 0.25,
    }).addTo(map);
  }

  map.on("click", (e) => {
    if (marker) marker.setLatLng(e.latlng);
    else marker = L.marker(e.latlng, { draggable: true }).addTo(map);
    marker.on("drag", () => {
      latIn.value = marker.getLatLng().lat.toFixed(6);
      lonIn.value = marker.getLatLng().lng.toFixed(6);
      redraw();
    });
    latIn.value = e.latlng.lat.toFixed(6);
    lonIn.value = e.latlng.lng.toFixed(6);
    save.disabled = false;
    if (hint) hint.textContent = "Drag the pin or slider to adjust, then save.";
    redraw();
  });

  radius.addEventListener("input", () => {
    if (radiusOut) radiusOut.textContent = radius.value;
    redraw();
  });
})();
