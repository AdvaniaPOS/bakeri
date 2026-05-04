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
  const [restrictToFavorites, setRestrictToFavorites] = useState(false);
  const [showAllProducts, setShowAllProducts] = useState(false);
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

  // Last produkter + favorittstatus når outlet endres
  useEffect(() => {
    if (!outletId) return;
    const token = localStorage.getItem('access_token');
    setLoadingProducts(true);
    Promise.all([
      fetch(`${API_BASE}/portal/products?customer_id=${outletId}`, {
        headers: { Authorization: `Bearer ${token}` },
      }).then(r => r.ok ? r.json() : []),
      fetch(`${API_BASE}/portal/restrictions?customer_id=${outletId}`, {
        headers: { Authorization: `Bearer ${token}` },
      }).then(r => r.ok ? r.json() : { restrict_to_favorites: false }),
    ])
      .then(([prods, restr]) => {
        setProducts(prods || []);
        setRestrictToFavorites(!!restr?.restrict_to_favorites);
        setShowAllProducts(false);
      })
      .catch(() => { setProducts([]); setRestrictToFavorites(false); })
      .finally(() => setLoadingProducts(false));
  }, [outletId]);

  const filtered = useMemo(() => {
    // Hvis kunden er begrenset til favoritter: vis kun favoritter (alltid)
    // Ellers: vis favoritter øverst, og resten under hvis showAllProducts er på
    const s = search.trim().toLowerCase();
    const matchesSearch = (p) => !s ||
      p.name.toLowerCase().includes(s) ||
      (p.sku || '').toLowerCase().includes(s);

    if (restrictToFavorites) {
      return products.filter(p => p.is_favorite && matchesSearch(p));
    }
    if (s) {
      // Søk overstyrer favoritt-filter slik at man finner det man leter etter
      return products.filter(matchesSearch);
    }
    if (showAllProducts) return products;
    // Default: kun favoritter
    const favs = products.filter(p => p.is_favorite);
    return favs.length > 0 ? favs : products;
  }, [products, search, restrictToFavorites, showAllProducts]);

  const totalLines = Object.values(quantities).filter(q => q > 0).length;
  const totalAmount = useMemo(() => {
    let sum = 0;
    for (const p of products) {
      const q = quantities[p.id] || 0;
      if (q > 0) sum += q * Number(p.unit_price || 0);
    }
    return sum;
  }, [products, quantities]);

  // Valgte linjer (for oppsummering)
  const selectedLines = useMemo(() => {
    return products
      .filter(p => (quantities[p.id] || 0) > 0)
      .map(p => {
        const q = quantities[p.id];
        const price = Number(p.unit_price || 0);
        return { ...p, quantity: q, line_total: q * price };
      });
  }, [products, quantities]);

  const setQty = (productId, value) => {
    setQuantities(q => ({
      ...q,
      [productId]: value === '' ? 0 : Math.max(0, parseInt(value, 10) || 0),
    }));
  };
  const removeLine = (productId) => {
    setQuantities(q => {
      const next = { ...q };
      delete next[productId];
      return next;
    });
  };

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
        <div className="px-4 py-3 border-b border-amber-100 flex flex-wrap items-center gap-3">
          <h2 className="font-semibold text-amber-900">
            {restrictToFavorites ? 'Favoritter' : (showAllProducts || search.trim() ? 'Alle produkter' : 'Mine favoritter')}
          </h2>
          {!restrictToFavorites && !search.trim() && (
            <button
              type="button"
              onClick={() => setShowAllProducts(v => !v)}
              className="text-xs px-2 py-1 rounded border border-amber-300 text-amber-800 hover:bg-amber-100"
            >
              {showAllProducts ? 'Vis kun favoritter' : 'Vis alle produkter'}
            </button>
          )}
          {restrictToFavorites && (
            <span className="text-xs px-2 py-1 rounded bg-amber-100 text-amber-800">
              Du kan kun bestille fra favorittlisten din
            </span>
          )}
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={restrictToFavorites ? 'Søk i favoritter…' : 'Søk produkt eller SKU…'}
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
                      <div className="font-medium">
                        {p.is_favorite && <span className="text-amber-500 mr-1" title="Favoritt">★</span>}
                        {p.name}
                      </div>
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
                        onChange={(e) => setQty(p.id, e.target.value)}
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

      <div className="bg-white border border-amber-200 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-amber-100 flex items-center gap-3">
          <h2 className="font-semibold text-amber-900">Oppsummering</h2>
          <span className="text-xs text-gray-500">({selectedLines.length} {selectedLines.length === 1 ? 'linje' : 'linjer'})</span>
        </div>
        {selectedLines.length === 0 ? (
          <div className="p-4 text-sm text-gray-500">Ingen produkter valgt ennå. Legg inn antall i produktlisten over.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-amber-50 text-xs uppercase text-amber-800">
              <tr>
                <th className="text-left px-3 py-2">Produkt</th>
                <th className="text-right px-3 py-2">Pris</th>
                <th className="text-right px-3 py-2 w-32">Antall</th>
                <th className="text-right px-3 py-2">Sum</th>
                <th className="px-3 py-2 w-12"></th>
              </tr>
            </thead>
            <tbody>
              {selectedLines.map(l => (
                <tr key={l.id} className="border-t border-amber-100">
                  <td className="px-3 py-2">
                    <div className="font-medium">{l.name}</div>
                    {l.sku && <div className="text-xs text-gray-500">{l.sku} · {l.unit}</div>}
                  </td>
                  <td className="px-3 py-2 text-right">{Number(l.unit_price).toFixed(2)} kr</td>
                  <td className="px-3 py-2">
                    <input
                      type="number"
                      min="0"
                      value={l.quantity}
                      onChange={(e) => setQty(l.id, e.target.value)}
                      className="w-24 border border-gray-300 rounded-md px-2 py-1 text-sm text-right"
                    />
                  </td>
                  <td className="px-3 py-2 text-right font-medium">{l.line_total.toFixed(2)} kr</td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => removeLine(l.id)}
                      className="text-red-600 hover:text-red-800 text-xs"
                      title="Fjern"
                    >✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-amber-50">
              <tr>
                <td colSpan={3} className="px-3 py-2 text-right font-semibold">Totalt (eks. mva)</td>
                <td className="px-3 py-2 text-right font-bold text-amber-900">{totalAmount.toFixed(2)} kr</td>
                <td></td>
              </tr>
            </tfoot>
          </table>
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
