// Leaflet ride map: speed-gradient polyline, basemap switcher, scrub marker.
// Exposes window.RideMap.{init(data), showIndex(i), hideMarker()}.
(function () {
  function speedColor(norm) {
    // norm in [0,1] -> blue (slow, hue 240) to red (fast, hue 0).
    const hue = 240 - 240 * Math.max(0, Math.min(1, norm));
    return `hsl(${hue}, 85%, 50%)`;
  }

  const RideMap = {
    map: null,
    marker: null,
    latlngs: [],

    init(data) {
      const pts = data.points || [];
      this.latlngs = pts.map((p) => [p.lat, p.lon]);

      const street = L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        { maxZoom: 19, attribution: "© OpenStreetMap" }
      );
      const satellite = L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        { maxZoom: 19, attribution: "© Esri" }
      );
      const topo = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
        maxZoom: 17,
        attribution: "© OpenTopoMap",
      });

      this.map = L.map("map", { layers: [street] });
      L.control.layers({ Street: street, Satellite: satellite, Topographic: topo }).addTo(this.map);

      // Speed range for normalization (ignore nulls).
      const speeds = pts.map((p) => p.speed).filter((s) => s != null);
      const min = speeds.length ? Math.min(...speeds) : 0;
      const max = speeds.length ? Math.max(...speeds) : 1;
      const span = max - min || 1;

      // Per-segment colored polylines (Leaflet has no native gradient line).
      for (let i = 1; i < pts.length; i++) {
        const s = pts[i].speed != null ? pts[i].speed : min;
        const norm = (s - min) / span;
        L.polyline([this.latlngs[i - 1], this.latlngs[i]], {
          color: speedColor(norm),
          weight: 4,
          opacity: 0.9,
        }).addTo(this.map);
      }

      if (this.latlngs.length) {
        this.map.fitBounds(this.latlngs);
      } else {
        this.map.setView([0, 0], 2);
      }

      this.marker = L.circleMarker([0, 0], {
        radius: 6,
        color: "#fff",
        weight: 2,
        fillColor: "#ff5a36",
        fillOpacity: 1,
      });
    },

    showIndex(i) {
      if (!this.map || i == null || i < 0 || i >= this.latlngs.length) return;
      this.marker.setLatLng(this.latlngs[i]);
      if (!this.map.hasLayer(this.marker)) this.marker.addTo(this.map);
    },

    hideMarker() {
      if (this.map && this.marker && this.map.hasLayer(this.marker)) {
        this.map.removeLayer(this.marker);
      }
    },
  };

  window.RideMap = RideMap;
})();
