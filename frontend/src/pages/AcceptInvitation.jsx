/**
 * Aksepter invitasjon — leser ?token= fra URL, samler inn navn + passord
 * og oppretter brukerkontoen. Logger inn automatisk ved suksess.
 */
import { useState } from 'react';
import { Link, useSearchParams, useNavigate } from 'react-router-dom';

const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_KEY = 'user';
const TENANT_KEY = 'tenant';

export default function AcceptInvitation() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get('token') || '';

  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError('Passordene er ikke like');
      return;
    }
    setSubmitting(true);
    try {
      const resp = await fetch('/api/v1/auth/accept-invitation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, name, password }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(data.detail || 'Kunne ikke akseptere invitasjon');
      }
      // Logg inn automatisk
      localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
      localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));
      localStorage.setItem(TENANT_KEY, JSON.stringify(data.tenant));
      // Tving full reload så AuthProvider plukker opp tokenene.
      window.location.href = '/';
    } catch (err) {
      setError(err.message);
      setSubmitting(false);
    }
  };

  if (!token) {
    return (
      <div className="min-h-screen app-main flex items-center justify-center py-12 px-4">
        <div className="max-w-md w-full card">
          <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-md text-sm">
            Mangler token i lenken. Be administratoren din om å sende invitasjonen på nytt.
          </div>
          <Link to="/login" className="btn-primary w-full justify-center mt-4">
            Til innlogging
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen app-main flex items-center justify-center py-12 px-4">
      <div className="max-w-md w-full">
        <div className="text-center mb-6">
          <h1 className="text-xl font-semibold text-gray-900">Aksepter invitasjon</h1>
          <p className="mt-1 text-sm text-gray-500">
            Velg navn og passord for å fullføre opprettelsen av brukerkontoen din.
          </p>
        </div>
        <div className="card">
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-md text-sm">
                {error}
              </div>
            )}
            <div>
              <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
                Fullt navn
              </label>
              <input
                id="name"
                type="text"
                required
                minLength={2}
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="input w-full"
                autoFocus
              />
            </div>
            <div>
              <label htmlFor="pw" className="block text-sm font-medium text-gray-700 mb-1">
                Passord
              </label>
              <input
                id="pw"
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input w-full"
              />
              <p className="text-xs text-gray-500 mt-1">
                Minst 8 tegn, store/små bokstaver, tall og spesialtegn.
              </p>
            </div>
            <div>
              <label htmlFor="pw2" className="block text-sm font-medium text-gray-700 mb-1">
                Bekreft passord
              </label>
              <input
                id="pw2"
                type="password"
                required
                minLength={8}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="input w-full"
              />
            </div>
            <button
              type="submit"
              disabled={submitting}
              className="btn-primary w-full justify-center disabled:opacity-50"
            >
              {submitting ? 'Oppretter konto...' : 'Opprett konto og logg inn'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
