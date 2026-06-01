// uPlot elevation + speed profile vs distance, with hover-scrub that drives a
// callback (used to move the map marker). Exposes window.RideElevation.init.
(function () {
  function haversine(a, b) {
    const R = 6371000;
    const dLat = ((b[0] - a[0]) * Math.PI) / 180;
    const dLon = ((b[1] - a[1]) * Math.PI) / 180;
    const la1 = (a[0] * Math.PI) / 180;
    const la2 = (b[0] * Math.PI) / 180;
    const h =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  const RideElevation = {
    init(data, onHover, opts) {
      const pts = data.points || [];
      const el = document.getElementById("elevation");
      if (!el || pts.length < 2) {
        if (el) el.style.display = "none";
        return;
      }
      const imperial = (opts && opts.unit) === "mi";

      // Cumulative distance for the x-axis.
      const xs = [];
      let cum = 0;
      for (let i = 0; i < pts.length; i++) {
        if (i > 0) {
          cum += haversine([pts[i - 1].lat, pts[i - 1].lon], [pts[i].lat, pts[i].lon]);
        }
        xs.push(imperial ? cum / 1609.344 : cum / 1000);
      }
      const elev = pts.map((p) =>
        p.elev == null ? null : imperial ? p.elev * 3.28084 : p.elev
      );
      const speed = pts.map((p) =>
        p.speed == null ? null : imperial ? p.speed * 2.236936 : p.speed * 3.6
      );

      const xUnit = imperial ? "mi" : "km";
      const elUnit = imperial ? "ft" : "m";
      const spUnit = imperial ? "mph" : "km/h";

      const opts2 = {
        width: el.clientWidth || 800,
        height: 220,
        scales: { x: { time: false } },
        series: [
          { label: `Dist (${xUnit})` },
          {
            label: `Elev (${elUnit})`,
            stroke: "#5aa9ff",
            width: 2,
            scale: "elev",
          },
          {
            label: `Speed (${spUnit})`,
            stroke: "#ff5a36",
            width: 1,
            scale: "speed",
          },
        ],
        axes: [
          { stroke: "#9aa3b2" },
          { scale: "elev", stroke: "#5aa9ff" },
          { scale: "speed", side: 1, stroke: "#ff5a36", grid: { show: false } },
        ],
        hooks: {
          setCursor: [
            (u) => {
              const idx = u.cursor.idx;
              if (typeof onHover === "function") onHover(idx);
            },
          ],
        },
      };

      const plot = new uPlot(opts2, [xs, elev, speed], el);

      window.addEventListener("resize", () => {
        plot.setSize({ width: el.clientWidth || 800, height: 220 });
      });
    },
  };

  window.RideElevation = RideElevation;
})();
