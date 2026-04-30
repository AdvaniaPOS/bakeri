import { useState, useEffect, useMemo } from 'react';
import { Search, Plus, Building2, Phone, Mail, MapPin, RefreshCw, Edit2, X, Check, ClipboardList, AlertTriangle, CalendarClock, PlayCircle, PauseCircle, Eye, EyeOff } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import QuickOverrideModal from '../components/QuickOverrideModal';
import Pagination from '../components/Pagination';

export default function Customers() {
  const { authFetch } = useAuth();
  const [customers, setCustomers] = useState([]);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('active');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showNewModal, setShowNewModal] = useState(false);
  const [editingCustomer, setEditingCustomer] = useState(null);
  const [overrideCustomer, setOverrideCustomer] = useState(null);
  const [planCustomer, setPlanCustomer] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const fetchCustomers = async () => {
    setLoading(true);
    try {
      const response = await authFetch('/api/v1/customers?page_size=1000');
      if (!response.ok) throw new Error('Kunne ikke hente kunder');
      const data = await response.json();
      setCustomers(data.items || []);
      setError(null);
    } catch (err) {
      console.error('Fetch error:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCustomers();
  }, []);

  const activeCount = customers.filter(c => c.is_active).length;
  const inactiveCount = customers.length - activeCount;

  const filteredCustomers = customers.filter(c => {
    const matchesSearch =
      c.name?.toLowerCase().includes(search.toLowerCase()) ||
      c.contact_person?.toLowerCase().includes(search.toLowerCase()) ||
      c.city?.toLowerCase().includes(search.toLowerCase());

    const matchesStatus =
      statusFilter === 'all' ||
      (statusFilter === 'active' && c.is_active) ||
      (statusFilter === 'inactive' && !c.is_active);

    return matchesSearch && matchesStatus;
  });

  // Reset page when filter/search changes
  useEffect(() => { setPage(1); }, [search, statusFilter, pageSize]);

  const pagedCustomers = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredCustomers.slice(start, start + pageSize);
  }, [filteredCustomers, page, pageSize]);

  const handleSaveCustomer = async (customerData) => {
    try {
      const url = editingCustomer 
        ? `/api/v1/customers/${editingCustomer.id}`
        : '/api/v1/customers';
      
      const response = await authFetch(url, {
        method: editingCustomer ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(customerData)
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Kunne ikke lagre kunde');
      }

      setShowNewModal(false);
      setEditingCustomer(null);
      fetchCustomers();
    } catch (err) {
      alert(err.message);
    }
  };

  const toggleActive = async (customer) => {
    const next = !customer.is_active;
    if (!next && !confirm(`Skjul "${customer.name}"? Kunden blir inaktiv og skjult fra lister.`)) return;
    try {
      const response = await authFetch(`/api/v1/customers/${customer.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: next })
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke endre status');
      }
      // Optimistisk oppdatering
      setCustomers((prev) => prev.map(c => c.id === customer.id ? { ...c, is_active: next } : c));
    } catch (err) {
      alert(err.message);
    }
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <RefreshCw className="w-6 h-6 animate-spin text-amber-600" />
        <span className="ml-2 text-gray-500">Laster kunder...</span>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <div className="page-header">
        <div>
          <h1 className="page-title">Kunder</h1>
          <p className="page-subtitle">{customers.length} kunder fra SuSoft</p>
        </div>
        <div className="flex gap-2">
          <button onClick={fetchCustomers} className="btn-secondary" title="Oppdater">
            <RefreshCw className="w-4 h-4" /> Oppdater
          </button>
          <button onClick={() => setShowNewModal(true)} className="btn-primary">
            <Plus className="w-4 h-4" />
            Ny kunde
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">{error}</div>
      )}

      <div className="card p-0 overflow-hidden">
        {/* Filter-bar */}
        <div className="px-3 py-2 border-b border-gray-200 flex flex-wrap items-center gap-2 bg-white">
          <div className="flex gap-1 bg-gray-100 rounded-md p-0.5">
            <button
              onClick={() => setStatusFilter('all')}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                statusFilter === 'all' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Alle ({customers.length})
            </button>
            <button
              onClick={() => setStatusFilter('active')}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                statusFilter === 'active' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Aktive ({activeCount})
            </button>
            <button
              onClick={() => setStatusFilter('inactive')}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                statusFilter === 'inactive' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Skjulte ({inactiveCount})
            </button>
          </div>
          <div className="relative flex-1 min-w-[220px]">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Søk og filtrer..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="input pl-8"
            />
          </div>
        </div>

        {filteredCustomers.length === 0 ? (
          <div className="text-center py-12 text-gray-500 text-sm">
            {customers.length === 0 ? 'Ingen kunder funnet. Synkroniser med SuSoft i Innstillinger.' : 'Ingen kunder matcher søket'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="shop-table">
              <thead>
                <tr>
                  <th>Kunde</th>
                  <th>Kontakt</th>
                  <th>Sted</th>
                  <th>SuSoft-ID</th>
                  <th>Ledetid</th>
                  <th>Status</th>
                  <th className="text-right">Handlinger</th>
                </tr>
              </thead>
              <tbody>
                {pagedCustomers.map((customer) => (
                  <tr key={customer.id}>
                    <td>
                      <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 bg-amber-100 rounded flex items-center justify-center flex-shrink-0">
                          <Building2 className="w-4 h-4 text-amber-600" />
                        </div>
                        <span className="font-medium text-gray-900">{customer.name}</span>
                      </div>
                    </td>
                    <td>
                      <div className="text-gray-700">
                        {customer.contact_person && <div>{customer.contact_person}</div>}
                        {customer.email && (
                          <a href={`mailto:${customer.email}`} className="text-xs text-amber-700 hover:underline">{customer.email}</a>
                        )}
                        {customer.phone && (
                          <div className="text-xs text-gray-500">{customer.phone}</div>
                        )}
                      </div>
                    </td>
                    <td className="text-gray-700">
                      {(customer.street_address || customer.city) ? (
                        <span>{customer.postal_code} {customer.city}</span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="text-gray-500 text-xs">
                      {customer.susoft_customer_id || '—'}
                    </td>
                    <td className="text-gray-700 text-xs">
                      {customer.order_lead_days}d
                    </td>
                    <td>
                      <span className={`badge ${customer.is_active ? 'badge-success' : 'badge-neutral'}`}>
                        {customer.is_active ? 'Aktiv' : 'Skjult'}
                      </span>
                    </td>
                    <td>
                      <div className="flex items-center justify-end gap-1">
                        <Link
                          to={`/maler/kunde/${customer.id}`}
                          className="badge badge-amber hover:bg-amber-200"
                          title="Fastbestilling (matrise)"
                        >
                          <ClipboardList className="w-3 h-3" /> Fastbestilling
                        </Link>
                        <button
                          onClick={() => setPlanCustomer(customer)}
                          className="badge bg-blue-100 text-blue-800 hover:bg-blue-200"
                          title="Periodeplan"
                        >
                          <CalendarClock className="w-3 h-3" /> Plan
                        </button>
                        <button
                          onClick={() => setOverrideCustomer(customer)}
                          className="badge bg-orange-100 text-orange-800 hover:bg-orange-200"
                          title="Registrer avvik"
                        >
                          <AlertTriangle className="w-3 h-3" /> Avvik
                        </button>
                        <button
                          onClick={() => setEditingCustomer(customer)}
                          className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded"
                          title="Rediger"
                        >
                          <Edit2 className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => toggleActive(customer)}
                          className={`p-1.5 rounded ${
                            customer.is_active
                              ? 'text-gray-400 hover:text-amber-700 hover:bg-amber-50'
                              : 'text-amber-600 hover:text-green-700 hover:bg-green-50'
                          }`}
                          title={customer.is_active ? 'Skjul kunde' : 'Vis kunde igjen'}
                        >
                          {customer.is_active ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              page={page}
              pageSize={pageSize}
              total={filteredCustomers.length}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
            />
          </div>
        )}
      </div>

      {(showNewModal || editingCustomer) && (
        <CustomerModal
          customer={editingCustomer}
          onClose={() => { setShowNewModal(false); setEditingCustomer(null); }}
          onSave={handleSaveCustomer}
        />
      )}

      {overrideCustomer && (
        <QuickOverrideModal
          customer={overrideCustomer}
          onClose={() => setOverrideCustomer(null)}
        />
      )}

      {planCustomer && (
        <PlanModal
          customer={planCustomer}
          onClose={() => setPlanCustomer(null)}
          onChanged={fetchCustomers}
        />
      )}
    </div>
  );
}

function CustomerModal({ customer, onClose, onSave }) {
  const [formData, setFormData] = useState({
    name: customer?.name || '',
    company_name: customer?.company_name || '',
    contact_person: customer?.contact_person || '',
    email: customer?.email || '',
    phone: customer?.phone || '',
    street_address: customer?.street_address || '',
    postal_code: customer?.postal_code || '',
    city: customer?.city || '',
    delivery_instructions: customer?.delivery_instructions || '',
    order_lead_days: customer?.order_lead_days || 14,
    is_active: customer?.is_active ?? true,
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!formData.name.trim()) { alert('Kundenavn er påkrevd'); return; }
    onSave(formData);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto m-4">
        <div className="p-6 border-b flex items-center justify-between">
          <h2 className="text-xl font-semibold">{customer ? 'Rediger kunde' : 'Ny kunde'}</h2>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded"><X className="w-5 h-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="label">Kundenavn *</label>
              <input type="text" value={formData.name} onChange={(e) => setFormData({...formData, name: e.target.value})} className="input" required />
            </div>
            <div>
              <label className="label">Kontaktperson</label>
              <input type="text" value={formData.contact_person} onChange={(e) => setFormData({...formData, contact_person: e.target.value})} className="input" />
            </div>
            <div>
              <label className="label">E-post</label>
              <input type="email" value={formData.email} onChange={(e) => setFormData({...formData, email: e.target.value})} className="input" />
            </div>
            <div>
              <label className="label">Telefon</label>
              <input type="tel" value={formData.phone} onChange={(e) => setFormData({...formData, phone: e.target.value})} className="input" />
            </div>
            <div>
              <label className="label">Sted</label>
              <input type="text" value={formData.city} onChange={(e) => setFormData({...formData, city: e.target.value})} className="input" />
            </div>
            <div className="col-span-2">
              <label className="label">Adresse</label>
              <input type="text" value={formData.street_address} onChange={(e) => setFormData({...formData, street_address: e.target.value})} className="input" />
            </div>
            <div>
              <label className="label">Postnummer</label>
              <input type="text" value={formData.postal_code} onChange={(e) => setFormData({...formData, postal_code: e.target.value})} className="input" />
            </div>
            <div>
              <label className="label">Ordreforskudd (dager)</label>
              <input type="number" value={formData.order_lead_days} onChange={(e) => setFormData({...formData, order_lead_days: parseInt(e.target.value) || 14})} className="input" min="7" max="84" />
              <p className="text-xs text-gray-500 mt-1">{(formData.order_lead_days / 7).toFixed(1)} uker fremover</p>
            </div>
          </div>
          <div className="flex justify-end gap-3 pt-4 border-t">
            <button type="button" onClick={onClose} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Avbryt</button>
            <button type="submit" className="btn-primary flex items-center gap-2"><Check className="w-4 h-4" />Lagre</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function PlanModal({ customer, onClose, onChanged }) {
  const { authFetch } = useAuth();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [leadDays, setLeadDays] = useState(customer.order_lead_days || 14);
  const [isActive, setIsActive] = useState(customer.is_active);
  const [genResult, setGenResult] = useState(null);
  const [error, setError] = useState(null);

  const loadStatus = async () => {
    setLoading(true);
    try {
      const res = await authFetch(`/api/v1/customers/${customer.id}/plan-status`);
      if (!res.ok) throw new Error('Kunne ikke hente planstatus');
      const data = await res.json();
      setStatus(data);
      setLeadDays(data.order_lead_days);
      setIsActive(data.is_active);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadStatus(); }, [customer.id]);

  const saveSettings = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await authFetch(`/api/v1/customers/${customer.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order_lead_days: leadDays, is_active: isActive }),
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Kunne ikke lagre');
      }
      await loadStatus();
      if (onChanged) onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const generateNow = async () => {
    setGenerating(true);
    setGenResult(null);
    setError(null);
    try {
      const res = await authFetch(
        `/api/v1/orders/generate-range?days=${leadDays}&customer_id=${customer.id}`,
        { method: 'POST' }
      );
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Generering feilet');
      }
      const data = await res.json();
      setGenResult(data);
      await loadStatus();
      if (onChanged) onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl max-w-xl w-full max-h-[90vh] overflow-y-auto m-4">
        <div className="p-5 border-b flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">Periodeplan</h2>
            <p className="text-sm text-gray-500">{customer.name}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded"><X className="w-5 h-5" /></button>
        </div>

        <div className="p-5 space-y-5">
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
          )}

          {loading ? (
            <div className="flex items-center gap-2 text-gray-500 py-6 justify-center">
              <RefreshCw className="w-4 h-4 animate-spin" /> Laster...
            </div>
          ) : (
            <>
              {/* Status */}
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="card-tight p-3">
                  <div className="text-xs text-gray-500">Aktiv mal</div>
                  <div className="font-medium text-gray-900 mt-0.5">
                    {status?.has_active_template ? (
                      <span className="text-green-700">{status.template_name || 'Standard'}</span>
                    ) : (
                      <span className="text-red-700">Ingen mal</span>
                    )}
                  </div>
                </div>
                <div className="card-tight p-3">
                  <div className="text-xs text-gray-500">Fremtidige ordrer</div>
                  <div className="font-medium text-gray-900 mt-0.5">{status?.future_orders_count ?? 0}</div>
                </div>
                <div className="card-tight p-3">
                  <div className="text-xs text-gray-500">Sist generert til</div>
                  <div className="font-medium text-gray-900 mt-0.5">{status?.last_generated_date || '—'}</div>
                </div>
                <div className="card-tight p-3">
                  <div className="text-xs text-gray-500">Status</div>
                  <div className="mt-0.5">
                    <span className={`badge ${status?.is_active ? 'badge-success' : 'badge-neutral'}`}>
                      {status?.is_active ? 'Aktiv – genererer ordrer' : 'Pauset'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Innstillinger */}
              <div className="space-y-3 pt-2 border-t">
                <div>
                  <label className="label">Generer ordrer fremover</label>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min="7"
                      max="84"
                      step="7"
                      value={leadDays}
                      onChange={(e) => setLeadDays(parseInt(e.target.value))}
                      className="flex-1"
                    />
                    <div className="text-sm font-medium text-gray-900 w-28 text-right">
                      {(leadDays / 7).toFixed(0)} uker ({leadDays}d)
                    </div>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">
                    Daglig jobb fyller på horisonten automatisk så du alltid har {(leadDays/7).toFixed(0)} uker fremover.
                  </p>
                </div>

                <div className="flex items-center justify-between p-3 bg-gray-50 rounded-md">
                  <div>
                    <div className="text-sm font-medium text-gray-900">Periodeplan aktiv</div>
                    <div className="text-xs text-gray-500">Når av: ingen nye ordrer genereres</div>
                  </div>
                  <button
                    onClick={() => setIsActive(!isActive)}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${isActive ? 'bg-green-600' : 'bg-gray-300'}`}
                  >
                    <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${isActive ? 'translate-x-6' : 'translate-x-1'}`} />
                  </button>
                </div>
              </div>

              {/* Generer-resultat */}
              {genResult && (
                <div className="p-3 bg-green-50 border border-green-200 rounded text-sm text-green-800">
                  <div className="font-medium">
                    {genResult.created_count} nye ordrer opprettet ({genResult.from_date} → {genResult.to_date})
                  </div>
                  {genResult.skipped_count > 0 && (
                    <div className="text-xs mt-1">{genResult.skipped_count} datoer hoppet over (allerede ordre / blokkert dato).</div>
                  )}
                </div>
              )}

              {/* Knapper */}
              <div className="flex justify-between gap-3 pt-4 border-t">
                <button
                  onClick={generateNow}
                  disabled={generating || !status?.has_active_template || !isActive}
                  className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />}
                  Generer nå
                </button>
                <div className="flex gap-2">
                  <button onClick={onClose} className="btn-secondary">Lukk</button>
                  <button
                    onClick={saveSettings}
                    disabled={saving}
                    className="btn-primary disabled:opacity-50"
                  >
                    {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                    Lagre
                  </button>
                </div>
              </div>

              {!status?.has_active_template && (
                <div className="p-3 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800">
                  Ingen aktiv mal. Klikk «Fastbestilling» på kunden for å lage en mal først.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
