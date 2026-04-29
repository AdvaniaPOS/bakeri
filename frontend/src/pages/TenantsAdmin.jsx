import { useState, useEffect } from 'react';
import { Building2, Plus, RefreshCw, CheckCircle, XCircle, AlertCircle } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

const EMPTY_FORM = {
  name: '',
  slug: '',
  email: '',
  legal_name: '',
  org_number: '',
  admin_email: '',
  admin_password: '',
  admin_first_name: '',
  admin_last_name: '',
  susoft_api_url: 'https://api.susoft.com:4443',
  susoft_login: '',
  susoft_password: '',
  susoft_shop_url_key: '',
};

export default function TenantsAdmin() {
  const { authFetch, user } = useAuth();
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);

  const isSuperAdmin = user?.role === 'SUPER_ADMIN';

  const loadTenants = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await authFetch('/api/v1/admin/tenants');
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${resp.status}`);
      }
      setTenants(await resp.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isSuperAdmin) loadTenants();
    else setLoading(false);
  }, [isSuperAdmin]);

  const submit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const payload = { ...form };
      Object.keys(payload).forEach(k => { if (payload[k] === '') delete payload[k]; });
      const resp = await authFetch('/api/v1/admin/tenants', { method: 'POST', body: payload });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
      setForm(EMPTY_FORM);
      setShowForm(false);
      loadTenants();
    } catch (e) {
      setFormError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (!isSuperAdmin) {
    return (
      <div className="p-8 max-w-4xl">
        <div className="card bg-yellow-50 border-yellow-200">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-6 h-6 text-yellow-600" />
            <div>
              <h2 className="font-semibold text-yellow-900">Ikke tilgang</h2>
              <p className="text-sm text-yellow-800">Denne siden er kun for super-admin.</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <div className="page-header">
        <div>
          <h1 className="page-title">Kunder / Portaler</h1>
          <p className="page-subtitle">Administrer tenants i systemet</p>
        </div>
        <div className="flex gap-2">
          <button onClick={loadTenants} className="btn-secondary">
            <RefreshCw className="w-4 h-4" /> Oppdater
          </button>
          <button onClick={() => setShowForm(s => !s)} className="btn-primary">
            <Plus className="w-4 h-4" /> Ny tenant
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">{error}</div>
      )}

      {showForm && (
        <form onSubmit={submit} className="card mb-6 space-y-4">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <Building2 className="w-5 h-5" /> Opprett ny tenant
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Navn *</label>
              <input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="input" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Slug * <span className="text-xs text-gray-400">(a-z, 0-9, -)</span></label>
              <input required pattern="[a-z0-9-]+" value={form.slug} onChange={e => setForm({ ...form, slug: e.target.value })} className="input" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Juridisk navn</label>
              <input value={form.legal_name} onChange={e => setForm({ ...form, legal_name: e.target.value })} className="input" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Org.nr</label>
              <input value={form.org_number} onChange={e => setForm({ ...form, org_number: e.target.value })} className="input" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Kontakt-epost</label>
              <input type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} className="input" />
            </div>
          </div>

          <h3 className="font-medium text-gray-900 pt-4 border-t">Initial admin-bruker</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Admin epost *</label>
              <input required type="email" value={form.admin_email} onChange={e => setForm({ ...form, admin_email: e.target.value })} className="input" autoComplete="off" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Admin passord * <span className="text-xs text-gray-400">(min 8 tegn)</span></label>
              <input required type="password" minLength={8} value={form.admin_password} onChange={e => setForm({ ...form, admin_password: e.target.value })} className="input" autoComplete="new-password" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Fornavn</label>
              <input value={form.admin_first_name} onChange={e => setForm({ ...form, admin_first_name: e.target.value })} className="input" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Etternavn</label>
              <input value={form.admin_last_name} onChange={e => setForm({ ...form, admin_last_name: e.target.value })} className="input" />
            </div>
          </div>

          <h3 className="font-medium text-gray-900 pt-4 border-t">SuSoft tilgang (valgfritt)</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">SuSoft API URL</label>
              <input value={form.susoft_api_url} onChange={e => setForm({ ...form, susoft_api_url: e.target.value })} className="input" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Shop Key</label>
              <input value={form.susoft_shop_url_key} onChange={e => setForm({ ...form, susoft_shop_url_key: e.target.value })} className="input" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">SuSoft epost</label>
              <input type="email" value={form.susoft_login} onChange={e => setForm({ ...form, susoft_login: e.target.value })} className="input" autoComplete="off" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">SuSoft passord</label>
              <input type="password" value={form.susoft_password} onChange={e => setForm({ ...form, susoft_password: e.target.value })} className="input" autoComplete="new-password" />
            </div>
          </div>

          {formError && <p className="text-sm text-red-600">{formError}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => { setShowForm(false); setForm(EMPTY_FORM); }} className="btn-secondary">Avbryt</button>
            <button type="submit" disabled={submitting} className="btn-primary">{submitting ? 'Oppretter…' : 'Opprett tenant'}</button>
          </div>
        </form>
      )}

      <div className="card p-0 overflow-hidden">
        {loading ? (
          <p className="text-gray-500 p-4 text-sm">Laster…</p>
        ) : tenants.length === 0 ? (
          <p className="text-gray-500 p-4 text-sm">Ingen tenants funnet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="shop-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Slug</th>
                  <th>Navn</th>
                  <th>E-post</th>
                  <th>Plan</th>
                  <th>Brukere</th>
                  <th>SuSoft</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {tenants.map(t => (
                  <tr key={t.id}>
                    <td className="text-gray-500">{t.id}</td>
                    <td className="font-mono text-xs">{t.slug}</td>
                    <td className="font-medium text-gray-900">{t.name}</td>
                    <td className="text-gray-600">{t.email || '—'}</td>
                    <td className="text-xs text-gray-600">{t.subscription_plan || '—'} / {t.subscription_status || '—'}</td>
                    <td>{t.user_count}</td>
                    <td>
                      {t.susoft_connection_status === 'ok' ? (
                        <span className="badge badge-success"><CheckCircle className="w-3 h-3" /> ok</span>
                      ) : t.susoft_connection_status === 'failed' ? (
                        <span className="badge badge-danger"><XCircle className="w-3 h-3" /> feilet</span>
                      ) : (
                        <span className="badge badge-neutral">{t.susoft_connection_status || '—'}</span>
                      )}
                    </td>
                    <td>
                      {t.is_active ? <span className="badge badge-success">Aktiv</span> : <span className="badge badge-neutral">Inaktiv</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
