def dashboard_html() -> str:
    # Tailwind via CDN for quick local dashboard styling
    return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Receivables Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="bg-slate-50">
    <div class="max-w-[1400px] mx-auto p-6">
      <div class="flex items-start justify-between gap-4">
        <div>
          <h1 id="reportTitle" class="text-2xl font-semibold text-slate-900">Receivables Dashboard</h1>
          <p id="reportSub" class="text-sm text-slate-600 mt-1"></p>
        </div>
        <div class="flex items-center gap-2">
          <button id="undoBtn" class="px-3 py-2 rounded bg-white border text-slate-800 hover:bg-slate-100 disabled:opacity-50" disabled>
            Undo last move
          </button>
          <button id="resetBtn" class="px-3 py-2 rounded bg-white border text-slate-800 hover:bg-slate-100">
            Reset all changes
          </button>
          <div class="w-px h-8 bg-slate-300 mx-1"></div>
          <a id="exportCsv" class="px-3 py-2 rounded bg-white border text-slate-800 hover:bg-slate-100" href="#">Export CSV</a>
          <a id="exportXlsx" class="px-3 py-2 rounded bg-white border text-slate-800 hover:bg-slate-100" href="#">Export Excel</a>
          <a id="exportJson" class="px-3 py-2 rounded bg-white border text-slate-800 hover:bg-slate-100" href="#">Export JSON</a>
          <a id="exportPdf" class="px-3 py-2 rounded bg-slate-900 text-white hover:bg-slate-800" href="#">Export PDF</a>
        </div>
      </div>

      <div class="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
        <div class="bg-white border rounded p-3">
          <div class="text-xs text-slate-500">Rows</div>
          <div id="rowsCount" class="text-xl font-semibold text-slate-900">0</div>
        </div>
        <div class="bg-white border rounded p-3">
          <div class="text-xs text-slate-500">Regions detected</div>
          <div id="regions" class="text-sm text-slate-900 mt-1"></div>
        </div>
        <div class="bg-white border rounded p-3">
          <div class="text-xs text-slate-500">Total value</div>
          <div id="totalValue" class="text-xl font-semibold text-slate-900">0.00</div>
        </div>
      </div>

      <div class="mt-6 flex items-center justify-between gap-3">
        <div class="flex items-center gap-2">
          <label class="text-sm text-slate-700">Region</label>
          <select id="regionFilter" class="border rounded px-2 py-1 bg-white text-sm">
            <option value="">All</option>
          </select>
          <input id="searchBox" class="border rounded px-3 py-1 bg-white text-sm w-[360px]" placeholder="Search customer..." />
        </div>
        <div class="text-xs text-slate-600">
          Tip: click an amount cell to select it, then click another bucket to move the full amount. Hold <b>Shift</b> to enter partial amount.
        </div>
      </div>

      <div class="mt-3 bg-white border rounded overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead class="bg-slate-100 text-slate-700">
            <tr>
              <th class="text-left px-3 py-2">Customer</th>
              <th class="text-left px-3 py-2">Region</th>
              <th class="text-left px-3 py-2">Payment Status</th>
              <th class="text-right px-3 py-2">SAFE</th>
              <th class="text-right px-3 py-2">WARNING</th>
              <th class="text-right px-3 py-2">DANGER</th>
              <th class="text-right px-3 py-2">DOUBTFUL</th>
              <th class="text-right px-3 py-2">TOTAL</th>
            </tr>
          </thead>
          <tbody id="tbody" class="divide-y"></tbody>
        </table>
      </div>
    </div>

    <script>
      const reportId = window.location.pathname.split('/').pop();
      const undoStack = [];
      let originalRows = [];
      let rows = [];
      let selectedMove = null; // {rowId, from}

      function fmt(n) {
        return (Number(n || 0)).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
      }

      function recalcRow(r) {
        r.total = Number(r.safe) + Number(r.warning) + Number(r.danger) + Number(r.doubtful);
      }

      function setUndoEnabled() {
        document.getElementById('undoBtn').disabled = undoStack.length === 0;
      }

      function applyFilters(list) {
        const region = document.getElementById('regionFilter').value;
        const q = document.getElementById('searchBox').value.trim().toLowerCase();
        return list.filter(r => {
          if (region && r.region !== region) return false;
          if (q && !(r.customer_name || '').toLowerCase().includes(q)) return false;
          return true;
        });
      }

      function render() {
        const tbody = document.getElementById('tbody');
        tbody.innerHTML = '';
        const filtered = applyFilters(rows).sort((a, b) => {
          if (a.region === b.region) {
            return (a.customer_name || '').localeCompare(b.customer_name || '');
          }
          return (a.region || '').localeCompare(b.region || '');
        });
        let lastRegion = null;
        for (const r of filtered) {
          if (r.region !== lastRegion) {
            lastRegion = r.region;
            const hdr = document.createElement('tr');
            hdr.innerHTML = `
              <td colspan="8" class="px-3 py-2 bg-slate-50 text-slate-800 font-semibold">
                ${r.region} Customers
              </td>
            `;
            tbody.appendChild(hdr);
          }
          const tr = document.createElement('tr');

          const paymentSelect = `
            <select data-row="${r.id}" class="border rounded px-2 py-1 bg-white text-sm">
              <option ${r.payment_status === 'Unpaid' ? 'selected' : ''}>Unpaid</option>
              <option ${r.payment_status === 'Partially Paid' ? 'selected' : ''}>Partially Paid</option>
              <option ${r.payment_status === 'Paid' ? 'selected' : ''}>Paid</option>
            </select>`;

          tr.innerHTML = `
            <td class="px-3 py-2 text-slate-900">${r.customer_name}</td>
            <td class="px-3 py-2 text-slate-700">${r.region}</td>
            <td class="px-3 py-2">${paymentSelect}</td>
            ${bucketCell(r, 'safe', 'SAFE')}
            ${bucketCell(r, 'warning', 'WARNING')}
            ${bucketCell(r, 'danger', 'DANGER')}
            ${bucketCell(r, 'doubtful', 'DOUBTFUL')}
            <td class="px-3 py-2 text-right font-semibold text-slate-900">${fmt(r.total)}</td>
          `;
          tbody.appendChild(tr);
        }

        tbody.querySelectorAll('select[data-row]').forEach(sel => {
          sel.addEventListener('change', async (e) => {
            const rowId = e.target.getAttribute('data-row');
            const value = e.target.value;
            const row = rows.find(x => String(x.id) === String(rowId));
            if (!row) return;
            const before = {...row};
            row.payment_status = value;
            undoStack.push({type: 'payment', rowId, before});
            setUndoEnabled();
            await fetch(`/rows/${rowId}/payment-status`, {
              method: 'PATCH',
              headers: {'Content-Type':'application/json'},
              body: JSON.stringify({payment_status: value})
            });
          });
        });
      }

      function bucketCell(r, key, label) {
        const isSelected = selectedMove && String(selectedMove.rowId) === String(r.id) && selectedMove.from === key;
        const cls = isSelected ? 'bg-amber-50 ring-1 ring-amber-400' : 'hover:bg-slate-50';
        return `
          <td class="px-3 py-2 text-right cursor-pointer ${cls}"
              data-row="${r.id}" data-bucket="${key}">
              ${fmt(r[key])}
          </td>`;
      }

      async function doMove(rowId, from, to, amount) {
        const row = rows.find(r => String(r.id) === String(rowId));
        if (!row) return;
        if (from === to) return;

        const maxAmount = Number(row[from] || 0);
        const amt = Math.max(0, Math.min(Number(amount), maxAmount));
        if (!amt) return;

        const before = {...row};
        row[from] = Number(row[from]) - amt;
        row[to] = Number(row[to]) + amt;
        recalcRow(row);
        undoStack.push({type: 'move', rowId, before});
        setUndoEnabled();
        render();

        await fetch(`/rows/${rowId}/move`, {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({from_bucket: from, to_bucket: to, amount: amt})
        });
      }

      document.addEventListener('click', async (e) => {
        const cell = e.target.closest('td[data-row][data-bucket]');
        if (!cell) return;
        const rowId = cell.getAttribute('data-row');
        const bucket = cell.getAttribute('data-bucket');
        const row = rows.find(r => String(r.id) === String(rowId));
        if (!row) return;

        if (!selectedMove) {
          selectedMove = {rowId, from: bucket};
          render();
          return;
        }

        const from = selectedMove.from;
        const to = bucket;
        const fromRowId = selectedMove.rowId;
        selectedMove = null;

        if (String(fromRowId) !== String(rowId)) {
          // Only move within a row
          render();
          return;
        }

        const full = Number(row[from] || 0);
        let amt = full;
        if (e.shiftKey) {
          const input = prompt(`Move how much from ${from.toUpperCase()} to ${to.toUpperCase()}?`, String(full));
          if (input === null) { render(); return; }
          amt = Number(String(input).replace(/,/g,'')) || 0;
        }
        await doMove(rowId, from, to, amt);
      });

      document.getElementById('undoBtn').addEventListener('click', async () => {
        const op = undoStack.pop();
        setUndoEnabled();
        if (!op) return;

        const row = rows.find(r => String(r.id) === String(op.rowId));
        if (!row) return;
        Object.assign(row, op.before);
        render();

        // Persist by sending a full-row reset via move endpoint with 0? We'll use reset-row.
        await fetch(`/rows/${op.rowId}/set`, {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({
            payment_status: row.payment_status,
            safe: row.safe, warning: row.warning, danger: row.danger, doubtful: row.doubtful
          })
        });
      });

      document.getElementById('resetBtn').addEventListener('click', async () => {
        if (!confirm('Reset all changes for this report?')) return;
        await fetch(`/reports/${reportId}/reset`, {method:'POST'});
        await load();
        undoStack.length = 0;
        setUndoEnabled();
      });

      async function load() {
        const meta = await fetch(`/reports/${reportId}`).then(r => r.json());
        document.getElementById('reportTitle').textContent = meta.header || 'Receivables Dashboard';
        document.getElementById('reportSub').textContent = [meta.filename, meta.date_range].filter(Boolean).join(' • ');
        document.getElementById('exportCsv').href = `/reports/${reportId}/export/csv`;
        document.getElementById('exportXlsx').href = `/reports/${reportId}/export/xlsx`;
        document.getElementById('exportJson').href = `/reports/${reportId}/export/json`;
        document.getElementById('exportPdf').href = `/reports/${reportId}/export/pdf`;

        rows = await fetch(`/reports/${reportId}/rows`).then(r => r.json());
        for (const r of rows) recalcRow(r);
        document.getElementById('rowsCount').textContent = rows.length;
        const regions = Array.from(new Set(rows.map(r => r.region))).sort();
        document.getElementById('regions').textContent = regions.join(', ');

        const sum = rows.reduce((acc, r) => acc + Number(r.total||0), 0);
        document.getElementById('totalValue').textContent = fmt(sum);

        const sel = document.getElementById('regionFilter');
        sel.innerHTML = '<option value=\"\">All</option>' + regions.map(r => `<option>${r}</option>`).join('');

        render();
      }

      document.getElementById('regionFilter').addEventListener('change', render);
      document.getElementById('searchBox').addEventListener('input', render);

      load();
    </script>
  </body>
</html>
"""

