/**
 * Glemt passord — be om e-post med nullstillings-lenke.
 * Viser alltid samme suksessmelding (motvirker bruker-enumerering).
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';

export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState(null);
  const [doneMessage, setDoneMessage] = useState('');
  const helpText = 'For lokale kontoer sender vi en lenke på e-post. Hvis du logger inn med brukernavn eller via SuSoft, må passordet endres der eller av administrator.';

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const resp = await fetch('/api/v1/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
      });
      if (!resp.ok && resp.status !== 202) {
        throw new Error('Noe gikk galt — prøv igjen om litt.');
      }
      const data = await resp.json().catch(() => null);
      setDoneMessage(data?.message || 'Hvis innloggingen din er lokal, har vi sendt en lenke for nullstilling.');
      setDone(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen app-main flex items-center justify-center py-12 px-4">
      <div className="max-w-md w-full">
        <div className="text-center mb-6">
          <h1 className="text-xl font-semibold text-gray-900">Glemt passord</h1>
          <p className="mt-1 text-sm text-gray-500">
            Skriv inn e-postadressen eller brukernavnet ditt for å be om hjelp med innlogging.
          </p>
        </div>
        <div className="card">
          {done ? (
            <div className="space-y-4">
              <div className="bg-green-50 border border-green-200 text-green-800 px-3 py-2 rounded-md text-sm">
                {doneMessage}
              </div>
              <div className="bg-amber-50 border border-amber-200 text-amber-900 px-3 py-2 rounded-md text-sm">
                {helpText}
              </div>
              <Link to="/login" className="btn-primary w-full justify-center">
                Tilbake til innlogging
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="bg-amber-50 border border-amber-200 text-amber-900 px-3 py-2 rounded-md text-sm">
                {helpText}
              </div>
              {error && (
                <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-md text-sm">
                  {error}
                </div>
              )}
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
                  E-post eller brukernavn
                </label>
                <input
                  id="email"
                  type="text"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="input w-full"
                  placeholder="din@epost.no eller brukernavn"
                  autoFocus
                />
              </div>
              <button
                type="submit"
                disabled={submitting || !email}
                className="btn-primary w-full justify-center disabled:opacity-50"
              >
                {submitting ? 'Sender...' : 'Send nullstillings-lenke'}
              </button>
              <div className="text-center">
                <Link to="/login" className="text-sm text-amber-600 hover:text-amber-700">
                  Tilbake til innlogging
                </Link>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
