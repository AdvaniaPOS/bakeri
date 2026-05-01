import { useState, useEffect } from 'react';
import { Building2, Plus, RefreshCw, CheckCircle, XCircle, AlertCircle, Lock, Unlock, Settings as SettingsIcon, LogIn, ShieldCheck, Trash2, UserPlus } from 'lucide-react';
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
  // Edit Susoft per tenant
  const [editTenant, setEditTenant] = useState(null);
  const [editForm, setEditForm] = useState({ susoft_api_url: '', susoft_login: '', susoft_password: '', susoft_shop_url_key: '', config_locked: true });
  const [editError, setEditError] = useState(null);
  const [editSaving, setEditSaving] = useState(false);
  // Super-admins
  const [superAdmins, setSuperAdmins] = useState([]);
  const [showAddAdmin, setShowAddAdmin] = useState(false);
  const [adminForm, setAdminForm] = useState({ email: '', password: '', first_name: '', last_name: '' });
  const [adminError, setAdminError] = useState(null);
  const [adminSaving, setAdminSaving] = useState(false);

  const isSuperAdmin = (user?.role || '').toLowerCase() === 'super_admin';

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
    if (isSuperAdmin) {
      loadTenants();
      loadSuperAdmins();
    } else {
      setLoading(false);
    }
  }, [isSuperAdmin]);

  const loadSuperAdmins = async () => {
    try {
      const resp = await authFetch('/api/v1/admin/super-admins');
      if (resp.ok) setSuperAdmins(await resp.json());
    } catch { /* ignore */ }
  };

  const addSuperAdmin = async (e) => {
    e.preventDefault();
    setAdminSaving(true);
    setAdminError(null);
    try {
      const resp = await authFetch('/api/v1/admin/super-admins', { method: 'POST', body: adminForm });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
      setAdminForm({ email: '', password: '', first_name: '', last_name: '' });
      setShowAddAdmin(false);
      loadSuperAdmins();
    } catch (e) {
      setAdminError(e.message);
    } finally {
      setAdminSaving(false);
    }
  };

  const removeSuperAdmin = async (id) => {
    if (!confirm('Slette denne super-adminen?')) return;
    try {
      const resp = await authFetch(`/api/v1/admin/super-admins/${id}`, { method: 'DELETE' });
      if (!resp.ok && resp.status !== 204) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${resp.status}`);
      }
      loadSuperAdmins();
    } catch (e) {
      alert(e.message);
    }
  };

  const impersonate = async (t) => {
    if (!confirm(`Logge inn som support pa "${t.name}"?`)) return;
    try {
      const resp = await authFetch(`/api/v1/admin/tenants/${t.id}/impersonate`, { method: 'POST' });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token);
      localStorage.setItem('user', JSON.stringify(data.user));
      localStorage.setItem('tenant', JSON.stringify(data.tenant));
      window.location.href = '/';
    } catch (e) {
      alert(e.message);
    }
  };

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

  const openEdit = (t) => {
    setEditTenant(t);
    setEditError(null);
    setEditForm({
      susoft_api_url: t.susoft_api_url || '',
      susoft_login: t.susoft_login || '',
      susoft_password: '',
      susoft_shop_url_key: t.susoft_shop_url_key || '',
      config_locked: !!t.susoft_config_locked,
    });
  };

  const saveEdit = async (e) => {
    e.preventDefault();
    setEditSaving(true);
    setEditError(null);
    try {
      const payload = {
        api_url: editForm.susoft_api_url || null,
        login: editForm.susoft_login || null,
        shop_url_key: editForm.susoft_shop_url_key || null,
        config_locked: editForm.config_locked,
      };
      if (editForm.susoft_password) payload.password = editForm.susoft_password;
      const resp = await authFetch(`/api/v1/admin/tenants/${editTenant.id}/susoft-config`, { method: 'PUT', body: payload });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
      setEditTenant(null);
      loadTenants();
    } catch (e) {
      setEditError(e.message);
    } finally {
      setEditSaving(false);
    }
  };

  const toggleLock = async (t) => {
    try {
      const resp = await authFetch(`/api/v1/admin/tenants/${t.id}/susoft-config`, {
        method: 'PUT',
        body: { config_locked: !t.susoft_config_locked },
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${resp.status}`);
      }
      loadTenants();
    } catch (e) {
      alert(e.message);
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
                  <th>Lås</th>
                  <th>Status</th>
                  <th className="text-right">Handlinger</th>
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
                      <button
                        onClick={() => toggleLock(t)}
                        className={t.susoft_config_locked ? 'badge badge-warning hover:opacity-80' : 'badge badge-neutral hover:opacity-80'}
                        title={t.susoft_config_locked ? 'Klikk for å låse opp' : 'Klikk for å låse'}
                      >
                        {t.susoft_config_locked ? <><Lock className="w-3 h-3" /> Låst</> : <><Unlock className="w-3 h-3" /> Åpen</>}
                      </button>
                    </td>
                    <td>
                      {t.is_active ? <span className="badge badge-success">Aktiv</span> : <span className="badge badge-neutral">Inaktiv</span>}
                    </td>
                    <td className="text-right">
                      <div className="flex gap-1 justify-end">
                        <button onClick={() => impersonate(t)} className="btn-secondary !py-1 !text-xs" title="Logg inn som support paa denne tenanten">
                          <LogIn className="w-3.5 h-3.5" /> Gå inn
                        </button>
                        <button onClick={() => openEdit(t)} className="btn-secondary !py-1 !text-xs">
                          <SettingsIcon className="w-3.5 h-3.5" /> SuSoft
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Super Admins */}
      <div className="mt-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-indigo-600" /> Super-admins
          </h2>
          <button onClick={() => setShowAddAdmin(s => !s)} className="btn-primary text-sm">
            <UserPlus className="w-4 h-4" /> Legg til super-admin
          </button>
        </div>

        {showAddAdmin && (
          <form onSubmit={addSuperAdmin} className="card mb-4 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium mb-1">E-post *</label>
                <input required type="email" value={adminForm.email} onChange={e => setAdminForm({ ...adminForm, email: e.target.value })} className="input" autoComplete="off" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Passord * <span className="text-xs text-gray-400">(min 8 tegn)</span></label>
                <input required type="password" minLength={8} value={adminForm.password} onChange={e => setAdminForm({ ...adminForm, password: e.target.value })} className="input" autoComplete="new-password" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Fornavn</label>
                <input value={adminForm.first_name} onChange={e => setAdminForm({ ...adminForm, first_name: e.target.value })} className="input" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Etternavn</label>
                <input value={adminForm.last_name} onChange={e => setAdminForm({ ...adminForm, last_name: e.target.value })} className="input" />
              </div>
            </div>
            {adminError && <p className="text-sm text-red-600">{adminError}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => { setShowAddAdmin(false); setAdminError(null); }} className="btn-secondary">Avbryt</button>
              <button type="submit" disabled={adminSaving} className="btn-primary">{adminSaving ? 'Lagrer…' : 'Opprett'}</button>
            </div>
          </form>
        )}

        <div className="card p-0 overflow-hidden">
          {superAdmins.length === 0 ? (
            <p className="text-sm text-gray-500 p-4">Ingen super-admins.</p>
          ) : (
            <table className="shop-table">
              <thead>
                <tr>
                  <th>E-post</th>
                  <th>Navn</th>
                  <th>Sist innlogget</th>
                  <th>Status</th>
                  <th className="text-right">Handling</th>
                </tr>
              </thead>
              <tbody>
                {superAdmins.map(a => (
                  <tr key={a.id}>
                    <td className="font-mono text-xs">{a.email}</td>
                    <td>{a.first_name} {a.last_name}</td>
                    <td className="text-xs text-gray-500">{a.last_login_at ? new Date(a.last_login_at).toLocaleString('nb-NO') : 'Aldri'}</td>
                    <td>{a.is_active ? <span className="badge badge-success">Aktiv</span> : <span className="badge badge-neutral">Inaktiv</span>}</td>
                    <td className="text-right">
                      {a.id !== user?.id && (
                        <button onClick={() => removeSuperAdmin(a.id)} className="btn-secondary !py-1 !text-xs text-red-600">
                          <Trash2 className="w-3.5 h-3.5" /> Slett
                        </button>
                      )}
                      {a.id === user?.id && <span className="text-xs text-gray-400">Deg selv</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Edit Susoft modal */}
      {editTenant && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setEditTenant(null)}>
          <form onClick={(e) => e.stopPropagation()} onSubmit={saveEdit} className="bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 space-y-4 max-h-[90vh] overflow-auto">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">SuSoft-konfig: {editTenant.name}</h2>
                <p className="text-xs text-gray-500 font-mono">{editTenant.slug}</p>
              </div>
              <button type="button" onClick={() => setEditTenant(null)} className="text-gray-400 hover:text-gray-700">&times;</button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium mb-1">API URL</label>
                <input value={editForm.susoft_api_url} onChange={e => setEditForm({ ...editForm, susoft_api_url: e.target.value })} className="input" placeholder="https://api.susoft.com:4443" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Shop Key</label>
                <input value={editForm.susoft_shop_url_key} onChange={e => setEditForm({ ...editForm, susoft_shop_url_key: e.target.value })} className="input" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">E-post</label>
                <input type="email" value={editForm.susoft_login} onChange={e => setEditForm({ ...editForm, susoft_login: e.target.value })} className="input" autoComplete="off" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">
                  Passord {editTenant.susoft_has_password && <span className="text-xs text-gray-400">(lagret &mdash; tomt = behold)</span>}
                </label>
                <input type="password" value={editForm.susoft_password} onChange={e => setEditForm({ ...editForm, susoft_password: e.target.value })} className="input" autoComplete="new-password" placeholder={editTenant.susoft_has_password ? '••••••••' : ''} />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm pt-2 border-t">
              <input type="checkbox" checked={editForm.config_locked} onChange={e => setEditForm({ ...editForm, config_locked: e.target.checked })} />
              <Lock className="w-4 h-4 text-amber-700" />
              <span><strong>L&aring;s konfigurasjonen</strong> &mdash; tenant-admin kan se men ikke endre</span>
            </label>
            {editError && <p className="text-sm text-red-600">{editError}</p>}
            <div className="flex justify-end gap-2 pt-2 border-t">
              <button type="button" onClick={() => setEditTenant(null)} className="btn-secondary">Avbryt</button>
              <button type="submit" disabled={editSaving} className="btn-primary">{editSaving ? 'Lagrer…' : 'Lagre'}</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
