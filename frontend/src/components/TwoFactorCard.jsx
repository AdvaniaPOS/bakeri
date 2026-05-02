import { useEffect, useState } from 'react';
import { Lock, ShieldCheck, ShieldOff } from 'lucide-react';

/**
 * 2FA-kort i Settings.
 * Bruker authFetch fra parent.
 */
export default function TwoFactorCard({ authFetch }) {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [setupSecret, setSetupSecret] = useState(null);
  const [setupUri, setSetupUri] = useState(null);
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);

  async function loadStatus() {
    setLoading(true);
    try {
      const r = await authFetch('/api/v1/auth/2fa/status');
      if (r.ok) {
        const d = await r.json();
        setEnabled(!!d.enabled);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadStatus(); }, []);

  async function startSetup() {
    setBusy(true); setMessage(null);
    try {
      const r = await authFetch('/api/v1/auth/2fa/setup', { method: 'POST' });
      if (!r.ok) throw new Error('Kunne ikke starte 2FA-oppsett');
      const d = await r.json();
      setSetupSecret(d.secret);
      setSetupUri(d.otpauth_uri);
    } catch (e) {
      setMessage({ error: true, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function confirmEnable(e) {
    e.preventDefault();
    setBusy(true); setMessage(null);
    try {
      const r = await authFetch('/api/v1/auth/2fa/enable', {
        method: 'POST',
        body: { code },
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || 'Ugyldig kode');
      }
      setMessage({ success: true, text: '2FA aktivert' });
      setSetupSecret(null);
      setSetupUri(null);
      setCode('');
      await loadStatus();
    } catch (e) {
      setMessage({ error: true, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function disable(e) {
    e.preventDefault();
    if (!confirm('Sikker på at du vil slå av 2FA?')) return;
    setBusy(true); setMessage(null);
    try {
      const r = await authFetch('/api/v1/auth/2fa/disable', {
        method: 'POST',
        body: { password },
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || 'Kunne ikke deaktivere');
      }
      setMessage({ success: true, text: '2FA deaktivert' });
      setPassword('');
      await loadStatus();
    } catch (e) {
      setMessage({ error: true, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center">
          {enabled ? <ShieldCheck className="w-5 h-5 text-purple-600" /> : <Lock className="w-5 h-5 text-purple-600" />}
        </div>
        <div>
          <h2 className="font-semibold text-gray-900">To-faktor-autentisering (2FA)</h2>
          <p className="text-sm text-gray-500">
            {enabled ? 'Aktivert — du må skrive inn engangskode ved innlogging' : 'Anbefalt for admin-brukere'}
          </p>
        </div>
      </div>

      {loading && <div className="text-sm text-gray-500">Laster…</div>}

      {!loading && !enabled && !setupSecret && (
        <button onClick={startSetup} disabled={busy} className="btn btn-primary">
          <Lock className="w-4 h-4" /> Sett opp 2FA
        </button>
      )}

      {setupSecret && (
        <form onSubmit={confirmEnable} className="space-y-3">
          <div className="text-sm text-gray-700">
            Skann QR-koden i Authenticator-appen din (Google Authenticator, Authy, 1Password osv.).
          </div>
          <div className="flex justify-center">
            <img
              alt="QR-kode for 2FA"
              src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(setupUri)}`}
              className="border rounded"
            />
          </div>
          <div className="text-xs text-gray-600 text-center">
            Eller skriv inn manuelt: <code className="font-mono bg-gray-100 px-2 py-0.5 rounded">{setupSecret}</code>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Bekreftelseskode fra appen</label>
            <input
              type="text"
              inputMode="numeric"
              maxLength={8}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              className="input tracking-widest text-center font-mono"
              placeholder="123456"
              autoFocus
            />
          </div>
          <div className="flex gap-2">
            <button type="submit" disabled={busy || code.length < 6} className="btn btn-primary">
              Aktiver 2FA
            </button>
            <button
              type="button"
              onClick={() => { setSetupSecret(null); setSetupUri(null); setCode(''); }}
              className="btn"
            >
              Avbryt
            </button>
          </div>
        </form>
      )}

      {!loading && enabled && (
        <form onSubmit={disable} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Bekreft passord for å slå av</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input"
              placeholder="••••••••"
              required
            />
          </div>
          <button type="submit" disabled={busy || !password} className="btn">
            <ShieldOff className="w-4 h-4" /> Slå av 2FA
          </button>
        </form>
      )}

      {message && (
        <div className={`mt-3 text-sm ${message.success ? 'text-green-700' : 'text-red-700'}`}>
          {message.text}
        </div>
      )}
    </div>
  );
}
