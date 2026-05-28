(function () {
  const btn = document.getElementById("demo-reset");
  if (!btn) return;

  btn.addEventListener("click", async () => {
    if (btn.disabled) return;
    const label = btn.textContent;
    btn.disabled = true;
    btn.classList.add("resetting");
    btn.textContent = "Resetting…";

    try {
      const res = await fetch("/api/reset", { method: "POST" });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      btn.textContent = "Replaying…";
      // Full reload preserves ?id= on /track so the same shipment replays from t=0.
      window.location.reload();
    } catch (err) {
      console.error("demo reset failed", err);
      btn.textContent = "Reset failed";
      btn.classList.remove("resetting");
      btn.disabled = false;
      setTimeout(() => {
        btn.textContent = label;
      }, 2500);
    }
  });
})();
