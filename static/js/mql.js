/** Render mongosh-style MQL with highlight.js syntax highlighting. */
window.csxMql = {
  render(container, mql) {
    if (!container || !mql) return;
    const ops = mql.operations || [];
    const labels = ops.map((o, i) => {
      const kind = o.operation === "aggregate" ? "aggregate" : "find";
      return `${o.collection}.${kind}${ops.length > 1 ? ` #${i + 1}` : ""}`;
    });

    let tabs = "";
    let panels = "";
    if (ops.length > 1) {
      tabs = `<div class="mql-tabs">${labels.map((l, i) =>
        `<button type="button" class="mql-tab${i === 0 ? " active" : ""}" data-idx="${i}">${l}</button>`
      ).join("")}</div>`;
    }

    const shellParts = (mql.shell || "").split("\n\n");
    shellParts.forEach((snippet, i) => {
      panels += `
        <div class="mql-snippet${i === 0 ? "" : " hidden"}" data-idx="${i}">
          <div class="mql-meta mono">${labels[i] || "query"} · db: ${mql.database}</div>
          <pre class="mql-code"><code class="language-javascript">${escapeHtml(snippet)}</code></pre>
        </div>`;
    });

    container.innerHTML = `
      <div class="mql-panel-inner">
        ${tabs}
        ${panels}
        <button type="button" class="btn btn-secondary mql-copy" style="margin-top:8px;font-size:12px">Copy MQL</button>
      </div>`;

    container.querySelectorAll(".mql-code code").forEach((el) => {
      if (window.hljs) hljs.highlightElement(el);
    });

    const snippets = container.querySelectorAll(".mql-snippet");
    container.querySelectorAll(".mql-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = btn.dataset.idx;
        container.querySelectorAll(".mql-tab").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        snippets.forEach((s) => s.classList.toggle("hidden", s.dataset.idx !== idx));
      });
    });

    const copyBtn = container.querySelector(".mql-copy");
    if (copyBtn) {
      copyBtn.addEventListener("click", () => {
        const visible = container.querySelector(".mql-snippet:not(.hidden) code");
        const text = visible ? visible.textContent : mql.shell;
        navigator.clipboard.writeText(text).then(() => {
          copyBtn.textContent = "Copied!";
          setTimeout(() => { copyBtn.textContent = "Copy MQL"; }, 1500);
        });
      });
    }
  },

  renderCard(parent, title, mql) {
    if (!parent) return;
    const card = document.createElement("div");
    card.className = "card mql-card";
    card.innerHTML = `
      <div class="card-header mql-header">
        <span>${title}</span>
        <button type="button" class="mql-toggle btn btn-secondary" style="font-size:11px;padding:4px 10px">Show MQL</button>
      </div>
      <div class="card-body mql-body hidden"></div>`;
    parent.appendChild(card);
    const body = card.querySelector(".mql-body");
    const toggle = card.querySelector(".mql-toggle");
    toggle.addEventListener("click", () => {
      const hidden = body.classList.toggle("hidden");
      toggle.textContent = hidden ? "Show MQL" : "Hide MQL";
      if (!hidden && !body.dataset.rendered) {
        csxMql.render(body, mql);
        body.dataset.rendered = "1";
      }
    });
  },

  initEmbeds(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll(".mql-embed:not([data-done])").forEach((wrap) => {
      const jsonEl = wrap.querySelector(".mql-json");
      if (!jsonEl) return;
      try {
        const mql = JSON.parse(jsonEl.textContent);
        const panel = document.createElement("div");
        wrap.appendChild(panel);
        csxMql.render(panel, mql);
        wrap.dataset.done = "1";
      } catch (e) {
        console.error("mql embed parse failed", e);
      }
    });
  },
};

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
