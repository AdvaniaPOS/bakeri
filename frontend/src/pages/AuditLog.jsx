import { useEffect, useState, useCallback, Fragment } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { History, Filter, RefreshCw } from 'lucide-react';

const ACTIONS = [
  '', 'CREATE', 'UPDATE', 'DELETE', 'PANIC_CANCEL', 'PRICE_CHANGE',
  'TEMPLATE_APPLY', 'SYNC', 'LOGIN', 'LOGOUT'
];

function formatTs(ts) {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleString('nb-NO');
  } catch {
    return ts;
  }
}

function ActionBadge({ action }) {
  const colors = {
    DELETE: 'bg-red-100 text-red-800',
    CREATE: 'bg-green-100 text-green-800',
    UPDATE: 'bg-blue-100 text-blue-800',
    PANIC_CANCEL: 'bg-red-200 text-red-900 font-bold',
    PRICE_CHANGE: 'bg-amber-100 text-amber-800',
  };
  const cls = colors[action] || 'bg-gray-100 text-gray-800';
  return <span className={`px-2 py-0.5 rounded text-xs ${cls}`}>{action}</span>;
}

export default function AuditLog() {
  const { authFetch } = useAuth();
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    action: '',
    entity_type: '',
    entity_id: '',
    user_id: '',
    from_date: '',
    to_date: '',
  });
  const [expanded, setExpanded] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: '50' });
      Object.entries(filters).forEach(([k, v]) => {
        if (v) params.set(k, v);
      });
      const resp = await authFetch(`/api/v1/admin/audit-logs?${params.toString()}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setLogs(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e.message || 'Kunne ikke hente audit-logg');
    } finally {
      setLoading(false);
    }
  }, [authFetch, page, filters]);

  useEffect(() => {
    load();
  }, [load]);

  function updateFilter(key, value) {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(1);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <History className="w-6 h-6" /> Audit-logg
        </h1>
        <button
          onClick={load}
          className="px-3 py-1.5 text-sm bg-amber-600 text-white rounded hover:bg-amber-700 flex items-center gap-2"
        >
          <RefreshCw className="w-4 h-4" /> Oppdater
        </button>
      </div>

      <div className="bg-white border rounded p-4">
        <div className="flex items-center gap-2 mb-3 text-sm font-semibold text-gray-700">
          <Filter className="w-4 h-4" /> Filtre
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <select
            value={filters.action}
            onChange={(e) => updateFilter('action', e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          >
            {ACTIONS.map((a) => (
              <option key={a} value={a}>{a || 'Alle handlinger'}</option>
            ))}
          </select>
          <input
            type="text"
            placeholder="Entity type"
            value={filters.entity_type}
            onChange={(e) => updateFilter('entity_type', e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          />
          <input
            type="number"
            placeholder="Entity ID"
            value={filters.entity_id}
            onChange={(e) => updateFilter('entity_id', e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          />
          <input
            type="number"
            placeholder="User ID"
            value={filters.user_id}
            onChange={(e) => updateFilter('user_id', e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          />
          <input
            type="datetime-local"
            value={filters.from_date}
            onChange={(e) => updateFilter('from_date', e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          />
          <input
            type="datetime-local"
            value={filters.to_date}
            onChange={(e) => updateFilter('to_date', e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          />
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 rounded p-3 text-sm">{error}</div>
      )}

      <div className="bg-white border rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-3 py-2">Tid</th>
              <th className="px-3 py-2">Bruker</th>
              <th className="px-3 py-2">Handling</th>
              <th className="px-3 py-2">Entitet</th>
              <th className="px-3 py-2">ID</th>
              <th className="px-3 py-2">Detaljer</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-500">Laster…</td></tr>
            )}
            {!loading && logs.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-500">Ingen oppføringer</td></tr>
            )}
            {logs.map((log) => (
              <Fragment key={log.id}>
                <tr className="border-t hover:bg-gray-50">
                  <td className="px-3 py-2 whitespace-nowrap">{formatTs(log.timestamp)}</td>
                  <td className="px-3 py-2">{log.user_email || log.user_id || '—'}</td>
                  <td className="px-3 py-2"><ActionBadge action={log.action} /></td>
                  <td className="px-3 py-2">{log.entity_type}</td>
                  <td className="px-3 py-2">{log.entity_id}</td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => setExpanded(expanded === log.id ? null : log.id)}
                      className="text-amber-700 hover:underline text-xs"
                    >
                      {expanded === log.id ? 'Skjul' : 'Vis'}
                    </button>
                  </td>
                </tr>
                {expanded === log.id && (
                  <tr className="bg-gray-50 border-t">
                    <td colSpan={6} className="px-3 py-3">
                      {log.deletion_reason_category && (
                        <div className="mb-2 text-xs">
                          <strong>Slettegrunn:</strong> {log.deletion_reason_category}
                          {log.deletion_reason_text && ` — ${log.deletion_reason_text}`}
                        </div>
                      )}
                      <div className="grid grid-cols-2 gap-3 text-xs">
                        <div>
                          <div className="font-semibold mb-1">Gamle verdier</div>
                          <pre className="bg-white border rounded p-2 overflow-auto max-h-48">{JSON.stringify(log.old_values, null, 2)}</pre>
                        </div>
                        <div>
                          <div className="font-semibold mb-1">Nye verdier</div>
                          <pre className="bg-white border rounded p-2 overflow-auto max-h-48">{JSON.stringify(log.new_values, null, 2)}</pre>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-sm">
        <div>Side {page}</div>
        <div className="flex gap-2">
          <button
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="px-3 py-1 border rounded disabled:opacity-50"
          >Forrige</button>
          <button
            disabled={loading || logs.length < 50}
            onClick={() => setPage((p) => p + 1)}
            className="px-3 py-1 border rounded disabled:opacity-50"
          >Neste</button>
        </div>
      </div>
    </div>
  );
}
