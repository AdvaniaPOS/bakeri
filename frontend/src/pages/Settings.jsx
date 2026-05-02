import { useState, useEffect } from 'react';
import { Save, Bell, Clock, Truck, Database, Shield, RefreshCw, CheckCircle, AlertCircle, Users, Package, Calendar, PlayCircle, Lock, Image as ImageIcon } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

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
  });
  const [password, setPassword] = useState('');
  const [savingConfig, setSavingConfig] = useState(false);
  const [configMessage, setConfigMessage] = useState(null);

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
      };
      if (password) payload.password = password;
      const resp = await authFetch('/api/v1/admin/susoft-config', {
        method: 'PUT',
        body: payload,
      });
      const data = await resp.json();
      if (resp.ok) {
        setConfig(data);
        setPassword('');
        setConfigMessage({ success: true, message: 'Lagret' });
        setConnectionStatus(null);
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
          <p className="page-subtitle">Konfigurer systemet for Lampeland Bakeri</p>
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
              <p className="text-sm text-gray-500">Konfigurer tidsfrister for bestillinger</p>
            </div>
          </div>
        </div>

        {/* Delivery Settings */}
        <div className="card">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
              <Truck className="w-5 h-5 text-green-600" />
            </div>
            <div>
              <h2 className="font-semibold text-gray-900">Leveringsinnstillinger</h2>
              <p className="text-sm text-gray-500">Konfigurer leveringsruter og tider</p>
            </div>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Standard leveringstid</label>
              <input type="time" defaultValue="07:00" className="input" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Leveringsområde</label>
              <select className="input">
                <option>Numedal (Lampeland, Flesberg, Rollag)</option>
                <option>Kongsberg</option>
                <option>Hele regionen</option>
              </select>
            </div>
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
