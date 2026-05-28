(function () {
  const grid = document.getElementById("trace-grid");
  if (!grid) return;
  const waybill = grid.dataset.waybill;
  const statusEl = document.getElementById("train-status");
  const infoEl = document.getElementById("ship-info");

  const map = L.map("map");
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    subdomains: "abcd",
    maxZoom: 18,
  }).addTo(map);

  let trainMarker = null;
  let trainSymbol = null;

  function pulseIcon() {
    return L.divIcon({ className: "tracked-marker", iconSize: [22, 22] });
  }
  function navyIcon() {
    return L.divIcon({ className: "train-marker", iconSize: [12, 12] });
  }
  function yardIcon() {
    return L.divIcon({ className: "yard-marker", iconSize: [12, 12] });
  }

  function renderShip(data) {
    const s = data.shipment;
    const t = data.train;
    const hazmatChip = s.hazmat ? '<span class="chip chip-late">Hazmat</span>' : '<span class="chip chip-info">Non-haz</span>';
    const statusChip =
      s.status === "in_transit" ? '<span class="chip chip-ok">In Transit</span>' :
      s.status === "at_yard"    ? '<span class="chip chip-warn">At Yard</span>' :
      `<span class="chip chip-info">${s.status}</span>`;
    infoEl.innerHTML = `
      <dl class="kv">
        <dt>Waybill</dt><dd class="mono">${s.waybill_number}</dd>
        <dt>Status</dt><dd>${statusChip} ${hazmatChip}</dd>
        <dt>Equipment</dt><dd class="mono">${s.current_equipment_id}</dd>
        <dt>Train</dt><dd class="mono">${s.current_train_symbol || "—"} <span class="muted">&middot; ${t ? t.description : ""}</span></dd>
        <dt>Commodity</dt><dd>${s.commodity}</dd>
        <dt>Shipper</dt><dd>${s.shipper.name}</dd>
        <dt>Consignee</dt><dd>${s.consignee.name}</dd>
        <dt>Origin</dt><dd>${s.origin_industry}</dd>
        <dt>Destination</dt><dd>${s.destination_industry}</dd>
      </dl>`;
    statusEl.textContent = t ? `Train ${t.symbol}` : "—";
  }

  function drawRoute(segment, yards, trainPos) {
    if (segment && segment.geometry) {
      const coords = segment.geometry.coordinates.map((c) => [c[1], c[0]]);
      L.polyline(coords, {
        color: getComputedStyle(document.documentElement).getPropertyValue("--csx-blue").trim() || "#104f8c",
        weight: 4,
        opacity: 0.85,
      }).addTo(map);
    }
    yards.forEach((y) => {
      const ll = [y.location.coordinates[1], y.location.coordinates[0]];
      L.marker(ll, { icon: yardIcon() })
        .bindPopup(`<b>${y.name}</b> (${y.code})<br/>${y.city}, ${y.state}`)
        .addTo(map);
    });
    if (trainPos) {
      trainMarker = L.marker([trainPos[1], trainPos[0]], { icon: pulseIcon() }).addTo(map);
    }
    const bounds = [];
    if (segment && segment.geometry) bounds.push(...segment.geometry.coordinates.map((c) => [c[1], c[0]]));
    yards.forEach((y) => bounds.push([y.location.coordinates[1], y.location.coordinates[0]]));
    if (bounds.length) map.fitBounds(bounds, { padding: [40, 40] });
    else map.setView([37, -82], 5);
  }

  async function loadAll() {
    const res = await fetch(`/api/shipment/${encodeURIComponent(waybill)}`);
    if (!res.ok) {
      infoEl.innerHTML = `<p style="color:var(--status-late)">Lookup failed: ${res.status}</p>`;
      return;
    }
    const data = await res.json();
    trainSymbol = data.shipment.current_train_symbol;
    renderShip(data);
    const trainPos = data.train ? data.train.current_position.coordinates : null;
    drawRoute(data.segment, data.yards, trainPos);
    if (data.mql && window.csxMql) {
      const root = document.getElementById("track-mql-root");
      root.innerHTML = "";
      csxMql.renderCard(root, "Underlying MQL — shipment trace", data.mql);
    }
  }

  async function pollPosition() {
    if (!trainSymbol) return;
    try {
      const res = await fetch(`/api/positions?train_symbol=${encodeURIComponent(trainSymbol)}`);
      if (!res.ok) return;
      const t = await res.json();
      const ll = [t.current_position.coordinates[1], t.current_position.coordinates[0]];
      if (trainMarker) trainMarker.setLatLng(ll);
      else trainMarker = L.marker(ll, { icon: pulseIcon() }).addTo(map);
      statusEl.textContent = `Train ${t.symbol}`;
    } catch (e) { /* swallow transient */ }
  }

  loadAll().then(() => {
    setInterval(pollPosition, 5000);
  });
})();
