import { useEffect, useState } from 'react';
import { Lock, Mail, ShieldCheck, ShieldOff, Smartphone } from 'lucide-react';

/**
 * 2FA-kort i Settings.
 *
 * Støtter to metoder:
 *  - email  : engangskode på e-post (anbefalt)
 *  - totp   : autentiserings-app (Google Authenticator, Authy osv.)
 *
 * Backend-endepunkter:
 *  GET  /api/v1/auth/2fa/status               -> { enabled, mfa_method, totp_enabled, must_setup, required }
 *  POST /api/v1/auth/2fa/email/setup          -> { status:'sent' }
 *  POST /api/v1/auth/2fa/email/verify-setup   { code }
 *  POST /api/v1/auth/2fa/setup                -> { secret, otpauth_uri }
 *  POST /api/v1/auth/2fa/enable               { code }
 *  POST /api/v1/auth/2fa/disable              { password }
 */
export default function TwoFactorCard({ authFetch, autoStart }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [chooseMethod, setChooseMethod] = useState(false);
  const [activeFlow, setActiveFlow] = useState(null); // 'email' | 'totp' | null
  const [emailStep, setEmailStep] = useState('idle'); // 'idle' | 'sent'
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
        setStatus({
          enabled: !!d.enabled,
          method: d.mfa_method || (d.totp_enabled ? 'totp' : 'none'),
          totpEnabled: !!d.totp_enabled,
          mustSetup: !!d.must_setup,
          required: !!d.required,
        });
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadStatus(); }, []);

  // Åpne metode-velgeren automatisk ved tvang eller ?mfa=setup
  useEffect(() => {
    if (!status) return;
    if ((autoStart || status.mustSetup) && !status.enabled && !activeFlow && !chooseMethod) {
      setChooseMethod(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, autoStart]);

  function resetFlow() {
    setActiveFlow(null);
    setEmailStep('idle');
    setSetupSecret(null);
    setSetupUri(null);
    setCode('');
    setMessage(null);
  }

  async function startEmailSetup() {
    setBusy(true); setMessage(null);
    try {
      const r = await authFetch('/api/v1/auth/2fa/email/setup', { method: 'POST' });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || 'Kunne ikke sende kode');
      }
      setEmailStep('sent');
      setActiveFlow('email');
      setChooseMethod(false);
      setMessage({ success: true, text: 'Kode sendt på e-post' });
    } catch (e) {
      setMessage({ error: true, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function verifyEmailSetup(e) {
    e.preventDefault();
    setBusy(true); setMessage(null);
    try {
      const r = await authFetch('/api/v1/auth/2fa/email/verify-setup', {
        method: 'POST',
        body: { code },
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || 'Ugyldig kode');
      }
      setMessage({ success: true, text: 'E-post 2FA aktivert' });
      resetFlow();
      await loadStatus();
    } catch (e) {
      setMessage({ error: true, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function startTotpSetup() {
    setBusy(true); setMessage(null);
    try {
      const r = await authFetch('/api/v1/auth/2fa/setup', { method: 'POST' });
      if (!r.ok) throw new Error('Kunne ikke starte 2FA-oppsett');
      const d = await r.json();
      setSetupSecret(d.secret);
      setSetupUri(d.otpauth_uri);
      setActiveFlow('totp');
      setChooseMethod(false);
    } catch (e) {
      setMessage({ error: true, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function confirmTotpEnable(e) {
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
      setMessage({ success: true, text: '2FA via app aktivert' });
      resetFlow();
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

  const enabled = !!status?.enabled;
  const required = !!status?.required;
  const mustSetup = !!status?.mustSetup;
  const method = status?.method || 'none';

  function methodLabel(m) {
    if (m === 'email') return 'E-post';
    if (m === 'totp') return 'Autentiserings-app';
    return 'Ikke aktivert';
  }

  return (
    <div className="card">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-10 h-10 bg-amber-100 rounded-lg flex items-center justify-center">
          {enabled ? <ShieldCheck className="w-5 h-5 text-amber-600" /> : <Lock className="w-5 h-5 text-amber-600" />}
        </div>
        <div className="flex-1">
          <h2 className="font-semibold text-gray-900">To-faktor-autentisering (2FA)</h2>
          <p className="text-sm text-gray-500">
            {enabled
              ? <>Aktivert via <strong>{methodLabel(method)}</strong></>
              : (required
                  ? 'Påkrevd for din rolle — du må sette opp 2FA'
                  : 'Anbefalt for ekstra sikkerhet')}
          </p>
        </div>
      </div>

      {loading && <div className="text-sm text-gray-500">Laster…</div>}

      {/* Tvunget oppsett-banner */}
      {!loading && mustSetup && !activeFlow && !chooseMethod && (
        <div className="mb-4 p-3 rounded-md bg-amber-50 border border-amber-200 text-sm text-amber-900">
          Din rolle krever 2FA. Velg metode for å fullføre oppsettet.
        </div>
      )}

      {/* Hovedstatus + handling */}
      {!loading && !activeFlow && !chooseMethod && (
        <div className="space-y-3">
          {!enabled && (
            <button onClick={() => setChooseMethod(true)} disabled={busy} className="btn btn-primary">
              <Lock className="w-4 h-4" /> Sett opp 2FA
            </button>
          )}
          {enabled && (
            <div className="flex flex-wrap gap-2">
              <button onClick={() => setChooseMethod(true)} disabled={busy} className="btn">
                Bytt metode
              </button>
              {!required && (
                <details className="w-full mt-2">
                  <summary className="cursor-pointer text-sm text-gray-600">Slå av 2FA</summary>
                  <form onSubmit={disable} className="space-y-3 mt-3">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Bekreft passord</label>
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
                </details>
              )}
              {required && (
                <p className="text-xs text-gray-500 w-full">
                  2FA kan ikke slås av for din rolle. Du kan bytte metode.
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Velg metode */}
      {chooseMethod && !activeFlow && (
        <div className="space-y-3">
          <p className="text-sm text-gray-700">Velg hvordan du vil motta engangskoder:</p>
          <div className="grid sm:grid-cols-2 gap-3">
            <button
              type="button"
              onClick={startEmailSetup}
              disabled={busy}
              className="border rounded-lg p-4 text-left hover:bg-amber-50 transition"
            >
              <div className="flex items-center gap-2 font-medium text-gray-900 mb-1">
                <Mail className="w-4 h-4 text-amber-600" /> E-post
              </div>
              <div className="text-xs text-gray-600">
                Vi sender en 6-sifret kode på e-post hver gang du logger inn. Anbefalt — ingen app trengs.
              </div>
            </button>
            <button
              type="button"
              onClick={startTotpSetup}
              disabled={busy}
              className="border rounded-lg p-4 text-left hover:bg-amber-50 transition"
            >
              <div className="flex items-center gap-2 font-medium text-gray-900 mb-1">
                <Smartphone className="w-4 h-4 text-amber-600" /> Autentiserings-app
              </div>
              <div className="text-xs text-gray-600">
                Bruk Google Authenticator, Authy, 1Password osv. Krever app på telefonen.
              </div>
            </button>
          </div>
          <button type="button" onClick={() => setChooseMethod(false)} className="btn">
            Avbryt
          </button>
        </div>
      )}

      {/* E-post-flow */}
      {activeFlow === 'email' && emailStep === 'sent' && (
        <form onSubmit={verifyEmailSetup} className="space-y-3">
          <p className="text-sm text-gray-700">Vi har sendt en 6-sifret kode på e-post. Skriv den inn under for å aktivere.</p>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Bekreftelseskode</label>
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
          <div className="flex gap-2 flex-wrap">
            <button type="submit" disabled={busy || code.length < 6} className="btn btn-primary">
              Aktiver e-post 2FA
            </button>
            <button type="button" onClick={startEmailSetup} disabled={busy} className="btn">
              Send på nytt
            </button>
            <button type="button" onClick={resetFlow} className="btn">
              Avbryt
            </button>
          </div>
        </form>
      )}

      {/* TOTP-flow */}
      {activeFlow === 'totp' && setupSecret && (
        <form onSubmit={confirmTotpEnable} className="space-y-3">
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
          <div className="flex gap-2 flex-wrap">
            <button type="submit" disabled={busy || code.length < 6} className="btn btn-primary">
              Aktiver app-2FA
            </button>
            <button type="button" onClick={resetFlow} className="btn">
              Avbryt
            </button>
          </div>
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
