/**
 * Velkomst-wizard som vises første gang en tenant logger inn.
 * Markeres som fullført ved å sette settings.onboarding_completed = true.
 *
 * Viser bare for TENANT_ADMIN/SUPER_ADMIN på Dashboard.
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Check, ChevronRight, X, Sparkles, Settings as SettingsIcon, Users, Package } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

const STEPS = [
  {
    id: 'welcome',
    title: 'Velkommen!',
    icon: Sparkles,
    body: (tenantName) => (
      <>
        <p className="text-sm text-gray-700">
          Velkommen til <strong>{tenantName}</strong> sitt ordresystem. Vi hjelper deg
          med en rask start.
        </p>
        <p className="text-sm text-gray-700 mt-3">
          Wizardden tar under 2 minutter og guider deg gjennom det viktigste.
        </p>
      </>
    ),
  },
  {
    id: 'settings',
    title: 'Sjekk firmaopplysningene',
    icon: SettingsIcon,
    body: () => (
      <>
        <p className="text-sm text-gray-700">
          Gå til <Link to="/innstillinger" className="text-amber-600 underline">Innstillinger</Link>{' '}
          og sjekk at navn, logo, tema og leveringsregler stemmer. Disse vises på
          ordrer, etiketter og PDF-utskrifter.
        </p>
      </>
    ),
  },
  {
    id: 'team',
    title: 'Inviter teamet',
    icon: Users,
    body: () => (
      <>
        <p className="text-sm text-gray-700">
          Inviter kollegene dine fra <Link to="/innstillinger" className="text-amber-600 underline">Innstillinger → Brukere</Link>.
          De får en e-post med lenke for å opprette konto. Du velger rollen deres
          (admin, manager, sjåfør eller viewer).
        </p>
      </>
    ),
  },
  {
    id: 'data',
    title: 'Importer kunder og produkter',
    icon: Package,
    body: () => (
      <>
        <p className="text-sm text-gray-700">
          Hvis dere bruker SuSoft kan synkroniseringen aktiveres i Innstillinger.
          Ellers kan kunder og produkter legges til manuelt fra{' '}
          <Link to="/kunder" className="text-amber-600 underline">Kunder</Link> og{' '}
          <Link to="/produkter" className="text-amber-600 underline">Produkter</Link>.
        </p>
      </>
    ),
  },
];

export default function OnboardingWizard() {
  const { tenant, isAdmin, authFetch, updateTenant } = useAuth();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const completed = tenant?.settings?.onboarding_completed === true;
  if (completed || dismissed || !tenant || !isAdmin()) return null;

  const isLast = step === STEPS.length - 1;
  const current = STEPS[step];
  const Icon = current.icon;

  const finish = async () => {
    setSaving(true);
    try {
      const resp = await authFetch('/api/v1/admin/settings', {
        method: 'PUT',
        body: { onboarding_completed: true },
      });
      if (resp.ok) {
        const data = await resp.json().catch(() => ({}));
        // Oppdater lokalt tenant-objekt slik at wizarden ikke vises igjen
        updateTenant({ settings: { ...(tenant.settings || {}), ...(data.settings || { onboarding_completed: true }) } });
      }
    } catch {
      // Ikke kritisk — la brukeren lukke uansett
    } finally {
      setSaving(false);
      setDismissed(true);
    }
  };

  const skip = () => {
    setDismissed(true);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b">
          <div className="flex items-center gap-2 text-amber-700">
            <Icon className="w-5 h-5" />
            <h2 className="font-semibold">{current.title}</h2>
          </div>
          <button
            onClick={skip}
            className="text-gray-400 hover:text-gray-600"
            aria-label="Lukk"
            title="Hopp over"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6">{current.body(tenant.name)}</div>

        {/* Steg-indikator */}
        <div className="px-6 pb-3 flex gap-1">
          {STEPS.map((s, i) => (
            <div
              key={s.id}
              className={`h-1 flex-1 rounded-full ${
                i <= step ? 'bg-amber-600' : 'bg-gray-200'
              }`}
            />
          ))}
        </div>

        <div className="flex items-center justify-between p-4 border-t bg-gray-50 rounded-b-lg">
          <button
            onClick={skip}
            className="text-sm text-gray-600 hover:text-gray-800"
          >
            Hopp over
          </button>
          <div className="flex gap-2">
            {step > 0 && (
              <button
                onClick={() => setStep(s => s - 1)}
                className="btn-secondary"
              >
                Tilbake
              </button>
            )}
            {!isLast ? (
              <button
                onClick={() => setStep(s => s + 1)}
                className="btn-primary inline-flex items-center gap-1"
              >
                Neste <ChevronRight className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={finish}
                disabled={saving}
                className="btn-primary inline-flex items-center gap-1 disabled:opacity-50"
              >
                {saving ? 'Lagrer...' : (<>Ferdig <Check className="w-4 h-4" /></>)}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
