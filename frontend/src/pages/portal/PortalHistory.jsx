import { useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';

const API_BASE = '/api/v1';

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('no-NO', { day: '2-digit', month: 'short', year: 'numeric' });
}

export default function PortalHistory() {
  const { me } = useOutletContext();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [outletFilter, setOutletFilter] = useState('all');
  const [error, setError] = useState(null);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!token) return;
    setLoading(true);
    const today = new Date().toISOString().slice(0, 10);
    const from = new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10);
    fetch(`${API_BASE}/portal/orders?from_date=${from}&to_date=${today}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : [])
      .then(data => setOrders(data || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = outletFilter === 'all'
    ? orders
    : orders.filter(o => o.customer_id === Number(outletFilter));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-amber-900">Historikk (siste 90 dager)</h1>
        {me?.outlets?.length > 1 && (
          <select
            value={outletFilter}
            onChange={(e) => setOutletFilter(e.target.value)}
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm"
          >
            <option value="all">Alle utsalg</option>
            {me.outlets.map(o => (
              <option key={o.id} value={o.id}>{o.name}</option>
            ))}
          </select>
        )}
      </div>

      {loading && <div className="text-gray-600">Laster…</div>}
      {error && <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">{error}</div>}

      {!loading && filtered.length === 0 && (
        <div className="bg-white border border-amber-200 rounded-lg p-6 text-center text-gray-600">
          Ingen tidligere bestillinger funnet
        </div>
      )}

      {!loading && filtered.length > 0 && (
        <div className="bg-white border border-amber-200 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-amber-50 text-xs uppercase text-amber-800 text-left">
              <tr>
                <th className="px-3 py-2">Lev.dato</th>
                <th className="px-3 py-2">Ordrenr</th>
                <th className="px-3 py-2">Utsalg</th>
                <th className="px-3 py-2">Ref.</th>
                <th className="px-3 py-2 text-right">Linjer</th>
                <th className="px-3 py-2 text-right">Sum (eks. mva)</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(o => (
                <tr key={o.id} className="border-t border-amber-100">
                  <td className="px-3 py-2">{fmtDate(o.delivery_date)}</td>
                  <td className="px-3 py-2 font-mono text-xs">{o.order_no_display || `ORD-${o.id}`}</td>
                  <td className="px-3 py-2">{o.customer_name}</td>
                  <td className="px-3 py-2 text-gray-700">{o.reference || '—'}</td>
                  <td className="px-3 py-2 text-right">{o.lines?.length ?? 0}</td>
                  <td className="px-3 py-2 text-right">
                    {Number(o.total_amount_excl_vat || 0).toFixed(2)} kr
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
