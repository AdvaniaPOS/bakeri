import { useEffect, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';

const API_BASE = '/api/v1';

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('no-NO', { weekday: 'short', day: '2-digit', month: 'short' });
}

function statusLabel(s) {
  const map = {
    pending: 'Foreslått',
    confirmed: 'Bekreftet',
    in_production: 'I produksjon',
    ready_for_delivery: 'Klar for levering',
    delivered: 'Levert',
    cancelled: 'Kansellert',
  };
  return map[s] || s;
}

export default function PortalDashboard() {
  const { me } = useOutletContext();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!token) return;
    setLoading(true);
    const today = new Date().toISOString().slice(0, 10);
    const to = new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10);
    fetch(`${API_BASE}/portal/orders?from_date=${today}&to_date=${to}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => {
        if (!r.ok) throw new Error('Klarte ikke laste bestillinger');
        return r.json();
      })
      .then(data => setOrders(data || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Gruppér ordrer pr. utsalg
  const outletMap = new Map((me?.outlets || []).map(o => [o.id, o]));
  const grouped = orders.reduce((acc, o) => {
    const key = o.customer_id;
    if (!acc[key]) acc[key] = [];
    acc[key].push(o);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-amber-900">Kommende bestillinger</h1>
        <Link
          to="/portal/ny"
          className="bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 rounded-md text-sm font-medium shadow-sm"
        >
          + Ny bestilling
        </Link>
      </div>

      {loading && <div className="text-gray-600">Laster…</div>}
      {error && <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">{error}</div>}

      {!loading && !error && orders.length === 0 && (
        <div className="bg-white rounded-lg border border-amber-200 p-8 text-center">
          <div className="text-4xl mb-3">📋</div>
          <div className="text-gray-700 mb-4">Ingen kommende bestillinger</div>
          <Link
            to="/portal/ny"
            className="inline-block bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 rounded-md text-sm font-medium"
          >
            Legg inn første bestilling
          </Link>
        </div>
      )}

      {(me?.outlets || []).map(outlet => {
        const list = grouped[outlet.id] || [];
        if (list.length === 0 && me.outlets.length > 1) {
          return (
            <section key={outlet.id} className="bg-white rounded-lg border border-amber-200 p-4">
              <h2 className="font-semibold text-amber-900">
                {outlet.name} {outlet.is_main && <span className="text-xs text-amber-700">(hovedutsalg)</span>}
              </h2>
              <div className="text-sm text-gray-500 mt-2">Ingen kommende bestillinger</div>
            </section>
          );
        }
        if (list.length === 0) return null;
        return (
          <section key={outlet.id} className="bg-white rounded-lg border border-amber-200 overflow-hidden">
            <div className="bg-amber-100 px-4 py-2 border-b border-amber-200">
              <h2 className="font-semibold text-amber-900">
                {outlet.name} {outlet.is_main && me.outlets.length > 1 && (
                  <span className="text-xs text-amber-700 font-normal">(hovedutsalg)</span>
                )}
              </h2>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-amber-50 text-left text-xs uppercase text-amber-800">
                <tr>
                  <th className="px-3 py-2">Lev.dato</th>
                  <th className="px-3 py-2">Ordrenr</th>
                  <th className="px-3 py-2">Ref.</th>
                  <th className="px-3 py-2 text-right">Antall linjer</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {list.map(o => (
                  <tr key={o.id} className="border-t border-amber-100">
                    <td className="px-3 py-2">{fmtDate(o.delivery_date)}</td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {o.order_no_display || `ORD-${o.id}`}
                    </td>
                    <td className="px-3 py-2 text-gray-700">{o.reference || '—'}</td>
                    <td className="px-3 py-2 text-right">{o.lines?.length ?? 0}</td>
                    <td className="px-3 py-2">
                      <span className="inline-block px-2 py-0.5 text-xs rounded bg-amber-100 text-amber-800">
                        {statusLabel(o.status)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        );
      })}
    </div>
  );
}
