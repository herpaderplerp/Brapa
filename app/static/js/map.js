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

      // The container can be laid out (flex/CSS, boosted nav) after init, leaving
      // Leaflet with a stale size and scattered tiles. Recompute + refit once the
      // browser has settled so the first load matches a manual refresh.
      this._fixSize();

      this.marker = L.circleMarker([0, 0], {
        radius: 6,
        color: "#fff",
        weight: 2,
        fillColor: "#ff5a36",
        fillOpacity: 1,
      });
    },

    _fixSize() {
      const refit = () => {
        if (!this.map) return;
        this.map.invalidateSize();
        if (this.latlngs && this.latlngs.length) this.map.fitBounds(this.latlngs);
      };
      requestAnimationFrame(refit);
      setTimeout(refit, 200);
      window.addEventListener("load", refit, { once: true });
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

    initCompare(dataA, dataB) {
      const street = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "© OpenStreetMap",
      });
      this.map = L.map("map", { layers: [street] });

      const all = [];
      const draw = (data, color, label) => {
        const ll = (data.points || []).map((p) => [p.lat, p.lon]);
        if (ll.length) {
          L.polyline(ll, { color, weight: 4, opacity: 0.85 }).addTo(this.map);
          all.push(...ll);
        }
        return label;
      };
      draw(dataA, "#5aa9ff", "A");
      draw(dataB, "#ff5a36", "B");
      this.latlngs = all;
      if (all.length) this.map.fitBounds(all);
      else this.map.setView([0, 0], 2);
      this._fixSize();

      const legend = L.control({ position: "topright" });
      legend.onAdd = function () {
        const div = L.DomUtil.create("div", "compare-legend");
        div.innerHTML =
          '<span style="color:#5aa9ff">⬤</span> Ride A&nbsp; ' +
          '<span style="color:#ff5a36">⬤</span> Ride B';
        return div;
      };
      legend.addTo(this.map);
    },

    addPhotos(photos) {
      if (!this.map || !photos) return;
      photos.forEach((p) => {
        if (p.lat == null || p.lon == null) return;
        const m = L.marker([p.lat, p.lon]).addTo(this.map);
        m.bindPopup(
          `<a href="${p.url}" target="_blank"><img src="${p.url}" style="max-width:200px;border-radius:6px"></a>`
        );
      });
    },

    // Manual photo placement (US-14): arm a one-shot map click that posts the
    // clicked coords to the place endpoint, then reloads.
    placePhoto(rideId, photoId) {
      if (!this.map) return;
      this._placing = true;
      document.getElementById("place-hint")?.removeAttribute("hidden");
      const handler = (e) => {
        this.map.off("click", handler);
        this._placing = false;
        const form = document.getElementById("place-form");
        form.action = `/rides/${rideId}/photos/${photoId}/place`;
        form.querySelector('input[name="lat"]').value = e.latlng.lat.toFixed(6);
        form.querySelector('input[name="lon"]').value = e.latlng.lng.toFixed(6);
        form.submit();
      };
      this.map.on("click", handler);
    },
  };

  window.RideMap = RideMap;
})();
