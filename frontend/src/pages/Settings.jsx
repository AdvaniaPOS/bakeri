import { useState, useEffect } from 'react';
import { Save, Bell, Clock, Database, Shield, RefreshCw, CheckCircle, AlertCircle, Users, Package, Calendar, PlayCircle, Lock, Image as ImageIcon, Download, UserPlus, Trash2, Mail, X as XIcon, Building2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import TwoFactorCard from '../components/TwoFactorCard';

const ROLE_OPTIONS = [
  { value: 'tenant_admin', label: 'Administrator' },
  { value: 'manager', label: 'Leder' },
  { value: 'driver', label: 'Sjafor' },
  { value: 'viewer', label: 'Leser' },
];

function UsersCard({ authFetch, currentUser }) {
  const [users, setUsers] = useState([]);
  const [invitations, setInvitations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [showInvite, setShowInvite] = useState(false);
  const [inviteForm, setInviteForm] = useState({ email: '', role: 'viewer' });
  const [inviting, setInviting] = useState(false);
  const [inviteMsg, setInviteMsg] = useState(null);

  const reload = async () => {
    setLoading(true);
    setErr(null);
    try {
      const [u, i] = await Promise.all([
        authFetch('/api/v1/auth/users'),
        authFetch('/api/v1/auth/invitations'),
      ]);
      if (u.ok) setUsers(await u.json());
      if (i.ok) setInvitations(await i.json());
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const submitInvite = async (e) => {
    e.preventDefault();
    setInviting(true);
    setInviteMsg(null);
    try {
      const resp = await authFetch('/api/v1/auth/invite', {
        method: 'POST',
        body: { email: inviteForm.email.trim().toLowerCase(), role: inviteForm.role },
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data?.detail || `HTTP ${resp.status}`);
      setInviteMsg({ success: true, text: `Invitasjon sendt til ${inviteForm.email}` });
      setInviteForm({ email: '', role: 'viewer' });
      setShowInvite(false);
      reload();
    } catch (e) {
      setInviteMsg({ success: false, text: e.message });
    } finally {
      setInviting(false);
    }
  };

  const updateRole = async (u, newRole) => {
    if (u.role === newRole) return;
    try {
      const resp = await authFetch(`/api/v1/auth/users/${u.id}`, {
        method: 'PATCH',
        body: { role: newRole },
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${resp.status}`);
      }
      reload();
    } catch (e) {
      alert('Kunne ikke endre rolle: ' + e.message);
    }
  };

  const toggleActive = async (u) => {
    try {
      const resp = await authFetch(`/api/v1/auth/users/${u.id}`, {
        method: 'PATCH',
        body: { is_active: !u.is_active },
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${resp.status}`);
      }
      reload();
    } catch (e) {
      alert(e.message);
    }
  };

  const deleteUser = async (u) => {
    if (!confirm(`Slette brukeren "${u.first_name} ${u.last_name}" (${u.email})?`)) return;
    try {
      const resp = await authFetch(`/api/v1/auth/users/${u.id}`, { method: 'DELETE' });
      if (!resp.ok && resp.status !== 204) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${resp.status}`);
      }
      reload();
    } catch (e) {
      alert(e.message);
    }
  };

  const revokeInvite = async (inv) => {
    if (!confirm(`Trekke tilbake invitasjon til ${inv.email}?`)) return;
    try {
      const resp = await authFetch(`/api/v1/auth/invitations/${inv.id}`, { method: 'DELETE' });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${resp.status}`);
      }
      reload();
    } catch (e) {
      alert(e.message);
    }
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
            <Users className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <h2 className="font-semibold text-gray-900">Brukere</h2>
            <p className="text-sm text-gray-500">Inviter kollegaer og styr roller</p>
          </div>
        </div>
        <button onClick={() => setShowInvite(s => !s)} className="btn btn-primary">
          <UserPlus className="w-4 h-4" /> Inviter bruker
        </button>
      </div>

      {showInvite && (
        <form onSubmit={submitInvite} className="mb-4 p-3 border border-gray-200 rounded-lg bg-gray-50 grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">E-post</label>
            <input
              type="email"
              required
              value={inviteForm.email}
              onChange={(e) => setInviteForm(f => ({ ...f, email: e.target.value }))}
              className="input w-full"
              placeholder="navn@firma.no"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Rolle</label>
            <select
              value={inviteForm.role}
              onChange={(e) => setInviteForm(f => ({ ...f, role: e.target.value }))}
              className="input w-full"
            >
              {ROLE_OPTIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>
          <div className="flex items-end gap-2">
            <button type="submit" disabled={inviting} className="btn btn-primary">
              {inviting ? 'Sender...' : 'Send invitasjon'}
            </button>
            <button type="button" onClick={() => { setShowInvite(false); setInviteMsg(null); }} className="btn-secondary">
              Avbryt
            </button>
          </div>
        </form>
      )}

      {inviteMsg && (
        <div className={`mb-3 p-2 rounded text-sm ${inviteMsg.success ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
          {inviteMsg.text}
        </div>
      )}

      {err && <div className="mb-3 p-2 rounded bg-red-50 text-red-800 text-sm">{err}</div>}

      {loading ? (
        <div className="text-sm text-gray-500">Laster...</div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-gray-500 border-b">
                  <th className="py-2 pr-3">Navn</th>
                  <th className="py-2 pr-3">E-post</th>
                  <th className="py-2 pr-3">Rolle</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3"></th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => {
                  const isSelf = u.id === currentUser?.id;
                  const isSuper = u.role === 'super_admin';
                  return (
                    <tr key={u.id} className="border-b last:border-b-0">
                      <td className="py-2 pr-3 font-medium text-gray-900">
                        {u.first_name} {u.last_name}
                        {isSelf && <span className="text-xs text-gray-400 ml-1">(deg)</span>}
                      </td>
                      <td className="py-2 pr-3 text-gray-600">{u.email}</td>
                      <td className="py-2 pr-3">
                        {isSuper ? (
                          <span className="px-2 py-0.5 rounded bg-purple-100 text-purple-700 text-xs font-medium">Super-admin</span>
                        ) : (
                          <select
                            value={u.role}
                            onChange={(e) => updateRole(u, e.target.value)}
                            className="input !py-0.5 !text-xs"
                            disabled={isSelf}
                          >
                            {ROLE_OPTIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                          </select>
                        )}
                      </td>
                      <td className="py-2 pr-3">
                        {u.is_active ? (
                          <span className="text-green-700 text-xs font-medium">Aktiv</span>
                        ) : (
                          <span className="text-gray-400 text-xs">Deaktivert</span>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-right">
                        {!isSelf && !isSuper && (
                          <div className="flex items-center justify-end gap-1">
                            <button
                              onClick={() => toggleActive(u)}
                              className="btn-secondary !py-1 !text-xs"
                              title={u.is_active ? 'Deaktiver' : 'Aktiver'}
                            >
                              {u.is_active ? 'Deaktiver' : 'Aktiver'}
                            </button>
                            <button
                              onClick={() => deleteUser(u)}
                              className="btn-secondary !py-1 !text-xs !text-red-600"
                              title="Slett bruker"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {users.length === 0 && (
                  <tr><td colSpan={5} className="py-3 text-center text-gray-400">Ingen brukere</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {invitations.filter(i => i.status === 'pending').length > 0 && (
            <div className="mt-5">
              <h3 className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-1.5">
                <Mail className="w-4 h-4" /> Ventende invitasjoner
              </h3>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <tbody>
                    {invitations.filter(i => i.status === 'pending').map(inv => (
                      <tr key={inv.id} className="border-b last:border-b-0">
                        <td className="py-2 pr-3 text-gray-700">{inv.email}</td>
                        <td className="py-2 pr-3 text-xs text-gray-500">{ROLE_OPTIONS.find(r => r.value === inv.role)?.label || inv.role}</td>
                        <td className="py-2 pr-3 text-right">
                          <button
                            onClick={() => revokeInvite(inv)}
                            className="btn-secondary !py-1 !text-xs !text-red-600"
                            title="Trekk tilbake invitasjon"
                          >
                            <XIcon className="w-3.5 h-3.5" /> Trekk tilbake
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function CompanyInfoCard({ authFetch, tenant, updateTenant }) {
  const [form, setForm] = useState({
    name: tenant?.name || '',
    legal_name: tenant?.legal_name || '',
    org_number: tenant?.org_number || '',
    email: tenant?.email || '',
    phone: tenant?.phone || '',
    street_address: tenant?.street_address || '',
    postal_code: tenant?.postal_code || '',
    city: tenant?.city || '',
  });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    setForm({
      name: tenant?.name || '',
      legal_name: tenant?.legal_name || '',
      org_number: tenant?.org_number || '',
      email: tenant?.email || '',
      phone: tenant?.phone || '',
      street_address: tenant?.street_address || '',
      postal_code: tenant?.postal_code || '',
      city: tenant?.city || '',
    });
  }, [tenant?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setMsg(null);
    try {
      const resp = await authFetch('/api/v1/auth/tenant', {
        method: 'PATCH',
        body: form,
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data?.detail || `HTTP ${resp.status}`);
      updateTenant({
        name: data.name,
        legal_name: data.legal_name,
        org_number: data.org_number,
        email: data.email,
        phone: data.phone,
        street_address: data.street_address,
        postal_code: data.postal_code,
        city: data.city,
        country: data.country,
      });
      setMsg({ success: true, text: 'Firmaopplysninger lagret' });
    } catch (err) {
      setMsg({ success: false, text: err.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-10 h-10 bg-emerald-100 rounded-lg flex items-center justify-center">
          <Building2 className="w-5 h-5 text-emerald-600" />
        </div>
        <div>
          <h2 className="font-semibold text-gray-900">Firmaopplysninger</h2>
          <p className="text-sm text-gray-500">Vises i menyen og pa alle PDF-rapporter (ogsa avsender/mottaker for e-post)</p>
        </div>
      </div>

      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Firmanavn (vises i menyen) *</label>
            <input required type="text" value={form.name} onChange={set('name')} className="input w-full" placeholder="F.eks. Lampeland Bakeri" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Juridisk navn</label>
            <input type="text" value={form.legal_name} onChange={set('legal_name')} className="input w-full" placeholder="F.eks. Lampeland Bakeri AS" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Org.nr</label>
            <input type="text" value={form.org_number} onChange={set('org_number')} className="input w-full" placeholder="9 siffer" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">E-post (rapporter sendes hit)</label>
            <input type="email" value={form.email} onChange={set('email')} className="input w-full" placeholder="post@firma.no" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Telefon</label>
            <input type="text" value={form.phone} onChange={set('phone')} className="input w-full" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Gateadresse</label>
            <input type="text" value={form.street_address} onChange={set('street_address')} className="input w-full" placeholder="Hovedgata 1" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Postnummer</label>
            <input type="text" value={form.postal_code} onChange={set('postal_code')} className="input w-full" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Sted</label>
            <input type="text" value={form.city} onChange={set('city')} className="input w-full" />
          </div>
        </div>

        {msg && (
          <div className={`p-2 rounded text-sm ${msg.success ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
            {msg.text}
          </div>
        )}

        <div className="flex justify-end">
          <button type="submit" disabled={saving} className="btn-primary text-sm flex items-center gap-2">
            <Save className="w-4 h-4" />
            {saving ? 'Lagrer...' : 'Lagre firmaopplysninger'}
          </button>
        </div>
      </form>
    </div>
  );
}

const WEEKDAY_LABELS = ['Mandag', 'Tirsdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lørdag', 'Søndag'];
const WEEKDAY_SHORT  = ['Man', 'Tir', 'Ons', 'Tor', 'Fre', 'Lør', 'Søn'];

function DeliveryCutoffsEditor({ value, onChange }) {
  // value = list of {dw, cw, h, m}. Map by dw for quick lookup.
  const byDw = new Map(value.map(r => [r.dw, r]));

  const setRule = (dw, patch) => {
    const existing = byDw.get(dw) || { dw, cw: (dw === 0 ? 3 : (dw - 1 + 7) % 7), h: 15, m: 0 };
    const next = { ...existing, ...patch, dw };
    const others = value.filter(r => r.dw !== dw);
    onChange([...others, next].sort((a, b) => a.dw - b.dw));
  };

  const toggleDay = (dw, enabled) => {
    if (enabled) {
      // Default: cutoff = previous weekday at 15:00
      const cw = (dw - 1 + 7) % 7;
      setRule(dw, { cw, h: 15, m: 0 });
    } else {
      onChange(value.filter(r => r.dw !== dw));
    }
  };

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-12 gap-2 text-xs font-medium text-gray-500 px-1">
        <div className="col-span-1">På</div>
        <div className="col-span-3">Leveringsdag</div>
        <div className="col-span-4">Cutoff-dag</div>
        <div className="col-span-4">Klokkeslett</div>
      </div>
      {[0, 1, 2, 3, 4, 5, 6].map(dw => {
        const rule = byDw.get(dw);
        const enabled = !!rule;
        return (
          <div key={dw} className="grid grid-cols-12 gap-2 items-center px-1 py-1.5 rounded hover:bg-gray-50">
            <div className="col-span-1">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => toggleDay(dw, e.target.checked)}
                className="w-4 h-4 rounded border-gray-300 text-amber-600"
              />
            </div>
            <div className="col-span-3 text-sm font-medium text-gray-800">
              {WEEKDAY_LABELS[dw]}
            </div>
            <div className="col-span-4">
              <select
                value={rule?.cw ?? ''}
                disabled={!enabled}
                onChange={(e) => setRule(dw, { cw: parseInt(e.target.value, 10) })}
                className="input text-sm py-1.5 disabled:bg-gray-100 disabled:text-gray-400"
              >
                {WEEKDAY_LABELS.map((lbl, i) => (
                  <option key={i} value={i}>{lbl}</option>
                ))}
              </select>
            </div>
            <div className="col-span-4">
              <input
                type="time"
                disabled={!enabled}
                value={enabled
                  ? `${String(rule.h).padStart(2, '0')}:${String(rule.m).padStart(2, '0')}`
                  : '15:00'}
                onChange={(e) => {
                  const [h, m] = e.target.value.split(':').map(n => parseInt(n, 10));
                  setRule(dw, { h, m });
                }}
                className="input text-sm py-1.5 disabled:bg-gray-100 disabled:text-gray-400"
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function Settings() {
  const { authFetch, user, tenant, updateTenant, isAdmin } = useAuth();
  const [syncStatus, setSyncStatus] = useState({ customers: null, products: null });
  const [syncing, setSyncing] = useState({ customers: false, products: false });
  const [connectionStatus, setConnectionStatus] = useState(null);
  const [checkingConnection, setCheckingConnection] = useState(false);

  // SuSoft config (editable)
  const [config, setConfig] = useState({
    api_url: '',
    login: '',
    shop_url_key: '',
    has_password: false,
    connection_status: null,
    last_check_at: null,
    last_error: null,
    is_locked: true,
    can_edit: false,
    // Admin-API ("API 2") - aPOS-CART-er
    admin_api_url: '',
    admin_login: '',
    admin_shop_url_key: '',
    admin_shop_id: null,
    admin_has_password: false,
  });
  const [password, setPassword] = useState('');
  const [adminPassword, setAdminPassword] = useState('');
  const [savingConfig, setSavingConfig] = useState(false);
  const [configMessage, setConfigMessage] = useState(null);
  const [adminConnectionStatus, setAdminConnectionStatus] = useState(null);
  const [checkingAdminConnection, setCheckingAdminConnection] = useState(false);

  // Tenant settings (bakeri-defaults)
  const [tenantSettings, setTenantSettings] = useState({});
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState(null);

  // Periodeplan-horisont
  const [horizonStatus, setHorizonStatus] = useState(null);
  const [triggeringHorizon, setTriggeringHorizon] = useState(false);
  const [horizonMessage, setHorizonMessage] = useState(null);

  // Branding (logo, primaerfarge, navn)
  const [branding, setBranding] = useState({
    name: tenant?.name || '',
    logo_url: tenant?.logo_url || '',
    primary_color: tenant?.primary_color || '#d97706',
  });
  const [savingBranding, setSavingBranding] = useState(false);
  const [brandingMessage, setBrandingMessage] = useState(null);
  useEffect(() => {
    setBranding({
      name: tenant?.name || '',
      logo_url: tenant?.logo_url || '',
      primary_color: tenant?.primary_color || '#d97706',
    });
  }, [tenant?.name, tenant?.logo_url, tenant?.primary_color]);

  const saveBranding = async () => {
    setSavingBranding(true);
    setBrandingMessage(null);
    try {
      const resp = await authFetch('/api/v1/admin/tenant/branding', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: branding.name?.trim() || null,
          logo_url: branding.logo_url?.trim() || null,
          primary_color: branding.primary_color?.trim() || null,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data?.detail || 'Lagring feilet');
      updateTenant({
        name: branding.name || tenant?.name,
        logo_url: branding.logo_url || null,
        primary_color: branding.primary_color || null,
      });
      setBrandingMessage({ success: true, text: 'Branding oppdatert' });
    } catch (e) {
      setBrandingMessage({ success: false, text: e.message });
    } finally {
      setSavingBranding(false);
    }
  };

  // Last inn konfig ved mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await authFetch('/api/v1/admin/susoft-config');
        if (!resp.ok) return;
        const data = await resp.json();
        if (cancelled) return;
        setConfig(data);
        if (data.connection_status === 'ok') {
          setConnectionStatus({ success: true, message: 'Tilkoblet SuSoft' });
        } else if (data.connection_status === 'failed') {
          setConnectionStatus({ success: false, message: data.last_error || 'Tilkobling feilet' });
        }
      } catch (e) {
        // Ignore - handled by AuthContext
      }
    })();
    return () => { cancelled = true; };
  }, [authFetch]);

  // Last inn tenant-settings + horizon-status
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [sResp, hResp] = await Promise.all([
          authFetch('/api/v1/admin/settings'),
          authFetch('/api/v1/orders/horizon-status'),
        ]);
        if (!cancelled && sResp.ok) {
          setTenantSettings(await sResp.json());
        }
        if (!cancelled && hResp.ok) {
          setHorizonStatus(await hResp.json());
        }
      } catch {
        // ignore
      }
    })();
    return () => { cancelled = true; };
  }, [authFetch]);

  const updateSetting = (key, value) => {
    setTenantSettings(s => ({
      ...s,
      [key]: { ...(s[key] || {}), value },
    }));
  };

  const saveTenantSettings = async () => {
    setSavingSettings(true);
    setSettingsMessage(null);
    try {
      const payload = {};
      Object.entries(tenantSettings).forEach(([k, v]) => {
        payload[k] = v.value;
      });
      const resp = await authFetch('/api/v1/admin/settings', { method: 'PUT', body: payload });
      const data = await resp.json();
      if (resp.ok) {
        setSettingsMessage({ success: true, message: 'Innstillinger lagret' });
      } else {
        setSettingsMessage({ success: false, message: data.detail || 'Kunne ikke lagre' });
      }
    } catch (e) {
      setSettingsMessage({ success: false, message: e.message });
    } finally {
      setSavingSettings(false);
    }
  };

  const triggerHorizon = async (force = false) => {
    setTriggeringHorizon(true);
    setHorizonMessage(null);
    try {
      const url = `/api/v1/admin/horizon/trigger${force ? '?force=true' : ''}`;
      const resp = await authFetch(url, { method: 'POST' });
      const data = await resp.json();
      if (resp.ok) {
        setHorizonMessage({ success: true, message: force ? 'Tving-generering startet i bakgrunnen' : 'Generering startet i bakgrunnen' });
        // Refresh status after a delay
        setTimeout(async () => {
          try {
            const r = await authFetch('/api/v1/orders/horizon-status');
            if (r.ok) setHorizonStatus(await r.json());
          } catch { /* ignore */ }
        }, 4000);
      } else {
        setHorizonMessage({ success: false, message: data.detail || 'Kunne ikke trigge' });
      }
    } catch (e) {
      setHorizonMessage({ success: false, message: e.message });
    } finally {
      setTriggeringHorizon(false);
    }
  };

  const saveConfig = async () => {
    setSavingConfig(true);
    setConfigMessage(null);
    try {
      const payload = {
        login: config.login || null,
        shop_url_key: config.shop_url_key || null,
        admin_login: config.admin_login || null,
        admin_shop_url_key: config.admin_shop_url_key || null,
        admin_shop_id: config.admin_shop_id === '' || config.admin_shop_id === null ? null : Number(config.admin_shop_id),
      };
      if (password) payload.password = password;
      if (adminPassword) payload.admin_password = adminPassword;
      const resp = await authFetch('/api/v1/admin/susoft-config', {
        method: 'PUT',
        body: payload,
      });
      const data = await resp.json();
      if (resp.ok) {
        setConfig(data);
        setPassword('');
        setAdminPassword('');
        setConfigMessage({ success: true, message: 'Lagret' });
        setConnectionStatus(null);
        setAdminConnectionStatus(null);
      } else {
        setConfigMessage({ success: false, message: data.detail || 'Kunne ikke lagre' });
      }
    } catch (e) {
      setConfigMessage({ success: false, message: e.message });
    } finally {
      setSavingConfig(false);
    }
  };

  const checkConnection = async () => {
    setCheckingConnection(true);
    try {
      const response = await authFetch('/api/v1/admin/test-connection', { method: 'POST' });
      const data = await response.json();
      setConnectionStatus(data);
      if (data.status) {
        setConfig(c => ({ ...c, connection_status: data.status, last_check_at: data.last_check_at }));
      }
    } catch (err) {
      setConnectionStatus({ success: false, message: err.message });
    } finally {
      setCheckingConnection(false);
    }
  };

  const checkAdminConnection = async () => {
    setCheckingAdminConnection(true);
    try {
      const response = await authFetch('/api/v1/admin/test-admin-connection', { method: 'POST' });
      const data = await response.json();
      setAdminConnectionStatus(data);
    } catch (err) {
      setAdminConnectionStatus({ success: false, message: err.message });
    } finally {
      setCheckingAdminConnection(false);
    }
  };

  const syncCustomers = async () => {
    setSyncing(s => ({ ...s, customers: true }));
    setSyncStatus(s => ({ ...s, customers: null }));
    try {
      const response = await authFetch('/api/v1/admin/sync/customers', { method: 'POST' });
      const data = await response.json();
      setSyncStatus(s => ({ ...s, customers: { success: data.success !== false, ...data } }));
    } catch (err) {
      setSyncStatus(s => ({ ...s, customers: { success: false, message: err.message } }));
    } finally {
      setSyncing(s => ({ ...s, customers: false }));
    }
  };

  const syncProducts = async () => {
    setSyncing(s => ({ ...s, products: true }));
    setSyncStatus(s => ({ ...s, products: null }));
    try {
      const response = await authFetch('/api/v1/admin/sync/products', { method: 'POST' });
      const data = await response.json();
      setSyncStatus(s => ({ ...s, products: { success: data.success !== false, ...data } }));
    } catch (err) {
      setSyncStatus(s => ({ ...s, products: { success: false, message: err.message } }));
    } finally {
      setSyncing(s => ({ ...s, products: false }));
    }
  };

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Innstillinger</h1>
          <p className="page-subtitle">{tenant?.name ? `Konfigurer systemet for ${tenant.name}` : 'Konfigurer systemet'}</p>
        </div>
      </div>

      {/* Settings sections */}
      <div className="space-y-4">
        {/* SuSoft Integration - Moved to top */}
        <div className="card border-2 border-purple-200">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center">
              <Database className="w-5 h-5 text-purple-600" />
            </div>
            <div>
              <h2 className="font-semibold text-gray-900">SuSoft Integrasjon</h2>
              <p className="text-sm text-gray-500">Synkroniser data med SuSoft POS-system</p>
            </div>
          </div>

          {config.is_locked && !config.can_edit && (
            <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-md flex items-start gap-2 text-sm">
              <Lock className="w-4 h-4 text-amber-700 mt-0.5 flex-shrink-0" />
              <div className="text-amber-900">
                <strong>Susoft-konfigurasjonen er l&aring;st av support.</strong> Du kan se innstillingene og k&oslash;re synkronisering, men ikke endre tilgangsdata. Kontakt support for &aring; gj&oslash;re endringer.
              </div>
            </div>
          )}
          {config.is_locked && config.can_edit && (
            <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-md flex items-start gap-2 text-sm">
              <Shield className="w-4 h-4 text-blue-700 mt-0.5 flex-shrink-0" />
              <div className="text-blue-900">L&aring;st for kunden &mdash; kun du (super-admin) kan endre.</div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Shop Key (X-Shop-Url-Key)</label>
              <input
                type="text"
                value={config.shop_url_key || ''}
                onChange={e => setConfig(c => ({ ...c, shop_url_key: e.target.value }))}
                placeholder="f.eks. jonb"
                className="input"
                disabled={!config.can_edit}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">E-post (innlogging)</label>
              <input
                type="email"
                value={config.login || ''}
                onChange={e => setConfig(c => ({ ...c, login: e.target.value }))}
                placeholder="bruker@firma.no"
                className="input"
                autoComplete="username"
                disabled={!config.can_edit}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Passord {config.has_password && <span className="text-xs text-gray-400">(lagret &mdash; la st&aring; tomt for &aring; beholde)</span>}
              </label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder={config.has_password ? '••••••••••••' : 'Skriv passord'}
                className="input"
                autoComplete="new-password"
                disabled={!config.can_edit}
              />
            </div>
          </div>

          <div className="flex items-center justify-between mb-6">
            <div className="text-sm">
              {configMessage && (
                <span className={configMessage.success ? 'text-green-600' : 'text-red-600'}>
                  {configMessage.success ? '✓ ' : '✗ '}{configMessage.message}
                </span>
              )}
            </div>
            <button
              onClick={saveConfig}
              disabled={savingConfig || !config.can_edit}
              className="btn-primary text-sm flex items-center gap-2"
              title={!config.can_edit ? 'Konfig er laast - kontakt support' : ''}
            >
              <Save className="w-4 h-4" />
              {savingConfig ? 'Lagrer…' : 'Lagre tilgang'}
            </button>
          </div>
          
          {/* Connection Test */}
          <div className="mb-6 p-4 bg-gray-50 rounded-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {connectionStatus === null ? (
                  <span className="w-2 h-2 bg-gray-400 rounded-full"></span>
                ) : connectionStatus.success ? (
                  <CheckCircle className="w-5 h-5 text-green-500" />
                ) : (
                  <AlertCircle className="w-5 h-5 text-red-500" />
                )}
                <span className={`text-sm ${connectionStatus?.success ? 'text-green-600' : connectionStatus === null ? 'text-gray-500' : 'text-red-600'}`}>
                  {connectionStatus === null ? 'Tilkobling ikke testet' : connectionStatus.success ? 'Tilkoblet SuSoft' : connectionStatus.message || 'Tilkobling feilet'}
                </span>
              </div>
              <button 
                onClick={checkConnection} 
                disabled={checkingConnection}
                className="btn-secondary text-sm flex items-center gap-2"
              >
                {checkingConnection ? <RefreshCw className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                Test tilkobling
              </button>
            </div>
          </div>

          {/* Admin-API ("API 2") - aPOS-CART-er — DEAKTIVERT
              Henting av ordrer/CART-er fra SuSoft er fjernet. */}
          {false && (
          <div className="mb-6 p-4 border border-purple-200 bg-purple-50 rounded-lg">
            <div className="mb-3">
              <h3 className="text-sm font-semibold text-purple-900">Admin-API (aPOS-CART-er)</h3>
              <p className="text-xs text-purple-800 mt-1">
                Brukes for &aring; hente CART-er som er opprettet i aPOS-kassen, slik at de kommer inn i ordresystemet automatisk.
                Kan v&aelig;re samme bruker som over, eller en separat admin-bruker fra SuSoft.
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Admin-login (brukernavn)</label>
                <input
                  type="text"
                  value={config.admin_login || ''}
                  onChange={e => setConfig(c => ({ ...c, admin_login: e.target.value }))}
                  placeholder="admin@firma.no eller bruker"
                  className="input"
                  autoComplete="username"
                  disabled={!config.can_edit}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Admin-passord {config.admin_has_password && <span className="text-xs text-gray-400">(lagret &mdash; la st&aring; tomt for &aring; beholde)</span>}
                </label>
                <input
                  type="password"
                  value={adminPassword}
                  onChange={e => setAdminPassword(e.target.value)}
                  placeholder={config.admin_has_password ? '••••••••••••' : 'Skriv admin-passord'}
                  className="input"
                  autoComplete="new-password"
                  disabled={!config.can_edit}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Admin Shop Key (X-Shop-Url-Key)</label>
                <input
                  type="text"
                  value={config.admin_shop_url_key || ''}
                  onChange={e => setConfig(c => ({ ...c, admin_shop_url_key: e.target.value }))}
                  placeholder="ofte samme som over"
                  className="input"
                  disabled={!config.can_edit}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Admin Shop ID (numerisk)</label>
                <input
                  type="number"
                  value={config.admin_shop_id ?? ''}
                  onChange={e => setConfig(c => ({ ...c, admin_shop_id: e.target.value }))}
                  placeholder="f.eks. 1"
                  className="input"
                  disabled={!config.can_edit}
                />
              </div>
            </div>
            <div className="flex items-center justify-between p-3 bg-white rounded border">
              <div className="flex items-center gap-2">
                {adminConnectionStatus === null ? (
                  <span className="w-2 h-2 bg-gray-400 rounded-full"></span>
                ) : adminConnectionStatus.success ? (
                  <CheckCircle className="w-5 h-5 text-green-500" />
                ) : (
                  <AlertCircle className="w-5 h-5 text-red-500" />
                )}
                <span className={`text-sm ${adminConnectionStatus?.success ? 'text-green-600' : adminConnectionStatus === null ? 'text-gray-500' : 'text-red-600'}`}>
                  {adminConnectionStatus === null
                    ? 'Admin-tilkobling ikke testet'
                    : adminConnectionStatus.success
                      ? (adminConnectionStatus.message || 'Tilkoblet SuSoft admin-API')
                      : adminConnectionStatus.message || 'Tilkobling feilet'}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={saveConfig}
                  disabled={savingConfig || !config.can_edit}
                  className="btn-primary text-sm flex items-center gap-2"
                  title={!config.can_edit ? 'Konfig er laast - kontakt support' : 'Lagre admin-API-feltene'}
                >
                  <Save className="w-4 h-4" />
                  {savingConfig ? 'Lagrer…' : 'Lagre admin-tilgang'}
                </button>
                <button
                  onClick={checkAdminConnection}
                  disabled={checkingAdminConnection || !config.admin_login || (!config.admin_has_password && !adminPassword)}
                  className="btn-secondary text-sm flex items-center gap-2"
                  title={!config.admin_login ? 'Sett admin-login forst og lagre' : 'Husk a lagre forst hvis du har endret feltene'}
                >
                  {checkingAdminConnection ? <RefreshCw className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                  Test admin-tilkobling
                </button>
              </div>
            </div>
          </div>
          )}

          {/* Sync Buttons */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-4 border rounded-lg">
              <div className="flex items-center gap-3 mb-3">
                <Users className="w-5 h-5 text-blue-600" />
                <span className="font-medium">Kunder</span>
              </div>
              <button 
                onClick={syncCustomers} 
                disabled={syncing.customers}
                className="btn-primary w-full flex items-center justify-center gap-2"
              >
                {syncing.customers ? <RefreshCw className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                Synkroniser kunder
              </button>
              {syncStatus.customers && (
                <div className={`mt-2 text-sm ${syncStatus.customers.success ? 'text-green-600' : 'text-red-600'}`}>
                  {syncStatus.customers.success ? (
                    <>✓ {syncStatus.customers.created || 0} nye, {syncStatus.customers.updated || 0} oppdatert</>
                  ) : (
                    <>✗ {syncStatus.customers.message}</>
                  )}
                </div>
              )}
            </div>
            
            <div className="p-4 border rounded-lg">
              <div className="flex items-center gap-3 mb-3">
                <Package className="w-5 h-5 text-amber-600" />
                <span className="font-medium">Produkter</span>
              </div>
              <button 
                onClick={syncProducts} 
                disabled={syncing.products}
                className="btn-primary w-full flex items-center justify-center gap-2"
              >
                {syncing.products ? <RefreshCw className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                Synkroniser produkter
              </button>
              {syncStatus.products && (
                <div className={`mt-2 text-sm ${syncStatus.products.success ? 'text-green-600' : 'text-red-600'}`}>
                  {syncStatus.products.success ? (
                    <>✓ {syncStatus.products.created || 0} nye, {syncStatus.products.updated || 0} oppdatert</>
                  ) : (
                    <>✗ {syncStatus.products.message}</>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Branding (kun TENANT_ADMIN+) */}
        {isAdmin() && (
          <div className="card">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 bg-amber-100 rounded-lg flex items-center justify-center">
                <ImageIcon className="w-5 h-5 text-amber-600" />
              </div>
              <div>
                <h2 className="font-semibold text-gray-900">Branding</h2>
                <p className="text-sm text-gray-500">Tilpass navn, logo og farge p&aring; portalen</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="md:col-span-2 flex items-center gap-4">
                {branding.logo_url ? (
                  <img src={branding.logo_url} alt="" className="w-16 h-16 rounded-lg object-cover border border-gray-200" />
                ) : (
                  <div
                    className="w-16 h-16 rounded-lg flex items-center justify-center text-white text-xl font-bold"
                    style={{ backgroundColor: branding.primary_color || '#d97706' }}
                  >
                    {(branding.name || 'B').charAt(0).toUpperCase()}
                  </div>
                )}
                <div className="text-sm text-gray-500">Forh&aring;ndsvisning av logo / fargem&aelig;rke i sidemenyen.</div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Bakerinavn</label>
                <input
                  type="text"
                  value={branding.name}
                  onChange={e => setBranding(b => ({ ...b, name: e.target.value }))}
                  className="input"
                  placeholder="Lampeland Bakeri"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Prim&aelig;rfarge</label>
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={branding.primary_color || '#d97706'}
                    onChange={e => setBranding(b => ({ ...b, primary_color: e.target.value }))}
                    className="w-12 h-10 rounded border border-gray-300 cursor-pointer"
                  />
                  <input
                    type="text"
                    value={branding.primary_color || ''}
                    onChange={e => setBranding(b => ({ ...b, primary_color: e.target.value }))}
                    className="input"
                    placeholder="#d97706"
                  />
                </div>
              </div>
              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">Logo-URL</label>
                <input
                  type="url"
                  value={branding.logo_url}
                  onChange={e => setBranding(b => ({ ...b, logo_url: e.target.value }))}
                  className="input"
                  placeholder="https://..."
                />
                <p className="text-xs text-gray-500 mt-1">Lim inn lenke til logoen din (PNG, SVG, JPG). La st&aring; tomt for &aring; bruke fargem&aelig;rke.</p>
              </div>
            </div>

            <div className="mt-4 flex items-center gap-3">
              <button
                onClick={saveBranding}
                disabled={savingBranding}
                className="btn btn-primary"
              >
                {savingBranding ? <><RefreshCw className="w-4 h-4 animate-spin" /> Lagrer...</> : <><Save className="w-4 h-4" /> Lagre branding</>}
              </button>
              {brandingMessage && (
                <span className={`text-sm flex items-center gap-1 ${brandingMessage.success ? 'text-green-700' : 'text-red-700'}`}>
                  {brandingMessage.success ? <CheckCircle className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
                  {brandingMessage.text}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Firmaopplysninger (kun TENANT_ADMIN+) */}
        {isAdmin() && (
          <CompanyInfoCard authFetch={authFetch} tenant={tenant} updateTenant={updateTenant} />
        )}

        {/* Brukere (kun TENANT_ADMIN+) */}
        {isAdmin() && (
          <UsersCard authFetch={authFetch} currentUser={user} />
        )}

        {/* GDPR-eksport (kun TENANT_ADMIN+) */}
        {isAdmin() && (
          <div className="card">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                <Download className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <h2 className="font-semibold text-gray-900">GDPR-eksport</h2>
                <p className="text-sm text-gray-500">Last ned alle data tilh&oslash;rende denne tenanten som JSON</p>
              </div>
            </div>
            <button
              onClick={async () => {
                try {
                  const resp = await authFetch('/api/v1/admin/tenant/export');
                  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                  const blob = await resp.blob();
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `tenant-${tenant?.slug || 'export'}-${new Date().toISOString().slice(0, 10)}.json`;
                  document.body.appendChild(a);
                  a.click();
                  a.remove();
                  URL.revokeObjectURL(url);
                } catch (e) {
                  alert('Eksport feilet: ' + e.message);
                }
              }}
              className="btn btn-primary"
            >
              <Download className="w-4 h-4" /> Last ned eksport
            </button>
            <p className="text-xs text-gray-500 mt-2">
              Inneholder kunder, ordrer, produkter, brukere (uten passord), maler, ruter og audit-logg.
            </p>
          </div>
        )}

        {/* 2FA / TOTP */}
        <TwoFactorCard authFetch={authFetch} />

        {/* Bakeri-innstillinger */}
        <div className="card">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 bg-indigo-100 rounded-lg flex items-center justify-center">
              <Calendar className="w-5 h-5 text-indigo-600" />
            </div>
            <div>
              <h2 className="font-semibold text-gray-900">Bakeri-innstillinger</h2>
              <p className="text-sm text-gray-500">Standardvalg for rapporter og utskrifter</p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Standardvisning for produksjonsrapport
              </label>
              <select
                className="input"
                value={String(tenantSettings.production_report_default_day?.value ?? 'today')}
                onChange={e => updateSetting('production_report_default_day', e.target.value)}
              >
                <option value="today">I dag</option>
                <option value="tomorrow">I morgen</option>
                <option value="2">Om 2 dager</option>
                <option value="3">Om 3 dager</option>
                <option value="7">Om 7 dager</option>
              </select>
              <p className="text-xs text-gray-400 mt-1">
                Hvilken dato produksjonsrapporten åpner på som standard. Ofte tas rapporten ut på ettermiddagen for morgendagens produksjon.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  className="w-5 h-5 rounded border-gray-300 text-amber-600 focus:ring-amber-500"
                  checked={!!(tenantSettings.labels_show_phone?.value ?? true)}
                  onChange={e => updateSetting('labels_show_phone', e.target.checked)}
                />
                <span className="text-sm text-gray-700">Vis telefon på etiketter</span>
              </label>
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  className="w-5 h-5 rounded border-gray-300 text-amber-600 focus:ring-amber-500"
                  checked={!!(tenantSettings.labels_show_delivery_window?.value ?? true)}
                  onChange={e => updateSetting('labels_show_delivery_window', e.target.checked)}
                />
                <span className="text-sm text-gray-700">Vis leveringsvindu på etiketter</span>
              </label>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Undertittel på PDF-rapporter (valgfritt)
              </label>
              <input
                type="text"
                className="input"
                placeholder="F.eks. 'Daglig produksjon'"
                value={tenantSettings.pdf_header_subtitle?.value ?? ''}
                onChange={e => updateSetting('pdf_header_subtitle', e.target.value)}
              />
            </div>

            <div className="flex items-center justify-between pt-2">
              <div className="text-sm">
                {settingsMessage && (
                  <span className={settingsMessage.success ? 'text-green-600' : 'text-red-600'}>
                    {settingsMessage.success ? '✓ ' : '✗ '}{settingsMessage.message}
                  </span>
                )}
              </div>
              <button
                onClick={saveTenantSettings}
                disabled={savingSettings}
                className="btn-primary text-sm flex items-center gap-2"
              >
                <Save className="w-4 h-4" />
                {savingSettings ? 'Lagrer…' : 'Lagre innstillinger'}
              </button>
            </div>
          </div>
        </div>

        {/* Periodeplan-horisont */}
        <div className="card">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 bg-teal-100 rounded-lg flex items-center justify-center">
              <PlayCircle className="w-5 h-5 text-teal-600" />
            </div>
            <div>
              <h2 className="font-semibold text-gray-900">Periodeplan / ordre-generering</h2>
              <p className="text-sm text-gray-500">Generer fremtidige ordre fra aktive maler</p>
            </div>
          </div>

          <div className="p-4 bg-gray-50 rounded-lg mb-4">
            <div className="text-sm text-gray-700">
              <strong>Sist sjekket:</strong>{' '}
              {horizonStatus?.last_check_at
                ? new Date(horizonStatus.last_check_at).toLocaleString('nb-NO')
                : 'Aldri'}
            </div>
            <div className="text-sm text-gray-700 mt-1">
              <strong>Sjekket i dag:</strong>{' '}
              {horizonStatus?.checked_today ? (
                <span className="text-green-600">Ja ✓</span>
              ) : (
                <span className="text-amber-600">Nei</span>
              )}
            </div>
            <p className="text-xs text-gray-500 mt-2">
              Daglig kjøring skjer via cron (eller ved innlogging). «Tving generering» nullstiller stempelet og kjører på nytt.
            </p>
          </div>

          <div className="flex items-center justify-between">
            <div className="text-sm">
              {horizonMessage && (
                <span className={horizonMessage.success ? 'text-green-600' : 'text-red-600'}>
                  {horizonMessage.success ? '✓ ' : '✗ '}{horizonMessage.message}
                </span>
              )}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => triggerHorizon(false)}
                disabled={triggeringHorizon}
                className="btn-secondary text-sm flex items-center gap-2"
              >
                <RefreshCw className={`w-4 h-4 ${triggeringHorizon ? 'animate-spin' : ''}`} />
                Generer manglende ordre
              </button>
              <button
                onClick={() => triggerHorizon(true)}
                disabled={triggeringHorizon}
                className="btn-primary text-sm flex items-center gap-2"
              >
                <PlayCircle className="w-4 h-4" />
                Tving generering
              </button>
            </div>
          </div>
        </div>

        {/* Order Settings */}
        <div className="card">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 bg-amber-100 rounded-lg flex items-center justify-center">
              <Clock className="w-5 h-5 text-amber-600" />
            </div>
            <div>
              <h2 className="font-semibold text-gray-900">Bestillingsfrister</h2>
              <p className="text-sm text-gray-500">
                Sett bestillingsfrist (cutoff) per leveringsdag. Hak av kun de dagene dere leverer.
              </p>
            </div>
          </div>

          <DeliveryCutoffsEditor
            value={Array.isArray(tenantSettings.delivery_cutoffs?.value)
              ? tenantSettings.delivery_cutoffs.value
              : [
                  { dw: 0, cw: 3, h: 15, m: 0 },
                  { dw: 1, cw: 4, h: 15, m: 0 },
                  { dw: 2, cw: 1, h: 15, m: 0 },
                  { dw: 3, cw: 2, h: 15, m: 0 },
                  { dw: 4, cw: 3, h: 15, m: 0 },
                ]}
            onChange={(next) => updateSetting('delivery_cutoffs', next)}
          />

          <div className="text-xs text-gray-600 bg-amber-50 border border-amber-200 rounded p-3 mt-4">
            <strong>Standard:</strong> Mandag-levering må bestilles før Torsdag 15:00 (siden bakeriet ikke
            jobber i helga). Fredag-levering før Torsdag 15:00. Produkter med produksjonsdager øker
            ventetida ytterligere.
          </div>

          <div className="flex justify-end pt-4">
            <button
              onClick={saveTenantSettings}
              disabled={savingSettings}
              className="btn-primary text-sm flex items-center gap-2"
            >
              <Save className="w-4 h-4" />
              {savingSettings ? 'Lagrer…' : 'Lagre bestillingsfrister'}
            </button>
          </div>
        </div>

        {/* Notifications */}
        <div className="card">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
              <Bell className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h2 className="font-semibold text-gray-900">Varsler</h2>
              <p className="text-sm text-gray-500">Konfigurer e-post og push-varsler</p>
            </div>
          </div>
          
          <div className="space-y-4">
            <label className="flex items-center gap-3">
              <input type="checkbox" defaultChecked className="w-5 h-5 rounded border-gray-300 text-amber-600 focus:ring-amber-500" />
              <span className="text-sm text-gray-700">Send e-post ved nye bestillinger</span>
            </label>
            <label className="flex items-center gap-3">
              <input type="checkbox" defaultChecked className="w-5 h-5 rounded border-gray-300 text-amber-600 focus:ring-amber-500" />
              <span className="text-sm text-gray-700">Send påminnelse om bestillingsfrist</span>
            </label>
            <label className="flex items-center gap-3">
              <input type="checkbox" className="w-5 h-5 rounded border-gray-300 text-amber-600 focus:ring-amber-500" />
              <span className="text-sm text-gray-700">Send daglig oppsummering</span>
            </label>
          </div>
        </div>

        {/* Security */}
        <div className="card">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 bg-red-100 rounded-lg flex items-center justify-center">
              <Shield className="w-5 h-5 text-red-600" />
            </div>
            <div>
              <h2 className="font-semibold text-gray-900">Sikkerhet</h2>
              <p className="text-sm text-gray-500">Administrer passord og tilganger</p>
            </div>
          </div>
          
          <button className="btn-secondary">Endre passord</button>
        </div>

        {/* Save button */}
        <div className="flex justify-end">
          <button className="btn-primary flex items-center gap-2">
            <Save className="w-5 h-5" />
            Lagre endringer
          </button>
        </div>
      </div>
    </div>
  );
}
