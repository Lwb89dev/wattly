/* WATTLY charts — thin Chart.js wrappers themed via CSS custom properties.
   Every page registers builders; Wattly.refresh() re-themes and rebuilds. */
(function () {
  "use strict";

  const registry = [];
  let instances = [];
  let palette = {};

  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function readPalette() {
    palette = {
      accent: cssVar("--accent", "#2563eb"),
      accent2: cssVar("--accent-2", "#06b6d4"),
      grid: cssVar("--chart-grid", "#e6ecf4"),
      dim: cssVar("--text-faint", "#8b96ab"),
      warn: cssVar("--warn", "#d97706"),
      ok: cssVar("--ok", "#0d9488"),
      surface: cssVar("--surface", "#ffffff"),
    };
  }

  function applyDefaults() {
    if (!window.Chart) return;
    Chart.defaults.font.family = "Inter, system-ui, sans-serif";
    Chart.defaults.font.size = 11.5;
    Chart.defaults.color = palette.dim;
    Chart.defaults.borderColor = palette.grid;
    Chart.defaults.plugins.legend.display = false;
    Chart.defaults.plugins.tooltip.backgroundColor = palette.surface;
    Chart.defaults.plugins.tooltip.titleColor = cssVar("--text", "#1a2233");
    Chart.defaults.plugins.tooltip.bodyColor = cssVar("--text", "#1a2233");
    Chart.defaults.plugins.tooltip.borderColor = palette.grid;
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
    Chart.defaults.animation.duration = 500;
  }

  function make(canvasId, config) {
    const el = document.getElementById(canvasId);
    if (!el || !window.Chart) return null;
    instances.push(new Chart(el.getContext("2d"), config));
    return instances[instances.length - 1];
  }

  function gradient(ctx, hex, alphaTop) {
    const g = ctx.createLinearGradient(0, 0, 0, ctx.canvas.clientHeight || 260);
    g.addColorStop(0, hexA(hex, alphaTop));
    g.addColorStop(1, hexA(hex, 0));
    return g;
  }

  function hexA(hex, alpha) {
    if (!hex.startsWith("#")) return hex;
    const n = parseInt(hex.slice(1), 16);
    const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return `rgba(${r},${g},${b},${alpha})`;
  }

  function register(builder) { registry.push(builder); }

  function renderAll() {
    readPalette();
    applyDefaults();
    instances.forEach((c) => c.destroy());
    instances = [];
    registry.forEach((b) => b(make, palette, { gradient, hexA }));
  }

  window.Wattly = window.Wattly || {};
  window.Wattly.charts = { register, refresh: renderAll };
  document.addEventListener("DOMContentLoaded", renderAll);

  /* -------------------------------------------------------------- */
  /* Page builders                                                   */
  /* -------------------------------------------------------------- */
  window.WattlyPage = {
    dashboard(data) {
      register((make, p, util) => {
        make("trendChart", {
          type: "line",
          data: {
            labels: data.labels,
            datasets: [
              {
                label: "kWh", data: data.kwh, yAxisID: "y",
                borderColor: p.accent, borderWidth: 2, tension: 0.32,
                pointRadius: 3, pointBackgroundColor: p.accent,
                fill: true,
                backgroundColor: (c) => util.gradient(c.chart.ctx, p.accent, 0.22),
              },
              {
                label: "Cost", data: data.cost, yAxisID: "y1",
                borderColor: p.accent2, borderWidth: 1.8, tension: 0.32,
                pointRadius: 0, borderDash: [5, 4],
              },
            ],
          },
          options: {
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            scales: {
              y: { position: "left", title: { display: true, text: "kWh" }, grid: { color: p.grid } },
              y1: { position: "right", title: { display: true, text: "cost" }, grid: { drawOnChartArea: false } },
              x: { grid: { display: false } },
            },
          },
        });
      });
    },

    analytics(data) {
      register((make, p, util) => {
        make("kwhChart", {
          type: "line",
          data: {
            labels: data.labels,
            datasets: [
              {
                label: "kWh", data: data.kwh,
                borderColor: p.accent, borderWidth: 2, tension: 0.3,
                pointRadius: 3, pointBackgroundColor: p.accent, fill: true,
                backgroundColor: (c) => util.gradient(c.chart.ctx, p.accent, 0.2),
              },
              {
                label: "Rolling avg (3)", data: data.rolling,
                borderColor: p.accent2, borderWidth: 1.8, tension: 0.4,
                pointRadius: 0, borderDash: [6, 4],
              },
            ],
          },
          options: {
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            scales: { y: { grid: { color: p.grid } }, x: { grid: { display: false } } },
          },
        });
        make("costChart", {
          type: "bar",
          data: {
            labels: data.labels,
            datasets: [{
              label: "Cost", data: data.cost,
              backgroundColor: hexA2(p.accent2, 0.65),
              borderRadius: 6, maxBarThickness: 34,
            }],
          },
          options: {
            maintainAspectRatio: false,
            scales: { y: { grid: { color: p.grid } }, x: { grid: { display: false } } },
          },
        });
        make("perKwhChart", {
          type: "line",
          data: {
            labels: data.labels,
            datasets: [{
              label: "€/kWh", data: data.perKwh,
              borderColor: p.warn, borderWidth: 2, tension: 0.3,
              pointRadius: 3, pointBackgroundColor: p.warn, fill: true,
              backgroundColor: (c) => util.gradient(c.chart.ctx, p.warn, 0.16),
            }],
          },
          options: {
            maintainAspectRatio: false,
            scales: { y: { grid: { color: p.grid } }, x: { grid: { display: false } } },
          },
        });
        if (data.bands && Object.keys(data.bands).length) {
          const bandColors = [p.accent, p.accent2, p.warn];
          make("bandsChart", {
            type: "bar",
            data: {
              labels: data.labels,
              datasets: Object.entries(data.bands).map(([label, values], i) => ({
                label, data: values, stack: "bands",
                backgroundColor: hexA2(bandColors[i % 3], 0.7),
                borderRadius: 5, maxBarThickness: 34,
              })),
            },
            options: {
              maintainAspectRatio: false,
              scales: {
                x: { stacked: true, grid: { display: false } },
                y: { stacked: true, grid: { color: p.grid }, title: { display: true, text: "kWh" } },
              },
            },
          });
        }
      });
    },

    compare(data) {
      register((make, p, util) => {
        make("compareChart", {
          data: {
            labels: data.labels,
            datasets: [
              {
                type: "bar", label: "kWh", data: data.kwh, yAxisID: "y",
                backgroundColor: hexA2(p.accent, 0.7), borderRadius: 7, maxBarThickness: 60,
                order: 2,
              },
              {
                type: "line", label: "Cost", data: data.cost, yAxisID: "y1",
                borderColor: p.accent2, borderWidth: 2.2, tension: 0.3,
                pointRadius: 4, pointBackgroundColor: p.accent2, order: 1,
              },
            ],
          },
          options: {
            maintainAspectRatio: false,
            scales: {
              y: { position: "left", grid: { color: p.grid }, title: { display: true, text: "kWh" } },
              y1: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "cost" } },
              x: { grid: { display: false } },
            },
          },
        });
        if (data.bandLabels && data.bandLabels.length) {
          const bandColors = [p.accent, p.accent2, p.warn];
          make("compareBandsChart", {
            type: "bar",
            data: {
              labels: data.bandLabels,
              datasets: [
                {
                  label: data.labels[0], data: data.bandA,
                  backgroundColor: hexA2(bandColors[0], 0.45),
                  borderColor: bandColors[0], borderWidth: 1.4, borderRadius: 5, maxBarThickness: 40,
                },
                {
                  label: data.labels[1], data: data.bandB,
                  backgroundColor: hexA2(bandColors[1], 0.55),
                  borderColor: bandColors[1], borderWidth: 1.4, borderRadius: 5, maxBarThickness: 40,
                },
              ],
            },
            options: {
              maintainAspectRatio: false,
              plugins: { legend: { display: true, position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } } },
              scales: { y: { grid: { color: p.grid }, title: { display: true, text: "kWh" } }, x: { grid: { display: false } } },
            },
          });
        }
      });
    },

    bands(data) {
      register((make, p, util) => {
        make("bandsChart", {
          type: "doughnut",
          data: {
            labels: data.labels,
            datasets: [{
              data: data.kwh,
              backgroundColor: [hexA2(p.accent, 0.75), hexA2(p.accent2, 0.75), hexA2(p.warn, 0.75)],
              borderWidth: 0, hoverOffset: 6,
            }],
          },
          options: {
            maintainAspectRatio: false, cutout: "62%",
            plugins: { legend: { display: true, position: "right", labels: { boxWidth: 10, boxHeight: 10 } } },
          },
        });
      });
    },
  };

  function hexA2(hex, alpha) {
    if (!hex.startsWith("#")) return hex;
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
  }
})();
