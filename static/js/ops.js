(function () {
  const map = L.map("ops-map");
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    subdomains: "abcd",
    maxZoom: 18,
  }).addTo(map);
  map.setView([37.5, -82], 5);

  const yardSel = document.getElementById("yard_code");
  const form = document.getElementById("ops-form");
  const summary = document.getElementById("ops-summary");
  const resultsEl = document.getElementById("ops-results");
  const navyBlue = getComputedStyle(document.documentElement).getPropertyValue("--csx-blue").trim() || "#104f8c";
  const csxGold = getComputedStyle(document.documentElement).getPropertyValue("--csx-gold").trim() || "#FFC726";

  let yardLayer = null;
  let radiusLayer = null;
  let carLayer = null;
  const yardCoords = {}; // code -> [lat, lng]

  function yardIcon() {
    return L.divIcon({ className: "yard-marker", iconSize: [12, 12] });
  }
  function carIcon() {
    return L.divIcon({ className: "train-marker", iconSize: [12, 12] });
  }

  function drawNetwork(geo) {
    L.geoJSON(geo, {
      style: { color: navyBlue, weight: 3, opacity: 0.7 },
    }).addTo(map);
  }

  function drawYards(yards) {
    yardLayer = L.layerGroup();
    yards.forEach((y) => {
      yardCoords[y.code] = [y.location.coordinates[1], y.location.coordinates[0]];
      const opt = document.createElement("option");
      opt.value = y.code;
      opt.textContent = `${y.code} — ${y.name}, ${y.city} ${y.state}`;
      yardSel.appendChild(opt);
      L.marker(yardCoords[y.code], { icon: yardIcon() })
        .bindPopup(`<b>${y.name}</b> (${y.code})<br/>${y.city}, ${y.state}<br/><span class="muted">${y.role || ""}</span>`)
        .addTo(yardLayer);
    });
    yardLayer.addTo(map);
    if (yards.length) yardSel.value = "WCS";
  }

  function clearResults() {
    if (radiusLayer) { radiusLayer.remove(); radiusLayer = null; }
    if (carLayer)    { carLayer.remove();    carLayer = null; }
  }

  function drawGeoResults(center, miles, rows) {
    clearResults();
    radiusLayer = L.circle(center, {
      radius: miles * 1609.344,
      color: csxGold,
      weight: 2,
      fillColor: csxGold,
      fillOpacity: 0.15,
    }).addTo(map);
    carLayer = L.layerGroup();
    rows.forEach((r) => {
      const ll = [r.current_position.coordinates[1], r.current_position.coordinates[0]];
      L.marker(ll, { icon: carIcon() })
        .bindPopup(
          `<b>${r.waybill_number}</b><br/>` +
          `${r.equipment_id} (${r.car_type})<br/>` +
          `${r.commodity}<br/>` +
          `Train ${r.train_symbol || "—"}<br/>` +
          `${r.distance_miles.toFixed(1)} mi away` +
          (r.hazmat ? "<br/><b style='color:#C62828'>HAZMAT</b>" : "")
        )
        .addTo(carLayer);
    });
    carLayer.addTo(map);
    map.fitBounds(radiusLayer.getBounds().pad(0.1));
  }

  async function runNear(ev) {
    if (ev) ev.preventDefault();
    const yardCode = yardSel.value;
    if (!yardCode || !yardCoords[yardCode]) return;
    const [lat, lng] = yardCoords[yardCode];
    const miles = Number(document.getElementById("miles").value || 50);
    const carType = document.getElementById("car_type").value;
    const commCls = document.getElementById("commodity_class").value;
    const hazmat = document.getElementById("hazmat").value;

    const params = new URLSearchParams({ lat, lng, miles });
    if (carType) params.set("car_type", carType);
    if (commCls) params.set("commodity_class", commCls);
    if (hazmat) params.set("hazmat", hazmat);

    summary.textContent = "Running…";
    resultsEl.innerHTML = "<p class=\"muted\">Running $geoNear…</p>";

    const [jsonRes, htmlRes] = await Promise.all([
      fetch(`/api/cars/near?${params}`),
      fetch(`/api/cars/near?${params}`, { headers: { "HX-Request": "true" } }),
    ]);
    if (!jsonRes.ok) {
      resultsEl.innerHTML = `<p style="color:var(--status-late)">Error ${jsonRes.status}</p>`;
      return;
    }
    const data = await jsonRes.json();
    const html = await htmlRes.text();
    resultsEl.innerHTML = html;
    drawGeoResults([lat, lng], miles, data.rows || []);
    summary.textContent = `${data.count} cars within ${miles} mi of ${yardCode}`;
    if (data.mql && window.csxMql) {
      const root = document.getElementById("ops-mql-root");
      root.innerHTML = "";
      csxMql.renderCard(root, "Underlying MQL — $geoNear", data.mql);
    }
  }

  async function runAtYard() {
    const yardCode = yardSel.value;
    if (!yardCode) return;
    summary.textContent = "Loading yard inventory…";
    resultsEl.innerHTML = "<p class=\"muted\">Querying yard inventory…</p>";
    const htmlRes = await fetch(`/api/cars/at_yard?yard_code=${encodeURIComponent(yardCode)}`, {
      headers: { "HX-Request": "true" },
    });
    const jsonRes = await fetch(`/api/cars/at_yard?yard_code=${encodeURIComponent(yardCode)}`);
    if (!htmlRes.ok) {
      resultsEl.innerHTML = `<p style="color:var(--status-late)">Error ${htmlRes.status}</p>`;
      return;
    }
    resultsEl.innerHTML = await htmlRes.text();
    const data = await jsonRes.json();
    clearResults();
    if (yardCoords[yardCode]) map.setView(yardCoords[yardCode], 8);
    summary.textContent = `${data.count} cars at ${yardCode}`;
    if (data.mql && window.csxMql) {
      const root = document.getElementById("ops-mql-root");
      root.innerHTML = "";
      csxMql.renderCard(root, "Underlying MQL — yard inventory", data.mql);
    }
  }

  Promise.all([
    fetch("/api/yards").then((r) => r.json()),
    fetch("/api/network").then((r) => r.json()),
  ]).then(([y, geo]) => {
    drawNetwork(geo);
    drawYards(y.yards);
  });

  form.addEventListener("submit", runNear);
  document.getElementById("run-at-yard").addEventListener("click", runAtYard);
})();
