import { useEffect, useState, useCallback } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Activity, RefreshCw, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';

function StatusBadge({ status }) {
  if (status === 'ok') return <span className="inline-flex items-center gap-1 text-green-700 bg-green-50 border border-green-200 px-2 py-0.5 rounded text-xs"><CheckCircle2 className="w-3 h-3" /> OK</span>;
  if (status === 'warning') return <span className="inline-flex items-center gap-1 text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded text-xs"><AlertTriangle className="w-3 h-3" /> Advarsel</span>;
  if (status === 'disabled') return <span className="inline-flex items-center gap-1 text-gray-600 bg-gray-50 border border-gray-200 px-2 py-0.5 rounded text-xs">Deaktivert</span>;
  return <span className="inline-flex items-center gap-1 text-red-700 bg-red-50 border border-red-200 px-2 py-0.5 rounded text-xs"><XCircle className="w-3 h-3" /> Feil</span>;
}

export default function Status() {
  const { authFetch } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await authFetch('/api/v1/health/detailed');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setData(await resp.json());
    } catch (e) {
      setError(e.message || 'Kunne ikke hente status');
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Activity className="w-6 h-6" /> Systemstatus
        </h1>
        <button
          onClick={load}
          disabled={loading}
          className="px-3 py-1.5 text-sm bg-amber-600 text-white rounded hover:bg-amber-700 flex items-center gap-2 disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Oppdater
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 rounded p-3 text-sm">{error}</div>
      )}

      {data && (
        <div className="bg-white border rounded p-4 space-y-3">
          <div className="flex items-center justify-between border-b pb-3">
            <div className="font-semibold">Samlet status</div>
            <StatusBadge status={data.status === 'healthy' ? 'ok' : 'warning'} />
          </div>
          {Object.entries(data.checks || {}).map(([name, check]) => (
            <div key={name} className="flex items-center justify-between">
              <div>
                <div className="font-medium capitalize">{name}</div>
                {check.error && <div className="text-xs text-red-600 mt-0.5">{check.error}</div>}
                {check.detail && <div className="text-xs text-gray-500 mt-0.5">{check.detail}</div>}
                {check.provider && <div className="text-xs text-gray-500 mt-0.5">Provider: {check.provider}</div>}
              </div>
              <StatusBadge status={check.status} />
            </div>
          ))}
        </div>
      )}

      <p className="text-xs text-gray-500">Oppdateres automatisk hvert 30. sekund.</p>
    </div>
  );
}
