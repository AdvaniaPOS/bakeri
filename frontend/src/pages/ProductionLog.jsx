import { useState, useEffect, useCallback } from 'react';
import { Calendar, RefreshCw, Save, AlertTriangle, Loader2, TrendingDown, FileText } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { openPdf } from '../utils/pdf';

function formatDateISO(d) {
  const yr = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const da = String(d.getDate()).padStart(2, '0');
  return `${yr}-${mo}-${da}`;
}

function todayISO() {
  return formatDateISO(new Date());
}

const EMPTY_ROW = {
  actual_qty: 0,
  waste_returned: 0,
  waste_burnt: 0,
  waste_quality: 0,
  waste_other: 0,
  notes: '',
};

export default function ProductionLog() {
  const { authFetch } = useAuth();
  const [date, setDate] = useState(todayISO());
  const [data, setData] = useState(null);
  const [edits, setEdits] = useState({}); // { product_id: {actual_qty, waste_*, notes} }
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedAt, setSavedAt] = useState(null);
  // Periode for svinn-PDF (default: siste 30 dager)
  const [pdfFrom, setPdfFrom] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 30); return formatDateISO(d);
  });
  const [pdfTo, setPdfTo] = useState(todayISO());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await authFetch(`/api/v1/production/${date}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      setData(j);
      // Init edits fra serverens nåverdier
      const init = {};
      for (const row of j.rows) {
        init[row.product_id] = {
          actual_qty: row.actual_qty,
          waste_returned: row.waste_returned,
          waste_burnt: row.waste_burnt,
          waste_quality: row.waste_quality,
          waste_other: row.waste_other,
          notes: row.notes || '',
        };
      }
      setEdits(init);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [authFetch, date]);

  useEffect(() => { load(); }, [load]);

  const updateField = (pid, field, value) => {
    setEdits((prev) => ({
      ...prev,
      [pid]: {
        ...(prev[pid] || EMPTY_ROW),
        [field]: field === 'notes' ? value : Math.max(0, parseInt(value || '0', 10) || 0),
      },
    }));
  };

  const computed = (pid) => {
    const e = edits[pid] || EMPTY_ROW;
    const tw = (e.waste_returned || 0) + (e.waste_burnt || 0)
      + (e.waste_quality || 0) + (e.waste_other || 0);
    const sold = Math.max((e.actual_qty || 0) - tw, 0);
    const pct = e.actual_qty > 0 ? Math.round((tw / e.actual_qty) * 1000) / 10 : 0;
    return { totalWaste: tw, sold, pct };
  };

  const save = async () => {
    if (!data) return;
    setSaving(true);
    setError(null);
    try {
      const rows = data.rows.map((r) => ({
        product_id: r.product_id,
        ...(edits[r.product_id] || EMPTY_ROW),
      }));
      const r = await authFetch(`/api/v1/production/${date}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rows }),
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(`HTTP ${r.status}: ${txt}`);
      }
      const j = await r.json();
      setData(j);
      setSavedAt(new Date());
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 flex items-center gap-2">
            <TrendingDown className="w-6 h-6 text-amber-600" />
            Faktisk produksjon &amp; svinn
          </h1>
          <p className="text-sm text-gray-600 mt-1">
            Registrer hva som faktisk ble produsert og hvor mye som ble kassert.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-gray-500" />
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="border border-gray-300 rounded-md px-3 py-1.5 text-sm"
            />
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="btn-secondary flex items-center gap-1.5"
            title="Last på nytt"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={save}
            disabled={saving || loading || !data || data.rows.length === 0}
            className="btn-primary flex items-center gap-1.5"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Lagre
          </button>
        </div>
      </div>

      {/* Svinn-PDF for periode */}
      <div className="bg-white border border-gray-200 rounded-lg p-3 mb-4 flex items-center gap-3 flex-wrap">
        <FileText className="w-4 h-4 text-gray-500" />
        <span className="text-sm text-gray-700 font-medium">Svinnrapport (PDF):</span>
        <input
          type="date"
          value={pdfFrom}
          onChange={(e) => setPdfFrom(e.target.value)}
          className="border border-gray-300 rounded-md px-2 py-1 text-sm"
        />
        <span className="text-gray-400">–</span>
        <input
          type="date"
          value={pdfTo}
          onChange={(e) => setPdfTo(e.target.value)}
          className="border border-gray-300 rounded-md px-2 py-1 text-sm"
        />
        <button
          className="btn-secondary text-sm"
          onClick={() => openPdf(authFetch, `/api/v1/production/pdf/waste?from_date=${pdfFrom}&to_date=${pdfTo}`)}
        >
          Last ned
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 rounded-md p-3 mb-4 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      {savedAt && !error && (
        <div className="bg-green-50 border border-green-200 text-green-800 rounded-md p-3 mb-4 text-sm">
          Lagret kl {savedAt.toLocaleTimeString('nb-NO')}
        </div>
      )}

      {data && data.rows.length === 0 && !loading && (
        <div className="bg-white border border-gray-200 rounded-lg p-8 text-center text-gray-500">
          Ingen produkter planlagt eller registrert for denne datoen.
        </div>
      )}

      {data && data.rows.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr className="text-left text-xs font-medium text-gray-600 uppercase tracking-wide">
                  <th className="px-3 py-2.5">Produkt</th>
                  <th className="px-3 py-2.5 text-right">Planlagt</th>
                  <th className="px-3 py-2.5 text-right">Faktisk</th>
                  <th className="px-3 py-2.5 text-right" title="Returnert fra kunde">Retur</th>
                  <th className="px-3 py-2.5 text-right" title="Brent / feilprodusert">Brent</th>
                  <th className="px-3 py-2.5 text-right" title="Kassert grunnet kvalitet">Kvalitet</th>
                  <th className="px-3 py-2.5 text-right" title="Annen kassasjon">Annet</th>
                  <th className="px-3 py-2.5 text-right">Sum svinn</th>
                  <th className="px-3 py-2.5 text-right">Solgt</th>
                  <th className="px-3 py-2.5 text-right">Svinn %</th>
                  <th className="px-3 py-2.5">Notater</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.rows.map((row) => {
                  const e = edits[row.product_id] || EMPTY_ROW;
                  const c = computed(row.product_id);
                  const pctClass = c.pct >= 10 ? 'text-red-600 font-semibold'
                    : c.pct >= 5 ? 'text-amber-600' : 'text-gray-700';
                  return (
                    <tr key={row.product_id} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-medium text-gray-900">
                        {row.product_name}
                        <span className="ml-1 text-xs text-gray-400">({row.unit})</span>
                      </td>
                      <td className="px-3 py-2 text-right text-gray-700">{row.planned_qty}</td>
                      <NumCell value={e.actual_qty} onChange={(v) => updateField(row.product_id, 'actual_qty', v)} />
                      <NumCell value={e.waste_returned} onChange={(v) => updateField(row.product_id, 'waste_returned', v)} />
                      <NumCell value={e.waste_burnt} onChange={(v) => updateField(row.product_id, 'waste_burnt', v)} />
                      <NumCell value={e.waste_quality} onChange={(v) => updateField(row.product_id, 'waste_quality', v)} />
                      <NumCell value={e.waste_other} onChange={(v) => updateField(row.product_id, 'waste_other', v)} />
                      <td className="px-3 py-2 text-right text-gray-700">{c.totalWaste}</td>
                      <td className="px-3 py-2 text-right font-medium text-gray-900">{c.sold}</td>
                      <td className={`px-3 py-2 text-right ${pctClass}`}>{c.pct}%</td>
                      <td className="px-3 py-2">
                        <input
                          type="text"
                          value={e.notes}
                          onChange={(ev) => updateField(row.product_id, 'notes', ev.target.value)}
                          placeholder="…"
                          className="w-full border border-gray-200 rounded px-2 py-1 text-xs"
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot className="bg-gray-50 border-t border-gray-200 font-medium text-gray-800">
                <tr>
                  <td className="px-3 py-2">Total</td>
                  <td className="px-3 py-2 text-right">{data.total_planned}</td>
                  <td className="px-3 py-2 text-right">
                    {data.rows.reduce((s, r) => s + (edits[r.product_id]?.actual_qty || 0), 0)}
                  </td>
                  <td colSpan={4}></td>
                  <td className="px-3 py-2 text-right">
                    {data.rows.reduce((s, r) => s + computed(r.product_id).totalWaste, 0)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {data.rows.reduce((s, r) => s + computed(r.product_id).sold, 0)}
                  </td>
                  <td colSpan={2}></td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function NumCell({ value, onChange }) {
  return (
    <td className="px-1 py-1.5 text-right">
      <input
        type="number"
        min="0"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-16 border border-gray-200 rounded px-1.5 py-1 text-right text-sm"
      />
    </td>
  );
}
