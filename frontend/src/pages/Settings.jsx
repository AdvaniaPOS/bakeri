import { useState, useEffect } from 'react';
import { Save, Bell, Clock, Truck, Database, Shield, RefreshCw, CheckCircle, AlertCircle, Users, Package } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

export default function Settings() {
  const { authFetch } = useAuth();
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
  });
  const [password, setPassword] = useState('');
  const [savingConfig, setSavingConfig] = useState(false);
  const [configMessage, setConfigMessage] = useState(null);

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

  const saveConfig = async () => {
    setSavingConfig(true);
    setConfigMessage(null);
    try {
      const payload = {
        api_url: config.api_url || null,
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
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">API URL</label>
              <input
                type="text"
                value={config.api_url || ''}
                onChange={e => setConfig(c => ({ ...c, api_url: e.target.value }))}
                placeholder="https://api.susoft.com:4443"
                className="input"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Shop Key (X-Shop-Url-Key)</label>
              <input
                type="text"
                value={config.shop_url_key || ''}
                onChange={e => setConfig(c => ({ ...c, shop_url_key: e.target.value }))}
                placeholder="f.eks. jonb"
                className="input"
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
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Passord {config.has_password && <span className="text-xs text-gray-400">(lagret — la stå tomt for å beholde)</span>}
              </label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder={config.has_password ? '••••••••••••' : 'Skriv passord'}
                className="input"
                autoComplete="new-password"
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
              disabled={savingConfig}
              className="btn-primary text-sm flex items-center gap-2"
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
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Bestillingsfrist (tid)</label>
              <input type="time" defaultValue="15:00" className="input" />
              <p className="text-xs text-gray-400 mt-1">Siste tidspunkt for bestillinger neste dag</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Dager før levering</label>
              <input type="number" defaultValue="1" min="1" max="7" className="input" />
              <p className="text-xs text-gray-400 mt-1">Antall dager før levering bestilling må være inne</p>
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
