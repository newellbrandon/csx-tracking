(function () {
  const navy = getComputedStyle(document.documentElement).getPropertyValue("--csx-navy").trim() || "#003366";
  const gold = getComputedStyle(document.documentElement).getPropertyValue("--csx-gold").trim() || "#FFC726";
  const blue = getComputedStyle(document.documentElement).getPropertyValue("--csx-blue").trim() || "#104f8c";

  const ctxYards = document.getElementById("chart-yards").getContext("2d");
  const chartYards = new Chart(ctxYards, {
    type: "bar",
    data: { labels: [], datasets: [{ label: "Cars at yard", data: [], backgroundColor: gold, borderColor: navy, borderWidth: 1 }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: navy, font: { weight: 600 } }, grid: { display: false } },
        y: { ticks: { color: navy }, grid: { color: "rgba(0,51,102,0.08)" }, beginAtZero: true, precision: 0 },
      },
    },
  });

  function renderEmptyRow(tbody, cols, msg) {
    tbody.innerHTML = `<tr><td colspan="${cols}" class="muted">${msg}</td></tr>`;
  }

  async function refresh() {
    try {
      const [kpi, yards, comm, dwell, vel] = await Promise.all([
        fetch("/api/pulse/kpi").then((r) => r.json()),
        fetch("/api/pulse/cars_per_yard").then((r) => r.json()),
        fetch("/api/pulse/top_commodities").then((r) => r.json()),
        fetch("/api/pulse/dwell_leaders").then((r) => r.json()),
        fetch("/api/pulse/train_velocity").then((r) => r.json()),
      ]);
      document.getElementById("kpi-trains").textContent = kpi.trains_in_motion;
      document.getElementById("kpi-cars").textContent = kpi.cars_in_motion;
      document.getElementById("kpi-bills").textContent = kpi.active_waybills;
      document.getElementById("kpi-vel").textContent = kpi.avg_velocity_kmh;

      chartYards.data.labels = yards.rows.map((r) => r.yard_code);
      chartYards.data.datasets[0].data = yards.rows.map((r) => r.count);
      chartYards.update();
      if (!yards.rows.length) {
        // Chart.js shows empty area; nothing to do.
      }

      const tbComm = document.getElementById("tbl-commodities");
      if (!comm.rows.length) renderEmptyRow(tbComm, 3, "No in-transit cars");
      else tbComm.innerHTML = comm.rows.map((r) => `
        <tr>
          <td>${r.commodity_class}</td>
          <td class="num">${r.count}</td>
          <td class="num">${r.hazmat > 0 ? `<span class="chip chip-late">${r.hazmat}</span>` : 0}</td>
        </tr>`).join("");

      const tbDwell = document.getElementById("tbl-dwell");
      if (!dwell.rows.length) renderEmptyRow(tbDwell, 5, "No completed dwell pairs yet");
      else tbDwell.innerHTML = dwell.rows.map((r) => `
        <tr>
          <td class="mono">${r.yard_code}</td>
          <td>${r.city || ""}${r.state ? `, ${r.state}` : ""}</td>
          <td class="num">${r.avg_min}</td>
          <td class="num">${r.max_min}</td>
          <td class="num">${r.samples}</td>
        </tr>`).join("");

      const tbVel = document.getElementById("tbl-velocity");
      if (!vel.rows.length) renderEmptyRow(tbVel, 4, "No GPS points in the last 2 hours");
      else tbVel.innerHTML = vel.rows.map((r) => `
        <tr>
          <td class="mono">${r.train_symbol}</td>
          <td class="num">${r.samples}</td>
          <td class="num">${r.km}</td>
          <td class="num">${r.kmh}</td>
        </tr>`).join("");

      if (window.csxMql) {
        const root = document.getElementById("pulse-mql-root");
        root.innerHTML = "";
        const panels = [
          ["KPI tiles ($facet + velocity)", kpi.mql],
          ["Cars per yard", yards.mql],
          ["Top commodities in motion", comm.mql],
          ["Dwell-time leaders (events time-series)", dwell.mql],
          ["Train velocity (GPS events)", vel.mql],
        ];
        panels.forEach(([title, mql]) => {
          if (mql) csxMql.renderCard(root, title, mql);
        });
      }
    } catch (e) {
      console.error("pulse refresh failed", e);
    }
  }

  refresh();
  setInterval(refresh, 15000);
})();
