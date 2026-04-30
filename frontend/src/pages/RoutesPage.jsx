import { useState, useEffect } from 'react';
import { Search, Plus, Edit2, Trash2, RefreshCw, Truck, Users, MapPin, ChevronRight, GripVertical, Mail, Wand2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

// Day names in Norwegian
const dayNames = {
  1: 'Mandag',
  2: 'Tirsdag',
  3: 'Onsdag',
  4: 'Torsdag',
  5: 'Fredag',
  6: 'Lørdag',
  7: 'Søndag'
};

export default function RoutesPage() {
  const { authFetch } = useAuth();
  const [routes, setRoutes] = useState([]);
  const [selectedRoute, setSelectedRoute] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [unassignedCustomers, setUnassignedCustomers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showNewRouteModal, setShowNewRouteModal] = useState(false);
  const [newRoute, setNewRoute] = useState({ name: '', description: '', delivery_days: [1, 2, 3, 4, 5] });
  const [postalRules, setPostalRules] = useState([]);
  const [newRule, setNewRule] = useState({ from_code: '', to_code: '', label: '' });
  const [autoPreview, setAutoPreview] = useState(null);

  const fetchRoutes = async () => {
    setLoading(true);
    try {
      const response = await authFetch('/api/v1/routes');
      if (!response.ok) throw new Error('Kunne ikke hente ruter');
      const data = await response.json();
      setRoutes(data.items || []);
      setError(null);
    } catch (err) {
      console.error('Error loading routes:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchRouteDetails = async (routeId) => {
    try {
      const response = await authFetch(`/api/v1/routes/${routeId}`);
      if (!response.ok) throw new Error('Kunne ikke hente rutedetaljer');
      const data = await response.json();
      setSelectedRoute(data);
      setCustomers(data.customers || []);
      setAutoPreview(null);
      // Hent postnummer-regler
      try {
        const r = await authFetch(`/api/v1/routes/${routeId}/postal-rules`);
        if (r.ok) setPostalRules(await r.json()); else setPostalRules([]);
      } catch { setPostalRules([]); }
    } catch (err) {
      console.error('Error loading route details:', err);
      setError(err.message);
    }
  };

  const addPostalRule = async () => {
    if (!selectedRoute || !newRule.from_code) return;
    const payload = {
      from_code: newRule.from_code.trim(),
      to_code: (newRule.to_code || newRule.from_code).trim(),
      label: newRule.label?.trim() || null,
    };
    try {
      const r = await authFetch(`/api/v1/routes/${selectedRoute.id}/postal-rules`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke legge til regel');
      }
      const created = await r.json();
      setPostalRules((prev) => [...prev, created].sort((a, b) => a.from_code.localeCompare(b.from_code)));
      setNewRule({ from_code: '', to_code: '', label: '' });
    } catch (err) {
      alert(err.message);
    }
  };

  const deletePostalRule = async (ruleId) => {
    if (!selectedRoute) return;
    if (!confirm('Slette denne postnummer-regelen?')) return;
    try {
      const r = await authFetch(`/api/v1/routes/${selectedRoute.id}/postal-rules/${ruleId}`, { method: 'DELETE' });
      if (!r.ok) throw new Error('Kunne ikke slette regel');
      setPostalRules((prev) => prev.filter(x => x.id !== ruleId));
    } catch (err) {
      alert(err.message);
    }
  };

  const previewAutoAssign = async () => {
    if (!selectedRoute) return;
    try {
      const r = await authFetch(`/api/v1/routes/${selectedRoute.id}/auto-assign-preview`);
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke kjore preview');
      }
      setAutoPreview(await r.json());
    } catch (err) {
      alert(err.message);
    }
  };

  const commitAutoAssign = async (overwrite = false) => {
    if (!selectedRoute || !autoPreview) return;
    const msg = overwrite
      ? `Overskriv tilordning for ${autoPreview.conflicts} kunder som er paa andre ruter, og tilordne ${autoPreview.new_assignments} nye?`
      : `Tilordne ${autoPreview.new_assignments} kunder uten rute til denne ruten?`;
    if (!confirm(msg)) return;
    try {
      const r = await authFetch(
        `/api/v1/routes/${selectedRoute.id}/auto-assign-commit?overwrite_conflicts=${overwrite}`,
        { method: 'POST' }
      );
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke tilordne');
      }
      const result = await r.json();
      alert(`Ferdig: ${result.assigned} kunder tilordnet.`);
      setAutoPreview(null);
      fetchRouteDetails(selectedRoute.id);
      fetchUnassignedCustomers();
    } catch (err) {
      alert(err.message);
    }
  };

  const fetchUnassignedCustomers = async () => {
    try {
      // Get customers without route_id
      const response = await authFetch('/api/v1/customers?has_route=false&page_size=500');
      if (!response.ok) throw new Error('Kunne ikke hente kunder');
      const data = await response.json();
      setUnassignedCustomers(data.items || []);
    } catch (err) {
      console.error('Error loading unassigned customers:', err);
    }
  };

  useEffect(() => {
    fetchRoutes();
    fetchUnassignedCustomers();
  }, []);

  const createRoute = async () => {
    try {
      const response = await authFetch('/api/v1/routes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newRoute)
      });
      if (!response.ok) throw new Error('Kunne ikke opprette rute');
      setShowNewRouteModal(false);
      setNewRoute({ name: '', description: '', delivery_days: [1, 2, 3, 4, 5] });
      fetchRoutes();
    } catch (err) {
      setError(err.message);
    }
  };

  const deleteRoute = async (routeId) => {
    if (!confirm('Er du sikker på at du vil slette denne ruten?')) return;
    try {
      const response = await authFetch(`/api/v1/routes/${routeId}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('Kunne ikke slette rute');
      setSelectedRoute(null);
      fetchRoutes();
    } catch (err) {
      setError(err.message);
    }
  };

  const assignCustomer = async (customerId) => {
    if (!selectedRoute) return;
    try {
      const response = await authFetch(`/api/v1/routes/${selectedRoute.id}/assign-customers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([customerId])
      });
      if (!response.ok) throw new Error('Kunne ikke tildele kunde');
      fetchRouteDetails(selectedRoute.id);
      fetchUnassignedCustomers();
    } catch (err) {
      setError(err.message);
    }
  };

  const removeCustomer = async (customerId) => {
    if (!selectedRoute) return;
    try {
      const response = await authFetch(`/api/v1/routes/${selectedRoute.id}/customers/${customerId}`, {
        method: 'DELETE'
      });
      if (!response.ok) throw new Error('Kunne ikke fjerne kunde');
      fetchRouteDetails(selectedRoute.id);
      fetchUnassignedCustomers();
    } catch (err) {
      setError(err.message);
    }
  };

  const openGoogleMaps = async () => {
    if (!selectedRoute) return;
    const today = new Date().toISOString().split('T')[0];
    try {
      const response = await authFetch(`/api/v1/reports/delivery-list/${selectedRoute.id}/${today}/google-maps-url`);
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke generere Google Maps-lenke');
      }
      const data = await response.json();
      if (data.fallback_used) {
        // Ingen ordrer i dag - viser ruten basert paa kundenes adresser i stedet
      }
      window.open(data.url, '_blank');
    } catch (err) {
      alert(err.message);
    }
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <RefreshCw className="w-6 h-6 animate-spin text-amber-600" />
        <span className="ml-2 text-gray-500">Laster ruter...</span>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Leveringsruter</h1>
          <p className="page-subtitle">{routes.length} ruter definert</p>
        </div>
        <div className="flex gap-2">
          <button onClick={fetchRoutes} className="btn-secondary" title="Oppdater">
            <RefreshCw className="w-4 h-4" /> Oppdater
          </button>
          <button onClick={() => setShowNewRouteModal(true)} className="btn-primary">
            <Plus className="w-4 h-4" /> Ny rute
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">{error}</div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Routes List */}
        <div className="lg:col-span-1">
          <div className="card">
            <h2 className="text-sm font-semibold text-gray-900 mb-3 uppercase tracking-wider">Ruter</h2>
            <div className="space-y-1.5">
              {routes.map(route => (
                <div
                  key={route.id}
                  onClick={() => fetchRouteDetails(route.id)}
                  className={`p-3 rounded-md border cursor-pointer transition-all ${
                    selectedRoute?.id === route.id
                      ? 'border-amber-500 bg-amber-50'
                      : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <div className={`p-1.5 rounded ${route.is_active ? 'bg-green-100' : 'bg-gray-100'}`}>
                        <Truck className={`w-4 h-4 ${route.is_active ? 'text-green-600' : 'text-gray-400'}`} />
                      </div>
                      <div>
                        <h3 className="font-medium text-gray-900 text-sm">{route.name}</h3>
                        <p className="text-xs text-gray-500">
                          {route.delivery_days?.map(d => dayNames[d]?.substring(0, 2)).join(', ')}
                        </p>
                      </div>
                    </div>
                    <ChevronRight className="w-4 h-4 text-gray-400" />
                  </div>
                </div>
              ))}
              {routes.length === 0 && (
                <p className="text-gray-500 text-center py-4 text-sm">Ingen ruter definert</p>
              )}
            </div>
          </div>
        </div>

        {/* Route Details */}
        <div className="lg:col-span-2">
          {selectedRoute ? (
            <div className="card">
              <div className="flex items-center justify-between mb-4 pb-4 border-b border-gray-200">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">{selectedRoute.name}</h2>
                  {selectedRoute.description && (
                    <p className="text-sm text-gray-500">{selectedRoute.description}</p>
                  )}
                </div>
                <div className="flex gap-2">
                  <button onClick={openGoogleMaps} className="btn-secondary">
                    <MapPin className="w-4 h-4" /> Google Maps
                  </button>
                  <button
                    onClick={() => deleteRoute(selectedRoute.id)}
                    className="p-1.5 text-red-600 hover:bg-red-50 rounded"
                    title="Slett rute"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Delivery Days */}
              <div className="mb-4">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">Leveringsdager</h3>
                <div className="flex gap-1.5 flex-wrap">
                  {[1, 2, 3, 4, 5, 6, 7].map(day => (
                    <span
                      key={day}
                      className={`badge ${
                        selectedRoute.delivery_days?.includes(day) ? 'badge-amber' : 'badge-neutral opacity-50'
                      }`}
                    >
                      {dayNames[day]}
                    </span>
                  ))}
                </div>
              </div>

              {/* Postnummer-regler */}
              <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 flex items-center gap-1.5">
                    <Mail className="w-3.5 h-3.5" />
                    Postnummer-serier ({postalRules.length})
                  </h3>
                  {postalRules.length > 0 && (
                    <button onClick={previewAutoAssign} className="btn-secondary !py-1 !text-xs">
                      <Wand2 className="w-3.5 h-3.5" /> Auto-tilordne kunder
                    </button>
                  )}
                </div>
                <div className="space-y-1 mb-2">
                  {postalRules.map((rule) => (
                    <div key={rule.id} className="flex items-center gap-2 p-2 bg-gray-50 rounded-md text-sm">
                      <span className="font-mono font-medium text-gray-900">
                        {rule.from_code}{rule.from_code !== rule.to_code ? ` – ${rule.to_code}` : ''}
                      </span>
                      {rule.label && <span className="text-xs text-gray-500">{rule.label}</span>}
                      <button
                        onClick={() => deletePostalRule(rule.id)}
                        className="ml-auto p-1 text-red-500 hover:bg-red-100 rounded"
                        title="Slett serie"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                  {postalRules.length === 0 && (
                    <p className="text-gray-500 text-xs italic">
                      Ingen serier definert. Legg til en serie for å auto-tilordne kunder etter postnummer.
                    </p>
                  )}
                </div>
                <div className="flex gap-2 items-center flex-wrap">
                  <input
                    type="text"
                    value={newRule.from_code}
                    onChange={(e) => setNewRule({ ...newRule, from_code: e.target.value })}
                    className="input !py-1 !text-sm w-24"
                    placeholder="Fra"
                    inputMode="numeric"
                  />
                  <span className="text-gray-400">–</span>
                  <input
                    type="text"
                    value={newRule.to_code}
                    onChange={(e) => setNewRule({ ...newRule, to_code: e.target.value })}
                    className="input !py-1 !text-sm w-24"
                    placeholder="Til (valgfri)"
                    inputMode="numeric"
                  />
                  <input
                    type="text"
                    value={newRule.label}
                    onChange={(e) => setNewRule({ ...newRule, label: e.target.value })}
                    className="input !py-1 !text-sm flex-1 min-w-32"
                    placeholder="Etikett (valgfri)"
                  />
                  <button onClick={addPostalRule} className="btn-primary !py-1 !text-xs">
                    <Plus className="w-3.5 h-3.5" /> Legg til
                  </button>
                </div>
                {autoPreview && (
                  <div className="mt-3 p-3 border border-amber-300 bg-amber-50 rounded-md text-sm">
                    <p className="font-medium text-amber-900 mb-2">
                      Forhåndsvisning: {autoPreview.matched_customers} kunder matcher
                    </p>
                    <ul className="text-xs text-gray-700 space-y-0.5 mb-2">
                      <li>• {autoPreview.new_assignments} nye (uten rute) tilordnes</li>
                      <li>• {autoPreview.already_on_route} er allerede på denne ruten</li>
                      <li>• {autoPreview.conflicts} er allerede på en annen rute</li>
                    </ul>
                    {autoPreview.conflict_examples?.length > 0 && (
                      <details className="text-xs text-gray-600 mb-2">
                        <summary className="cursor-pointer">Vis konflikter</summary>
                        <ul className="mt-1 space-y-0.5">
                          {autoPreview.conflict_examples.map((c) => (
                            <li key={c.customer_id}>{c.name} ({c.postal_code}) → rute #{c.current_route_id}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                    <div className="flex gap-2 flex-wrap">
                      <button onClick={() => commitAutoAssign(false)} className="btn-primary !py-1 !text-xs" disabled={autoPreview.new_assignments === 0}>
                        Tilordne {autoPreview.new_assignments} nye
                      </button>
                      {autoPreview.conflicts > 0 && (
                        <button onClick={() => commitAutoAssign(true)} className="btn-secondary !py-1 !text-xs">
                          Overskriv {autoPreview.conflicts} konflikter
                        </button>
                      )}
                      <button onClick={() => setAutoPreview(null)} className="text-xs text-gray-600 hover:text-gray-900 ml-auto">
                        Lukk
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* Customers on route */}
              <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 flex items-center gap-1.5">
                    <Users className="w-3.5 h-3.5" />
                    Kunder på rute ({customers.length})
                  </h3>
                </div>
                <div className="space-y-1 max-h-96 overflow-y-auto">
                  {customers.map((customer, idx) => (
                    <div
                      key={customer.id}
                      className="flex items-center gap-2.5 p-2 bg-gray-50 hover:bg-gray-100 rounded-md text-sm"
                    >
                      <GripVertical className="w-3.5 h-3.5 text-gray-400 cursor-grab" />
                      <span className="w-5 h-5 bg-amber-100 text-amber-700 rounded-full flex items-center justify-center text-xs font-medium">
                        {idx + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-gray-900 truncate">{customer.company_name || customer.name}</p>
                        <p className="text-xs text-gray-500 truncate">
                          {customer.street_address}, {customer.postal_code} {customer.city}
                        </p>
                      </div>
                      <button
                        onClick={() => removeCustomer(customer.id)}
                        className="p-1 text-red-500 hover:bg-red-100 rounded"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                  {customers.length === 0 && (
                    <p className="text-gray-500 text-center py-4 text-sm">Ingen kunder på denne ruten</p>
                  )}
                </div>
              </div>

              {/* Unassigned customers */}
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">Kunder uten rute</h3>
                <div className="space-y-1 max-h-48 overflow-y-auto">
                  {unassignedCustomers.slice(0, 10).map(customer => (
                    <div
                      key={customer.id}
                      className="flex items-center justify-between p-2 border border-dashed border-gray-300 rounded-md hover:border-amber-400 hover:bg-amber-50 transition-all cursor-pointer text-sm"
                      onClick={() => assignCustomer(customer.id)}
                    >
                      <div className="min-w-0">
                        <p className="font-medium text-gray-900 truncate">{customer.company_name || customer.name}</p>
                        <p className="text-xs text-gray-500">{customer.city}</p>
                      </div>
                      <Plus className="w-4 h-4 text-amber-600 flex-shrink-0" />
                    </div>
                  ))}
                  {unassignedCustomers.length > 10 && (
                    <p className="text-gray-500 text-center py-2 text-sm">
                      + {unassignedCustomers.length - 10} flere kunder
                    </p>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="card flex items-center justify-center h-96">
              <div className="text-center text-gray-500">
                <Truck className="w-10 h-10 mx-auto mb-3 text-gray-300" />
                <p className="text-sm">Velg en rute for å se detaljer</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* New Route Modal */}
      {showNewRouteModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h2 className="text-xl font-bold text-gray-900 mb-4">Ny leveringsrute</h2>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Navn</label>
                <input
                  type="text"
                  value={newRoute.name}
                  onChange={(e) => setNewRoute({...newRoute, name: e.target.value})}
                  className="input w-full"
                  placeholder="f.eks. Rute 1 - Sentrum"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Beskrivelse</label>
                <input
                  type="text"
                  value={newRoute.description}
                  onChange={(e) => setNewRoute({...newRoute, description: e.target.value})}
                  className="input w-full"
                  placeholder="Valgfri beskrivelse"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Leveringsdager</label>
                <div className="flex flex-wrap gap-2">
                  {[1, 2, 3, 4, 5, 6, 7].map(day => (
                    <button
                      key={day}
                      type="button"
                      onClick={() => {
                        const days = newRoute.delivery_days.includes(day)
                          ? newRoute.delivery_days.filter(d => d !== day)
                          : [...newRoute.delivery_days, day].sort();
                        setNewRoute({...newRoute, delivery_days: days});
                      }}
                      className={`px-3 py-1 rounded-full text-sm ${
                        newRoute.delivery_days.includes(day)
                          ? 'bg-amber-500 text-white'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      {dayNames[day]}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setShowNewRouteModal(false)}
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg"
              >
                Avbryt
              </button>
              <button
                onClick={createRoute}
                disabled={!newRoute.name}
                className="btn-primary disabled:opacity-50"
              >
                Opprett rute
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
