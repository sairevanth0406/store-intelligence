/**
 * Purplle Store Intelligence — Live Dashboard JS
 * Polls API every 3 seconds for real-time updates.
 * Updates SVG heatmap, KPI cards, funnel, anomalies, brand table, journeys.
 */

const API_BASE = window.location.origin;
const STORE_ID = "STORE_BLR_002";
let windowHours = 24;
let refreshInterval = null;
let previousAnomalies = new Set();

// ── Initialization ──────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  updateClock();
  setInterval(updateClock, 1000);

  document.getElementById("window-select").addEventListener("change", (e) => {
    windowHours = parseInt(e.target.value);
    fetchAll();
  });

  fetchAll();
  refreshInterval = setInterval(fetchAll, 3000);
});

function updateClock() {
  const now = new Date();
  document.getElementById("current-time").textContent =
    now.toLocaleTimeString("en-IN", { hour12: false }) + " IST";
}

// ── Fetch All Data ───────────────────────────────────────
async function fetchAll() {
  await Promise.allSettled([
    fetchHealth(),
    fetchMetrics(),
    fetchFunnel(),
    fetchHeatmap(),
    fetchAnomalies(),
    fetchBrands(),
    fetchJourneys(),
  ]);
}

// ── API Helpers ──────────────────────────────────────────
async function apiFetch(endpoint) {
  const resp = await fetch(`${API_BASE}${endpoint}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

// ── Health ───────────────────────────────────────────────
async function fetchHealth() {
  try {
    const data = await apiFetch(`/health?store_id=${STORE_ID}`);
    const badge = document.getElementById("health-badge");
    const text = document.getElementById("health-text");
    badge.className = `health-badge ${data.status}`;
    const statusLabels = { healthy: "✓ Healthy", degraded: "⚠ Degraded", unhealthy: "✗ Unhealthy" };
    text.textContent = statusLabels[data.status] || data.status;
  } catch (e) {
    const badge = document.getElementById("health-badge");
    badge.className = "health-badge unhealthy";
    document.getElementById("health-text").textContent = "API Offline";
  }
}

// ── Metrics ──────────────────────────────────────────────
async function fetchMetrics() {
  try {
    const data = await apiFetch(`/stores/${STORE_ID}/metrics?window_hours=${windowHours}`);
    animateKPI("kpi-visitors-val", data.unique_visitors.toLocaleString());
    animateKPI("kpi-conversion-val", `${(data.conversion_rate * 100).toFixed(1)}%`);
    const dwellMin = Math.floor(data.avg_dwell_seconds / 60);
    const dwellSec = Math.round(data.avg_dwell_seconds % 60);
    animateKPI("kpi-dwell-val", dwellMin > 0 ? `${dwellMin}m ${dwellSec}s` : `${dwellSec}s`);

    const queueEl = document.getElementById("kpi-queue-val");
    queueEl.textContent = data.queue_depth;
    queueEl.style.color = data.queue_depth >= 5 ? "var(--red-accent)" :
                          data.queue_depth >= 3 ? "var(--amber-accent)" : "var(--text-primary)";

    animateKPI("kpi-abandonment-val", `${(data.abandonment_rate * 100).toFixed(1)}%`);
    document.getElementById("kpi-visitors-sub").textContent =
      `Top: ${data.top_zones?.[0]?.zone_id?.replace("_", " ") || "N/A"}`;
  } catch (e) { /* Silent fail — stale data still visible */ }
}

function animateKPI(id, value) {
  const el = document.getElementById(id);
  if (el && el.textContent !== value) {
    el.classList.add("updating");
    el.textContent = value;
    setTimeout(() => el.classList.remove("updating"), 400);
  }
}

// ── Funnel ───────────────────────────────────────────────
async function fetchFunnel() {
  try {
    const data = await apiFetch(`/stores/${STORE_ID}/funnel?window_hours=${windowHours}`);
    const container = document.getElementById("funnel-container");
    container.innerHTML = "";

    const colors = ["s0", "s1", "s2", "s3", "s4"];
    data.stages.forEach((stage, i) => {
      const pct = Math.round(stage.pct_of_entry * 100);
      const div = document.createElement("div");
      div.className = "funnel-stage";
      div.style.animationDelay = `${i * 0.05}s`;
      div.innerHTML = `
        <div class="funnel-stage-header">
          <span class="funnel-stage-name">${stage.stage}</span>
          <div style="display:flex;gap:10px;align-items:center">
            <span class="funnel-stage-count">${stage.count.toLocaleString()}</span>
            <span class="funnel-stage-pct">${pct}%</span>
          </div>
        </div>
        <div class="funnel-bar-bg">
          <div class="funnel-bar-fill ${colors[i]}" style="width:0%" data-target="${pct}"></div>
        </div>
      `;
      container.appendChild(div);
      // Animate bar
      requestAnimationFrame(() => {
        setTimeout(() => {
          div.querySelector(".funnel-bar-fill").style.width = `${pct}%`;
        }, 50 + i * 80);
      });
    });
  } catch (e) { }
}

// ── Heatmap ───────────────────────────────────────────────
async function fetchHeatmap() {
  try {
    const data = await apiFetch(`/stores/${STORE_ID}/heatmap?window_hours=${windowHours}`);
    const zoneMap = {};
    data.zones.forEach(z => { zoneMap[z.zone_id] = z; });

    // Update SVG zone rects and counts
    document.querySelectorAll(".zone-rect").forEach(rect => {
      const zoneId = rect.dataset.zone;
      const zone = zoneMap[zoneId];
      const countEl = rect.parentElement?.querySelector(".zone-count");

      if (zone) {
        const heat = zone.heat_score / 100;
        const opacity = 0.15 + heat * 0.75;
        rect.style.opacity = opacity;
        rect.style.filter = `brightness(${0.8 + heat * 0.8})`;
        if (countEl) {
          countEl.textContent = `${zone.visitor_count} visitors`;
        }
        // Tooltip
        rect.setAttribute("title", `${zone.display_name}: ${zone.visitor_count} visitors, ${zone.avg_dwell_seconds}s avg dwell`);
      } else {
        rect.style.opacity = "0.3";
        if (countEl) countEl.textContent = "—";
      }
    });
  } catch (e) { }
}

// ── Anomalies ─────────────────────────────────────────────
async function fetchAnomalies() {
  try {
    const data = await apiFetch(`/stores/${STORE_ID}/anomalies?window_hours=1`);
    const list = document.getElementById("anomaly-list");
    const countEl = document.getElementById("anomaly-count");

    const aCount = data.anomalies.length;
    countEl.textContent = aCount === 0 ? "No active anomalies" :
                          `${aCount} active anomaly${aCount > 1 ? "ies" : ""}`;

    if (aCount === 0) {
      list.innerHTML = `<div class="no-anomalies">✓ All systems nominal</div>`;
      return;
    }

    list.innerHTML = "";
    data.anomalies.forEach(a => {
      // Toast for new critical anomalies
      if (a.severity === "CRITICAL" && !previousAnomalies.has(a.anomaly_id)) {
        showToast(`🔴 CRITICAL: ${a.description}`, "critical");
      }
      previousAnomalies.add(a.anomaly_id);

      const timeAgo = timeSince(a.detected_at);
      const item = document.createElement("div");
      item.className = `anomaly-item ${a.severity}`;
      item.innerHTML = `
        <span class="anomaly-severity ${a.severity}">${a.severity}</span>
        <div class="anomaly-content">
          <div class="anomaly-desc">${a.description}</div>
          <div class="anomaly-action">💡 ${a.suggested_action}</div>
        </div>
        <span class="anomaly-time">${timeAgo}</span>
      `;
      list.appendChild(item);
    });
  } catch (e) { }
}

// ── Brand Intelligence ────────────────────────────────────
async function fetchBrands() {
  try {
    const data = await apiFetch(`/stores/${STORE_ID}/brands?window_hours=${windowHours}`);
    const tbody = document.getElementById("brand-tbody");
    tbody.innerHTML = "";

    if (!data.brands || data.brands.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="loading-cell">No brand data yet — run pipeline to ingest events</td></tr>`;
      return;
    }

    data.brands.slice(0, 12).forEach((brand, i) => {
      const rankClass = i === 0 ? "gold" : i === 1 ? "silver" : i === 2 ? "bronze" : "other";
      const convPct = (brand.conversion_rate * 100).toFixed(1);
      const row = document.createElement("tr");
      row.innerHTML = `
        <td><span class="rank-badge ${rankClass}">${brand.heat_rank}</span></td>
        <td><strong>${brand.display_name}</strong>${brand.top_product ? `<br><small style="color:var(--text-muted)">${brand.top_product}</small>` : ""}</td>
        <td><span class="cat-badge ${brand.category}">${brand.category}</span></td>
        <td style="font-weight:600">${brand.unique_visitors}</td>
        <td>${brand.avg_dwell_seconds.toFixed(0)}s</td>
        <td>${brand.converted_visitors}</td>
        <td>
          <div class="conv-bar">
            <div class="conv-bar-bg">
              <div class="conv-bar-fill" style="width:${Math.min(convPct * 2, 100)}%"></div>
            </div>
            <span class="conv-pct">${convPct}%</span>
          </div>
        </td>
        <td style="color:var(--green-accent);font-weight:600">
          ${brand.revenue_attributed > 0 ? `₹${brand.revenue_attributed.toLocaleString("en-IN", {maximumFractionDigits: 0})}` : "—"}
        </td>
      `;
      tbody.appendChild(row);
    });
  } catch (e) { }
}

// ── Journeys ──────────────────────────────────────────────
async function fetchJourneys() {
  try {
    const data = await apiFetch(`/stores/${STORE_ID}/journeys?window_hours=${windowHours}&limit=5`);
    const list = document.getElementById("journey-list");
    const statsEl = document.getElementById("journey-stats");

    const convPct = data.total_journeys > 0
      ? Math.round(data.converting_journeys / data.total_journeys * 100)
      : 0;
    statsEl.textContent = `${data.total_journeys} journeys · ${convPct}% converted`;

    if (!data.common_paths || data.common_paths.length === 0) {
      list.innerHTML = `<div class="journey-loading">No journeys yet — awaiting pipeline data</div>`;
      return;
    }

    list.innerHTML = "";
    data.common_paths.forEach((path, i) => {
      const parts = path.path.split(" → ").map(p =>
        `<span style="color:var(--purple-light)">${p.replace("_", " ")}</span>`
      ).join(` <span class="journey-arrow">→</span> `);

      const div = document.createElement("div");
      div.className = "journey-path";
      div.style.animationDelay = `${i * 0.06}s`;
      div.innerHTML = `
        <div class="journey-path-text">${parts}</div>
        <span class="journey-path-count">${path.count} shoppers</span>
      `;
      list.appendChild(div);
    });
  } catch (e) { }
}

// ── Utilities ─────────────────────────────────────────────
function timeSince(isoString) {
  try {
    const diff = (Date.now() - new Date(isoString).getTime()) / 1000;
    if (diff < 60)   return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    // Older than 24h — show the actual date + time instead of "1270h ago"
    return new Date(isoString).toLocaleString("en-IN", {
      day: "2-digit", month: "short",
      hour: "2-digit", minute: "2-digit", hour12: false
    });
  } catch { return ""; }
}


function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 6000);
}
