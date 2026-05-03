import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';

const API_BASE = '/api/v1';

function tomorrowIso() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
}

function isPastCutoff(dateStr) {
  // Cutoff: 15:00 dagen før leveringsdato.
  // Hvis det er før 15:00 i dag og leveringsdato == i morgen → OK.
  // Enkel klient-sjekk; backend validerer for sikkerhet.
  if (!dateStr) return false;
  const today = new Date();
  const delivery = new Date(dateStr + 'T00:00:00');
  const cutoff = new Date(delivery);
  cutoff.setDate(cutoff.getDate() - 1);
  cutoff.setHours(15, 0, 0, 0);
  return today >= cutoff;
}

export default function PortalNewOrder() {
  const { me } = useOutletContext();
  const navigate = useNavigate();

  const [outletId, setOutletId] = useState(null);
  const [deliveryDate, setDeliveryDate] = useState(tomorrowIso());
  const [reference, setReference] = useState('');
  const [notes, setNotes] = useState('');
  const [products, setProducts] = useState([]);
  const [search, setSearch] = useState('');
  const [quantities, setQuantities] = useState({}); // product_id -> qty
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  // Sett default outlet når me lastes
  useEffect(() => {
    if (me?.outlets?.length && outletId == null) {
      setOutletId(me.outlets[0].id);
    }
  }, [me, outletId]);

  // Last produkter når outlet endres
  useEffect(() => {
    if (!outletId) return;
    const token = localStorage.getItem('access_token');
    setLoadingProducts(true);
    fetch(`${API_BASE}/portal/products?customer_id=${outletId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : [])
      .then(data => setProducts(data || []))
      .catch(() => setProducts([]))
      .finally(() => setLoadingProducts(false));
  }, [outletId]);

  const filtered = useMemo(() => {
    if (!search.trim()) return products;
    const s = search.toLowerCase();
    return products.filter(p =>
      p.name.toLowerCase().includes(s) || (p.sku || '').toLowerCase().includes(s)
    );
  }, [products, search]);

  const totalLines = Object.values(quantities).filter(q => q > 0).length;
  const totalAmount = useMemo(() => {
    let sum = 0;
    for (const p of products) {
      const q = quantities[p.id] || 0;
      if (q > 0) sum += q * Number(p.unit_price || 0);
    }
    return sum;
  }, [products, quantities]);

  const cutoffPassed = isPastCutoff(deliveryDate);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    if (!outletId) return setError('Velg utsalg');
    const lines = Object.entries(quantities)
      .filter(([, q]) => q > 0)
      .map(([pid, q]) => ({ product_id: Number(pid), quantity: Number(q) }));
    if (lines.length === 0) return setError('Legg inn antall på minst ett produkt');
    if (cutoffPassed) return setError('Bestillingsfristen for denne datoen har passert (kl 15:00 dagen før).');

    setSubmitting(true);
    try {
      const token = localStorage.getItem('access_token');
      const resp = await fetch(`${API_BASE}/portal/orders`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          customer_id: outletId,
          delivery_date: deliveryDate,
          reference: reference.trim() || null,
          customer_notes: notes.trim() || null,
          lines,
        }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || 'Klarte ikke å sende bestillingen');
      }
      navigate('/portal');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (!me) return <div className="text-gray-600">Laster…</div>;

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <h1 className="text-2xl font-bold text-amber-900">Ny bestilling</h1>

      <div className="bg-white border border-amber-200 rounded-lg p-4 space-y-4">
        {me.outlets.length > 1 && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Utsalg</label>
            <select
              value={outletId || ''}
              onChange={(e) => setOutletId(Number(e.target.value))}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            >
              {me.outlets.map(o => (
                <option key={o.id} value={o.id}>
                  {o.name}{o.is_main ? ' (hovedutsalg)' : ''}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Leveringsdato</label>
            <input
              type="date"
              value={deliveryDate}
              min={new Date().toISOString().slice(0, 10)}
              onChange={(e) => setDeliveryDate(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            />
            {cutoffPassed && (
              <div className="mt-1 text-xs text-red-700">
                ⚠ Cutoff for denne datoen er passert (15:00 dagen før).
              </div>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Referanse / PO-nr</label>
            <input
              type="text"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="Valgfri"
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Notater til bakeriet</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            placeholder="Valgfritt"
          />
        </div>
      </div>

      <div className="bg-white border border-amber-200 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-amber-100 flex items-center gap-3">
          <h2 className="font-semibold text-amber-900">Produkter</h2>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Søk produkt eller SKU…"
            className="ml-auto border border-gray-300 rounded-md px-3 py-1.5 text-sm w-64"
          />
        </div>
        {loadingProducts ? (
          <div className="p-6 text-gray-600">Laster produkter…</div>
        ) : (
          <div className="max-h-[60vh] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-amber-50 text-xs uppercase text-amber-800 sticky top-0">
                <tr>
                  <th className="text-left px-3 py-2">Produkt</th>
                  <th className="text-left px-3 py-2">Enhet</th>
                  <th className="text-right px-3 py-2">Pris</th>
                  <th className="text-right px-3 py-2 w-32">Antall</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(p => (
                  <tr key={p.id} className="border-t border-amber-100 hover:bg-amber-50">
                    <td className="px-3 py-2">
                      <div className="font-medium">{p.name}</div>
                      {p.sku && <div className="text-xs text-gray-500">{p.sku}</div>}
                    </td>
                    <td className="px-3 py-2">{p.unit}</td>
                    <td className="px-3 py-2 text-right">
                      {Number(p.unit_price).toFixed(2)} kr
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="number"
                        min="0"
                        value={quantities[p.id] || ''}
                        onChange={(e) => {
                          const v = e.target.value;
                          setQuantities(q => ({ ...q, [p.id]: v === '' ? 0 : Math.max(0, parseInt(v, 10) || 0) }));
                        }}
                        className="w-24 border border-gray-300 rounded-md px-2 py-1 text-sm text-right"
                      />
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr><td colSpan={4} className="text-center px-3 py-6 text-gray-500">
                    Ingen produkter funnet
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="bg-white border border-amber-200 rounded-lg p-4 flex flex-wrap items-center gap-4">
        <div className="text-sm">
          <div className="text-gray-600">Antall produkter</div>
          <div className="text-xl font-bold text-amber-900">{totalLines}</div>
        </div>
        <div className="text-sm">
          <div className="text-gray-600">Estimert sum (eks. mva)</div>
          <div className="text-xl font-bold text-amber-900">
            {totalAmount.toFixed(2)} kr
          </div>
        </div>
        {error && (
          <div className="text-red-700 text-sm bg-red-50 px-3 py-2 rounded border border-red-200">
            {error}
          </div>
        )}
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={() => navigate('/portal')}
            className="px-4 py-2 border border-gray-300 rounded-md text-sm hover:bg-gray-50"
          >
            Avbryt
          </button>
          <button
            type="submit"
            disabled={submitting || cutoffPassed}
            className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-md text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? 'Sender…' : 'Send bestilling'}
          </button>
        </div>
      </div>
    </form>
  );
}
