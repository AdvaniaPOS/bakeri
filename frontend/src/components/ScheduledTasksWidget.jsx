import { useEffect, useState } from 'react';
import { CheckCircle, XCircle, Clock, RefreshCw, AlertTriangle } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

/**
 * Viser status for periodiske bakgrunnsjobber (Celery beat).
 * Brukt i Super-Admin-portalen for å bekrefte at f.eks. nattlig
 * ordregenerering kjørte som planlagt.
 */
const KNOWN_TASKS = {
  'app.tasks.generate_orders_for_all_customers': {
    label: 'Nattlig ordregenerering',
    schedule: 'Hver dag kl 02:00',
    metrics: [
      { key: 'customers_processed', label: 'Kunder behandlet' },
      { key: 'orders_created', label: 'Ordrer opprettet' },
      { key: 'errors', label: 'Feil', highlightIfPositive: true },
    ],
  },
  'app.tasks.sync_susoft_orders': {
    label: 'SuSoft ordresynk',
    schedule: 'Hver 60. minutt',
    metrics: [],
  },
  'app.tasks.lock_orders_at_cutoff': {
    label: 'Lås ordrer ved cut-off',
    schedule: 'Hver time',
    metrics: [],
  },
};

function formatRelative(iso) {
  if (!iso) return '—';
  const ts = new Date(iso);
  if (Number.isNaN(ts.getTime())) return iso;
  const diffMs = Date.now() - ts.getTime();
  const diffMin = Math.round(diffMs / 60000);
  if (diffMin < 1) return 'akkurat nå';
  if (diffMin < 60) return `for ${diffMin} min siden`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `for ${diffHr} t siden`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 7) return `for ${diffDay} d siden`;
  return ts.toLocaleString('no-NO');
}

function formatAbsolute(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('no-NO', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export default function ScheduledTasksWidget() {
  const { authFetch } = useAuth();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await authFetch('/api/v1/admin/scheduled-tasks/summary');
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${resp.status}`);
      }
      setRows(await resp.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // Gjør om listen til map for enkel oppslag, og vis ALLE kjente tasks
  // (også de som aldri har kjørt) slik at fravær er tydelig.
  const byName = Object.fromEntries(rows.map(r => [r.task_name, r]));

  const taskNames = Array.from(new Set([
    ...Object.keys(KNOWN_TASKS),
    ...rows.map(r => r.task_name),
  ]));

  return (
    <div className="card mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-gray-900 flex items-center gap-2">
          <Clock className="w-5 h-5" /> Bakgrunnsjobber (status)
        </h2>
        <button onClick={load} className="btn-secondary text-sm" disabled={loading}>
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Oppdater
        </button>
      </div>

      {error && (
        <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {taskNames.map(name => {
          const meta = KNOWN_TASKS[name] || { label: name, schedule: '', metrics: [] };
          const run = byName[name];
          const hasRun = !!run;
          const success = run?.success;

          return (
            <div key={name} className="border rounded-lg p-3 bg-white">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium text-gray-900">{meta.label}</div>
                  {meta.schedule && (
                    <div className="text-xs text-gray-500">{meta.schedule}</div>
                  )}
                </div>
                {!hasRun ? (
                  <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-gray-100 text-gray-600">
                    <AlertTriangle className="w-3 h-3" /> Aldri kjørt
                  </span>
                ) : success ? (
                  <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-green-100 text-green-700">
                    <CheckCircle className="w-3 h-3" /> OK
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-red-100 text-red-700">
                    <XCircle className="w-3 h-3" /> Feilet
                  </span>
                )}
              </div>

              {hasRun && (
                <div className="mt-2 space-y-1 text-sm">
                  <div className="text-gray-600">
                    Sist kjørt: <span className="text-gray-900">{formatRelative(run.started_at)}</span>
                    <span className="text-gray-400"> ({formatAbsolute(run.started_at)})</span>
                  </div>
                  {typeof run.duration_ms === 'number' && (
                    <div className="text-xs text-gray-500">
                      Varighet: {run.duration_ms < 1000
                        ? `${run.duration_ms} ms`
                        : `${(run.duration_ms / 1000).toFixed(1)} s`}
                    </div>
                  )}
                  {meta.metrics?.length > 0 && run.result && (
                    <div className="mt-2 grid grid-cols-3 gap-2">
                      {meta.metrics.map(m => {
                        const v = run.result?.[m.key];
                        const positive = m.highlightIfPositive && Number(v) > 0;
                        return (
                          <div
                            key={m.key}
                            className={`text-center p-2 rounded ${positive ? 'bg-red-50 border border-red-200' : 'bg-gray-50'}`}
                          >
                            <div className={`text-lg font-semibold ${positive ? 'text-red-700' : 'text-gray-900'}`}>
                              {v ?? '—'}
                            </div>
                            <div className="text-[11px] text-gray-500">{m.label}</div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {!meta.metrics?.length && run.result && (
                    <pre className="mt-2 text-xs bg-gray-50 p-2 rounded overflow-x-auto">
                      {JSON.stringify(run.result, null, 2)}
                    </pre>
                  )}
                  {run.error_message && (
                    <div className="mt-2 text-xs text-red-700 bg-red-50 border border-red-200 p-2 rounded">
                      {run.error_message}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
