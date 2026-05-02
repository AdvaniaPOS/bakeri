/**
 * Nullstill passord — leser ?token= fra URL og lar bruker sette nytt passord.
 */
import { useState } from 'react';
import { Link, useSearchParams, useNavigate } from 'react-router-dom';

export default function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get('token') || '';

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError('Passordene er ikke like');
      return;
    }
    setSubmitting(true);
    try {
      const resp = await fetch('/api/v1/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(data.detail || 'Kunne ikke oppdatere passord');
      }
      setDone(true);
      setTimeout(() => navigate('/login'), 2500);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (!token) {
    return (
      <div className="min-h-screen app-main flex items-center justify-center py-12 px-4">
        <div className="max-w-md w-full card">
          <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-md text-sm">
            Mangler token i lenken. Be om en ny nullstillings-lenke.
          </div>
          <Link to="/glemt-passord" className="btn-primary w-full justify-center mt-4">
            Be om ny lenke
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen app-main flex items-center justify-center py-12 px-4">
      <div className="max-w-md w-full">
        <div className="text-center mb-6">
          <h1 className="text-xl font-semibold text-gray-900">Sett nytt passord</h1>
        </div>
        <div className="card">
          {done ? (
            <div className="bg-green-50 border border-green-200 text-green-800 px-3 py-2 rounded-md text-sm">
              Passordet er oppdatert. Sender deg til innlogging…
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-md text-sm">
                  {error}
                </div>
              )}
              <div>
                <label htmlFor="pw" className="block text-sm font-medium text-gray-700 mb-1">
                  Nytt passord
                </label>
                <input
                  id="pw"
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input w-full"
                  autoFocus
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
                disabled={submitting || !password || !confirm}
                className="btn-primary w-full justify-center disabled:opacity-50"
              >
                {submitting ? 'Lagrer...' : 'Lagre nytt passord'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
