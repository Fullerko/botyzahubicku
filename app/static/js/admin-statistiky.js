(function () {
  const numberFormat = new Intl.NumberFormat('cs-CZ');
  const moneyFormat = new Intl.NumberFormat('cs-CZ', { maximumFractionDigits: 0 });

  let dashboard = window.BZH_ANALYTICS_DASHBOARD || {};
  const period = window.BZH_ANALYTICS_PERIOD || '30d';
  const charts = {};

  function toNumber(value) {
    const number = Number(value || 0);
    return Number.isFinite(number) ? number : 0;
  }

  function chartData() {
    return dashboard.series || [];
  }

  function sourceData() {
    return (dashboard.sources || []).slice(0, 8);
  }

  function funnelData() {
    return dashboard.funnel || [];
  }

  function updateKpis() {
    const cards = dashboard.cards || {};
    document.querySelectorAll('[data-kpi]').forEach((el) => {
      const key = el.getAttribute('data-kpi');
      el.textContent = numberFormat.format(toNumber(cards[key]));
    });

    document.querySelectorAll('[data-kpi-money]').forEach((el) => {
      const key = el.getAttribute('data-kpi-money');
      el.textContent = moneyFormat.format(toNumber(cards[key]));
    });

    const generated = document.getElementById('generatedAt');
    if (generated && dashboard.generated_at) {
      generated.textContent = dashboard.generated_at;
    }
  }

  function createOrUpdateLineChart(id, configFactory) {
    const canvas = document.getElementById(id);
    if (!canvas || typeof Chart === 'undefined') return;
    const config = configFactory();

    if (charts[id]) {
      charts[id].data = config.data;
      charts[id].options = config.options;
      charts[id].update();
      return;
    }

    charts[id] = new Chart(canvas, config);
  }

  function renderCharts() {
    const series = chartData();

    createOrUpdateLineChart('trafficChart', () => ({
      type: 'line',
      data: {
        labels: series.map((row) => row.date),
        datasets: [
          {
            label: 'Reální uživatelé',
            data: series.map((row) => row.users),
            tension: 0.35,
            borderWidth: 3,
            pointRadius: 2
          },
          {
            label: 'Organika',
            data: series.map((row) => row.organic),
            tension: 0.35,
            borderWidth: 3,
            pointRadius: 2
          },
          {
            label: 'Produktové zobrazení',
            data: series.map((row) => row.product_views),
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'bottom' },
          tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${numberFormat.format(ctx.raw || 0)}` } }
        },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0 } }
        }
      }
    }));

    createOrUpdateLineChart('revenueChart', () => ({
      type: 'line',
      data: {
        labels: series.map((row) => row.date),
        datasets: [
          {
            label: 'Obrat Kč',
            data: series.map((row) => row.revenue),
            tension: 0.35,
            borderWidth: 3,
            yAxisID: 'y'
          },
          {
            label: 'Objednávky',
            data: series.map((row) => row.orders),
            tension: 0.35,
            borderWidth: 2,
            yAxisID: 'y1'
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'bottom' },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                if (ctx.dataset.label === 'Obrat Kč') return `Obrat: ${moneyFormat.format(ctx.raw || 0)} Kč`;
                return `Objednávky: ${numberFormat.format(ctx.raw || 0)}`;
              }
            }
          }
        },
        scales: {
          y: { beginAtZero: true, position: 'left' },
          y1: { beginAtZero: true, position: 'right', grid: { drawOnChartArea: false }, ticks: { precision: 0 } }
        }
      }
    }));

    const sources = sourceData();
    createOrUpdateLineChart('sourceChart', () => ({
      type: 'bar',
      data: {
        labels: sources.map((row) => `${row.source} / ${row.medium}`),
        datasets: [
          {
            label: 'Uživatelé',
            data: sources.map((row) => row.users),
            borderWidth: 1,
            borderRadius: 8
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y',
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => `Uživatelé: ${numberFormat.format(ctx.raw || 0)}` } }
        },
        scales: {
          x: { beginAtZero: true, ticks: { precision: 0 } }
        }
      }
    }));

    const funnel = funnelData();
    createOrUpdateLineChart('funnelChart', () => ({
      type: 'bar',
      data: {
        labels: funnel.map((row) => row.step),
        datasets: [
          {
            label: 'Počet',
            data: funnel.map((row) => row.value),
            borderRadius: 8
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y',
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => `Počet: ${numberFormat.format(ctx.raw || 0)}` } }
        },
        scales: {
          x: { beginAtZero: true, ticks: { precision: 0 } }
        }
      }
    }));
  }

  function initTableSorting() {
    document.querySelectorAll('[data-sort-table]').forEach((table) => {
      const headers = table.querySelectorAll('th');
      headers.forEach((header, index) => {
        header.addEventListener('click', () => {
          const tbody = table.tBodies[0];
          if (!tbody) return;
          const rows = Array.from(tbody.querySelectorAll('tr')).filter((row) => row.children.length > 1);
          const current = header.getAttribute('data-sort-direction') || 'desc';
          const next = current === 'asc' ? 'desc' : 'asc';

          headers.forEach((h) => h.removeAttribute('data-sort-direction'));
          header.setAttribute('data-sort-direction', next);

          rows.sort((a, b) => {
            const aCell = a.children[index];
            const bCell = b.children[index];
            const aRaw = aCell?.getAttribute('data-sort-value') || aCell?.innerText || '';
            const bRaw = bCell?.getAttribute('data-sort-value') || bCell?.innerText || '';
            const aNum = Number(String(aRaw).replace(/\s/g, '').replace(',', '.').replace(/[^\d.-]/g, ''));
            const bNum = Number(String(bRaw).replace(/\s/g, '').replace(',', '.').replace(/[^\d.-]/g, ''));

            if (!Number.isNaN(aNum) && !Number.isNaN(bNum)) {
              return next === 'asc' ? aNum - bNum : bNum - aNum;
            }

            return next === 'asc'
              ? String(aRaw).localeCompare(String(bRaw), 'cs')
              : String(bRaw).localeCompare(String(aRaw), 'cs');
          });

          rows.forEach((row) => tbody.appendChild(row));
        });
      });
    });
  }

  function initTableFilters() {
    document.querySelectorAll('[data-table-filter]').forEach((input) => {
      const selector = input.getAttribute('data-table-filter');
      const table = document.querySelector(selector);
      if (!table) return;

      input.addEventListener('input', () => {
        const query = input.value.trim().toLowerCase();
        table.querySelectorAll('tbody tr').forEach((row) => {
          row.style.display = row.innerText.toLowerCase().includes(query) ? '' : 'none';
        });
      });
    });
  }

  async function refreshDashboard() {
    try {
      const response = await fetch(`/api/analytics/stats?period=${encodeURIComponent(period)}`, {
        credentials: 'same-origin',
        headers: { 'Accept': 'application/json' }
      });
      if (!response.ok) return;
      dashboard = await response.json();
      updateKpis();
      renderCharts();
    } catch (error) {
      // Silent fallback: dashboard still works with server-rendered data.
    }
  }

  function initRealtime() {
    if (!window.EventSource) {
      setInterval(refreshDashboard, 12000);
      return;
    }

    try {
      const stream = new EventSource(`/api/analytics/realtime?period=${encodeURIComponent(period)}`);
      stream.onmessage = (event) => {
        try {
          dashboard = JSON.parse(event.data);
          updateKpis();
          renderCharts();
        } catch (error) {
          refreshDashboard();
        }
      };
      stream.onerror = () => {
        stream.close();
        setInterval(refreshDashboard, 15000);
      };
    } catch (error) {
      setInterval(refreshDashboard, 12000);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    updateKpis();
    renderCharts();
    initTableSorting();
    initTableFilters();
    initRealtime();
  });
})();
