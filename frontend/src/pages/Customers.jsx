import { useState, useEffect, useMemo, Fragment } from 'react';
import { Search, Plus, Building2, Phone, Mail, MapPin, RefreshCw, Edit2, X, Check, ClipboardList, AlertTriangle, CalendarClock, PlayCircle, PauseCircle, Eye, EyeOff, Store, UserPlus, Star, Trash2, ChevronRight, ChevronDown, Repeat, CalendarCheck, Globe } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import QuickOverrideModal from '../components/QuickOverrideModal';
import Pagination from '../components/Pagination';
import SearchInput from '../components/SearchInput';

export default function Customers() {
  const { authFetch } = useAuth();
  const [customers, setCustomers] = useState([]);
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('active');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showNewModal, setShowNewModal] = useState(false);
  const [editingCustomer, setEditingCustomer] = useState(null);
  const [overrideCustomer, setOverrideCustomer] = useState(null);
  const [planCustomer, setPlanCustomer] = useState(null);
  const [portalCustomer, setPortalCustomer] = useState(null);
  const [favoritesCustomer, setFavoritesCustomer] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [expandedId, setExpandedId] = useState(null);

  const toggleExpanded = (id) => setExpandedId((prev) => (prev === id ? null : id));

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
    const q = (appliedSearch || '').toLowerCase();
    const matchesSearch =
      !q ||
      c.name?.toLowerCase().includes(q) ||
      c.contact_person?.toLowerCase().includes(q) ||
      c.city?.toLowerCase().includes(q);

    const matchesStatus =
      statusFilter === 'all' ||
      (statusFilter === 'active' && c.is_active) ||
      (statusFilter === 'inactive' && !c.is_active);

    return matchesSearch && matchesStatus;
  });

  // Reset page when filter/search changes
  useEffect(() => { setPage(1); setSelectedIds(new Set()); }, [appliedSearch, statusFilter, pageSize]);

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

  const toggleSelected = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const bulkSetActive = async (isActive) => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    const verb = isActive ? 'vise' : 'skjule';
    if (!confirm(`Vil du ${verb} ${ids.length} valgte ${ids.length === 1 ? 'kunde' : 'kunder'}?`)) return;
    try {
      const response = await authFetch('/api/v1/customers/bulk/set-active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids, is_active: isActive })
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke oppdatere');
      }
      setCustomers((prev) => prev.map(c => ids.includes(c.id) ? { ...c, is_active: isActive } : c));
      setSelectedIds(new Set());
    } catch (err) {
      alert(err.message);
    }
  };

  if (loading && customers.length === 0) {
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
            <SearchInput
              value={search}
              onChange={setSearch}
              onSearch={setAppliedSearch}
              placeholder="Sok kunde (min. 3 tegn, Enter for aa tvinge)"
              minChars={3}
              ariaLabel="Sok kunder"
            />
          </div>
        </div>

        {filteredCustomers.length === 0 ? (
          <div className="text-center py-12 text-gray-500 text-sm">
            {customers.length === 0 ? 'Ingen kunder funnet. Synkroniser med SuSoft i Innstillinger.' : 'Ingen kunder matcher søket'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            {selectedIds.size > 0 && (
              <div className="px-3 py-2 border-b border-amber-200 bg-amber-50 flex items-center gap-2 text-sm flex-wrap">
                <span className="font-medium text-amber-900">{selectedIds.size} valgt</span>
                <button onClick={() => bulkSetActive(false)} className="btn-secondary !py-1 !text-xs">
                  <EyeOff className="w-3.5 h-3.5" /> Skjul valgte
                </button>
                <button onClick={() => bulkSetActive(true)} className="btn-secondary !py-1 !text-xs">
                  <Eye className="w-3.5 h-3.5" /> Vis valgte
                </button>
                <button onClick={() => setSelectedIds(new Set())} className="text-xs text-gray-600 hover:text-gray-900 ml-auto">
                  Fjern utvalg
                </button>
              </div>
            )}
            <div className="px-3 py-2 text-xs text-gray-500 flex items-center gap-3 flex-wrap border-b">
              <span className="font-medium text-gray-600">Symboler:</span>
              <span className="inline-flex items-center gap-1">
                <span className="inline-flex items-center justify-center w-4 h-4 rounded bg-green-100 text-green-700">
                  <Repeat className="w-2.5 h-2.5" />
                </span>
                Fastbestilling (mal)
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="inline-flex items-center justify-center w-4 h-4 rounded bg-blue-100 text-blue-700">
                  <CalendarCheck className="w-2.5 h-2.5" />
                </span>
                Periodeplan kjører
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="inline-flex items-center justify-center w-4 h-4 rounded bg-purple-100 text-purple-700">
                  <Globe className="w-2.5 h-2.5" />
                </span>
                Portal-tilgang
              </span>
            </div>
            <table className="shop-table">
              <thead>
                <tr>
                  <th className="w-8">
                    <input
                      type="checkbox"
                      checked={pagedCustomers.length > 0 && pagedCustomers.every(c => selectedIds.has(c.id))}
                      onChange={(e) => {
                        const next = new Set(selectedIds);
                        if (e.target.checked) pagedCustomers.forEach(c => next.add(c.id));
                        else pagedCustomers.forEach(c => next.delete(c.id));
                        setSelectedIds(next);
                      }}
                      title="Velg alle paa siden"
                    />
                  </th>
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
                {pagedCustomers.map((customer) => {
                  const isExpanded = expandedId === customer.id;
                  return (
                  <Fragment key={customer.id}>
                  <tr
                    className={`${selectedIds.has(customer.id) ? 'bg-amber-50/50' : ''} ${isExpanded ? 'bg-amber-50/30' : ''} cursor-pointer hover:bg-gray-50`}
                    onClick={() => toggleExpanded(customer.id)}
                  >
                    <td onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(customer.id)}
                        onChange={() => toggleSelected(customer.id)}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </td>
                    <td>
                      <div className="flex items-center gap-2.5">
                        {isExpanded ? (
                          <ChevronDown className="w-4 h-4 text-gray-400" />
                        ) : (
                          <ChevronRight className="w-4 h-4 text-gray-400" />
                        )}
                        <div className="w-7 h-7 bg-amber-100 rounded flex items-center justify-center flex-shrink-0">
                          <Building2 className="w-4 h-4 text-amber-600" />
                        </div>
                        <span className="font-medium text-gray-900">{customer.name}</span>
                        <div className="flex items-center gap-1 ml-1">
                          {customer.has_active_template ? (
                            <span title="Fastbestilling (mal aktiv)" className="inline-flex items-center justify-center w-5 h-5 rounded bg-green-100 text-green-700">
                              <Repeat className="w-3 h-3" />
                            </span>
                          ) : (
                            <span title="Ingen fastbestilling" className="inline-flex items-center justify-center w-5 h-5 rounded bg-gray-100 text-gray-300">
                              <Repeat className="w-3 h-3" />
                            </span>
                          )}
                          {customer.has_future_orders ? (
                            <span title="Periodeplan kjører (har fremtidige ordrer)" className="inline-flex items-center justify-center w-5 h-5 rounded bg-blue-100 text-blue-700">
                              <CalendarCheck className="w-3 h-3" />
                            </span>
                          ) : (
                            <span title="Ingen plan / ingen fremtidige ordrer" className="inline-flex items-center justify-center w-5 h-5 rounded bg-gray-100 text-gray-300">
                              <CalendarCheck className="w-3 h-3" />
                            </span>
                          )}
                          {customer.has_portal_user ? (
                            <span title="Har portal-tilgang (kunden bestiller selv)" className="inline-flex items-center justify-center w-5 h-5 rounded bg-purple-100 text-purple-700">
                              <Globe className="w-3 h-3" />
                            </span>
                          ) : (
                            <span title="Ingen portal-bruker" className="inline-flex items-center justify-center w-5 h-5 rounded bg-gray-100 text-gray-300">
                              <Globe className="w-3 h-3" />
                            </span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="text-gray-700">
                        {customer.contact_person && <div>{customer.contact_person}</div>}
                        {customer.email && (
                          <a href={`mailto:${customer.email}`} className="text-xs text-amber-700 hover:underline" onClick={(e) => e.stopPropagation()}>{customer.email}</a>
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
                    <td onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
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
                  {isExpanded && (
                    <tr className="bg-amber-50/20">
                      <td></td>
                      <td colSpan={7} className="py-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs uppercase tracking-wider text-gray-500 mr-2">Sett opp:</span>
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
                            onClick={() => setPortalCustomer(customer)}
                            className="badge bg-emerald-100 text-emerald-800 hover:bg-emerald-200"
                            title="Utsalg & portal-tilgang"
                          >
                            <Store className="w-3 h-3" /> Portal
                          </button>
                          <button
                            onClick={() => setFavoritesCustomer(customer)}
                            className="badge bg-amber-100 text-amber-800 hover:bg-amber-200"
                            title="Favorittliste for portalen"
                          >
                            <Star className="w-3 h-3" /> Favoritter
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                  </Fragment>
                  );
                })}
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

      {portalCustomer && (
        <PortalAccessModal
          customer={portalCustomer}
          onClose={() => setPortalCustomer(null)}
          authFetch={authFetch}
        />
      )}

      {favoritesCustomer && (
        <FavoritesModal
          customer={favoritesCustomer}
          onClose={() => setFavoritesCustomer(null)}
          onCustomerUpdated={fetchCustomers}
          authFetch={authFetch}
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
    restrict_to_favorites: customer?.restrict_to_favorites ?? false,
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
            <div className="col-span-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={formData.restrict_to_favorites}
                  onChange={(e) => setFormData({ ...formData, restrict_to_favorites: e.target.checked })}
                  className="rounded border-gray-300"
                />
                <span>Begrens til favorittliste</span>
              </label>
              <p className="text-xs text-gray-500 mt-1 ml-6">
                Kunden kan kun bestille produkter fra favorittlisten i portalen.
              </p>
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

function PortalAccessModal({ customer, onClose, authFetch }) {
  const [outlets, setOutlets] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('outlets');

  // outlet form
  const [newOutlet, setNewOutlet] = useState({ name: '', street_address: '', postal_code: '', city: '', contact_person: '', phone: '' });
  // user form
  const [newUser, setNewUser] = useState({ email: '', first_name: '', last_name: '', phone: '', initial_password: '' });
  const [targetCustomerId, setTargetCustomerId] = useState(customer.id);
  // Vist passord etter oppretting / nullstilling (vises én gang)
  const [revealedPassword, setRevealedPassword] = useState(null); // { email, password }

  const reload = async () => {
    setLoading(true);
    try {
      const [oRes, uRes] = await Promise.all([
        authFetch(`/api/v1/customers/${customer.id}/outlets`),
        authFetch(`/api/v1/customers/${customer.id}/portal-users`),
      ]);
      const oData = oRes.ok ? await oRes.json() : [];
      const uData = uRes.ok ? await uRes.json() : [];
      setOutlets(oData);
      setUsers(uData);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [customer.id]);

  const handleAddOutlet = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      const res = await authFetch(`/api/v1/customers/${customer.id}/outlets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newOutlet),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || 'Klarte ikke opprette utsalg');
      }
      setNewOutlet({ name: '', street_address: '', postal_code: '', city: '', contact_person: '', phone: '' });
      reload();
    } catch (e) { setError(e.message); }
  };

  const handleAddUser = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      const res = await authFetch(`/api/v1/customers/${targetCustomerId}/portal-users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newUser),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || 'Klarte ikke opprette portal-bruker');
      }
      setRevealedPassword({ email: newUser.email, password: newUser.initial_password });
      setNewUser({ email: '', first_name: '', last_name: '', phone: '', initial_password: '' });
      reload();
    } catch (e) { setError(e.message); }
  };

  const handleResetPassword = async (user, customerIdForUser) => {
    if (!confirm(`Nullstille passord for ${user.email}? Brukeren må få det nye passordet av deg.`)) return;
    setError(null);
    try {
      const res = await authFetch(`/api/v1/customers/${customerIdForUser}/portal-users/${user.id}/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),  // generer tilfeldig
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || 'Klarte ikke nullstille passord');
      }
      const data = await res.json();
      setRevealedPassword({ email: data.email, password: data.new_password });
    } catch (e) { setError(e.message); }
  };

  const allCustomers = [{ id: customer.id, name: `${customer.name} (hovedkunde)` }, ...outlets.map(o => ({ id: o.id, name: o.name }))];

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Store className="w-5 h-5 text-emerald-600" />
            Utsalg & portal-tilgang — {customer.name}
          </h2>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="border-b flex">
          <button
            className={`px-4 py-2 text-sm font-medium ${tab === 'outlets' ? 'border-b-2 border-emerald-600 text-emerald-700' : 'text-gray-600'}`}
            onClick={() => setTab('outlets')}
          >Utsalg ({outlets.length})</button>
          <button
            className={`px-4 py-2 text-sm font-medium ${tab === 'users' ? 'border-b-2 border-emerald-600 text-emerald-700' : 'text-gray-600'}`}
            onClick={() => setTab('users')}
          >Portal-brukere ({users.length})</button>
        </div>

        {error && (
          <div className="m-4 bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm">{error}</div>
        )}

        {loading ? (
          <div className="p-6 text-gray-600">Laster…</div>
        ) : tab === 'outlets' ? (
          <div className="p-4 space-y-4">
            <div className="text-sm text-gray-600">
              Utsalg er undergrupper av denne kunden. Ordrer kan registreres pr. utsalg, og hovedkundens portal-bruker ser alle utsalgene sine.
            </div>

            {outlets.length > 0 && (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs uppercase text-gray-600 text-left">
                  <tr>
                    <th className="px-3 py-2">Navn</th>
                    <th className="px-3 py-2">Adresse</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Portal</th>
                  </tr>
                </thead>
                <tbody>
                  {outlets.map(o => (
                    <tr key={o.id} className="border-t">
                      <td className="px-3 py-2 font-medium">{o.name}</td>
                      <td className="px-3 py-2 text-gray-700">
                        {o.street_address || '—'}{o.city ? `, ${o.postal_code || ''} ${o.city}` : ''}
                      </td>
                      <td className="px-3 py-2">
                        <span className={`badge ${o.is_active ? 'badge-success' : 'badge-neutral'}`}>
                          {o.is_active ? 'Aktiv' : 'Skjult'}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        {o.has_portal_user ? (
                          <span className="text-xs text-emerald-700">✓ Egen bruker</span>
                        ) : (
                          <span className="text-xs text-gray-500">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <form onSubmit={handleAddOutlet} className="border-t pt-4 space-y-3">
              <div className="font-medium text-sm">Nytt utsalg</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <input
                  required
                  type="text"
                  placeholder="Navn på utsalg *"
                  value={newOutlet.name}
                  onChange={e => setNewOutlet(s => ({ ...s, name: e.target.value }))}
                  className="border border-gray-300 rounded px-3 py-2 text-sm"
                />
                <input
                  type="text"
                  placeholder="Kontaktperson"
                  value={newOutlet.contact_person}
                  onChange={e => setNewOutlet(s => ({ ...s, contact_person: e.target.value }))}
                  className="border border-gray-300 rounded px-3 py-2 text-sm"
                />
                <input
                  type="text"
                  placeholder="Adresse"
                  value={newOutlet.street_address}
                  onChange={e => setNewOutlet(s => ({ ...s, street_address: e.target.value }))}
                  className="border border-gray-300 rounded px-3 py-2 text-sm"
                />
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="Postnr"
                    value={newOutlet.postal_code}
                    onChange={e => setNewOutlet(s => ({ ...s, postal_code: e.target.value }))}
                    className="border border-gray-300 rounded px-3 py-2 text-sm w-24"
                  />
                  <input
                    type="text"
                    placeholder="Sted"
                    value={newOutlet.city}
                    onChange={e => setNewOutlet(s => ({ ...s, city: e.target.value }))}
                    className="border border-gray-300 rounded px-3 py-2 text-sm flex-1"
                  />
                </div>
                <input
                  type="text"
                  placeholder="Telefon"
                  value={newOutlet.phone}
                  onChange={e => setNewOutlet(s => ({ ...s, phone: e.target.value }))}
                  className="border border-gray-300 rounded px-3 py-2 text-sm"
                />
              </div>
              <button type="submit" className="btn-primary inline-flex items-center gap-2">
                <Plus className="w-4 h-4" /> Opprett utsalg
              </button>
            </form>
          </div>
        ) : (
          <div className="p-4 space-y-4">
            <div className="text-sm text-gray-600">
              Portal-brukere kan logge inn på bestillingsportalen og legge inn / se egne ordrer.
              Hvis brukeren knyttes til hovedkunden ser de alle utsalgene sine; knyttes de til ett utsalg ser de kun det.
            </div>

            {revealedPassword && (
              <div className="border border-amber-300 bg-amber-50 rounded p-3 text-sm space-y-2">
                <div className="font-medium text-amber-900">
                  Passord for <span className="font-mono">{revealedPassword.email}</span>
                </div>
                <div className="font-mono bg-white border border-amber-200 rounded px-3 py-2 select-all text-base">
                  {revealedPassword.password}
                </div>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => navigator.clipboard?.writeText(revealedPassword.password)}
                    className="text-xs text-amber-800 underline"
                  >Kopier til utklippstavle</button>
                  <button
                    type="button"
                    onClick={() => setRevealedPassword(null)}
                    className="text-xs text-amber-800 underline ml-auto"
                  >Lukk</button>
                </div>
                <div className="text-xs text-amber-800">
                  Vises kun denne ene gangen — kopier og send til kunden via SMS / sikker kanal.
                </div>
              </div>
            )}

            {users.length > 0 && (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs uppercase text-gray-600 text-left">
                  <tr>
                    <th className="px-3 py-2">E-post</th>
                    <th className="px-3 py-2">Navn</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {users.map(u => (
                    <tr key={u.id} className="border-t">
                      <td className="px-3 py-2 font-mono text-xs">{u.email}</td>
                      <td className="px-3 py-2">{u.first_name} {u.last_name}</td>
                      <td className="px-3 py-2">
                        <span className={`badge ${u.is_active ? 'badge-success' : 'badge-neutral'}`}>
                          {u.is_active ? 'Aktiv' : 'Inaktiv'}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          type="button"
                          onClick={() => handleResetPassword(u, u.customer_id)}
                          className="text-xs text-amber-700 hover:text-amber-800 underline"
                        >
                          Nullstill passord
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <form onSubmit={handleAddUser} className="border-t pt-4 space-y-3">
              <div className="font-medium text-sm flex items-center gap-2">
                <UserPlus className="w-4 h-4" /> Ny portal-bruker
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <select
                  value={targetCustomerId}
                  onChange={e => setTargetCustomerId(Number(e.target.value))}
                  className="border border-gray-300 rounded px-3 py-2 text-sm sm:col-span-2"
                >
                  {allCustomers.map(c => (
                    <option key={c.id} value={c.id}>Tilknytt: {c.name}</option>
                  ))}
                </select>
                <input
                  required type="email"
                  placeholder="E-post *"
                  value={newUser.email}
                  onChange={e => setNewUser(s => ({ ...s, email: e.target.value }))}
                  className="border border-gray-300 rounded px-3 py-2 text-sm"
                />
                <input
                  type="text" placeholder="Telefon"
                  value={newUser.phone}
                  onChange={e => setNewUser(s => ({ ...s, phone: e.target.value }))}
                  className="border border-gray-300 rounded px-3 py-2 text-sm"
                />
                <input
                  required type="text" placeholder="Fornavn *"
                  value={newUser.first_name}
                  onChange={e => setNewUser(s => ({ ...s, first_name: e.target.value }))}
                  className="border border-gray-300 rounded px-3 py-2 text-sm"
                />
                <input
                  required type="text" placeholder="Etternavn *"
                  value={newUser.last_name}
                  onChange={e => setNewUser(s => ({ ...s, last_name: e.target.value }))}
                  className="border border-gray-300 rounded px-3 py-2 text-sm"
                />
                <input
                  required type="text" minLength={8}
                  placeholder="Foreløpig passord (min 8 tegn) *"
                  value={newUser.initial_password}
                  onChange={e => setNewUser(s => ({ ...s, initial_password: e.target.value }))}
                  className="border border-gray-300 rounded px-3 py-2 text-sm sm:col-span-2"
                />
              </div>
              <div className="text-xs text-gray-500">
                Tips: Bruk et sterkt passord og gi det til kunden via en sikker kanal. Be dem bytte ved første innlogging.
              </div>
              <button type="submit" className="btn-primary inline-flex items-center gap-2">
                <Check className="w-4 h-4" /> Opprett bruker
              </button>
            </form>
          </div>
        )}
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

function FavoritesModal({ customer, onClose, onCustomerUpdated, authFetch }) {
  const isSubOutlet = !!customer.parent_customer_id;
  const targetCustomerId = customer.parent_customer_id || customer.id;
  const [favorites, setFavorites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [restrict, setRestrict] = useState(!!customer.restrict_to_favorites);
  const [savingRestrict, setSavingRestrict] = useState(false);
  const [search, setSearch] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [editPrice, setEditPrice] = useState({}); // favorite_id -> string

  const loadFavorites = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch(`/api/v1/customers/${targetCustomerId}/favorites`);
      if (!res.ok) throw new Error('Kunne ikke laste favoritter');
      const data = await res.json();
      setFavorites(data || []);
      const prices = {};
      (data || []).forEach(f => {
        prices[f.id] = f.custom_price != null ? String(f.custom_price) : '';
      });
      setEditPrice(prices);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadFavorites(); /* eslint-disable-next-line */ }, [targetCustomerId]);

  // Søk produkter med debounce
  useEffect(() => {
    if (isSubOutlet) return;
    if (!search.trim()) { setSearchResults([]); return; }
    const t = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await authFetch(`/api/v1/products?search=${encodeURIComponent(search)}&page_size=20&is_active=true`);
        if (res.ok) {
          const data = await res.json();
          const favIds = new Set(favorites.map(f => f.product_id));
          setSearchResults((data.items || []).filter(p => !favIds.has(p.id)));
        }
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [search, favorites, isSubOutlet, authFetch]);

  const toggleRestrict = async (checked) => {
    setSavingRestrict(true);
    try {
      const res = await authFetch(`/api/v1/customers/${customer.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ restrict_to_favorites: checked }),
      });
      if (!res.ok) throw new Error('Kunne ikke oppdatere kunde');
      setRestrict(checked);
      onCustomerUpdated && onCustomerUpdated();
    } catch (err) {
      alert(err.message);
    } finally {
      setSavingRestrict(false);
    }
  };

  const addFavorite = async (product, customPriceStr) => {
    const body = { product_id: product.id };
    const trimmed = (customPriceStr || '').trim();
    if (trimmed) {
      const v = parseFloat(trimmed.replace(',', '.'));
      if (!isNaN(v) && v >= 0) body.custom_price = v;
    }
    try {
      const res = await authFetch(`/api/v1/customers/${targetCustomerId}/favorites`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke legge til favoritt');
      }
      setSearch('');
      setSearchResults([]);
      await loadFavorites();
    } catch (err) {
      alert(err.message);
    }
  };

  const savePrice = async (fav) => {
    const raw = (editPrice[fav.id] || '').trim();
    const body = {};
    if (raw === '') {
      body.clear_custom_price = true;
    } else {
      const v = parseFloat(raw.replace(',', '.'));
      if (isNaN(v) || v < 0) { alert('Ugyldig pris'); return; }
      body.custom_price = v;
    }
    try {
      const res = await authFetch(`/api/v1/customers/${targetCustomerId}/favorites/${fav.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Kunne ikke lagre pris');
      }
      await loadFavorites();
    } catch (err) {
      alert(err.message);
    }
  };

  const removeFavorite = async (fav) => {
    if (!confirm(`Fjerne "${fav.name}" fra favorittlisten?`)) return;
    try {
      const res = await authFetch(`/api/v1/customers/${targetCustomerId}/favorites/${fav.id}`, {
        method: 'DELETE',
      });
      if (!res.ok && res.status !== 204) throw new Error('Kunne ikke slette favoritt');
      await loadFavorites();
    } catch (err) {
      alert(err.message);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto m-4">
        <div className="p-6 border-b flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold flex items-center gap-2">
              <Star className="w-5 h-5 text-amber-500" />
              Favorittliste — {customer.name}
            </h2>
            {isSubOutlet && (
              <p className="text-xs text-amber-700 mt-1">
                Dette er et underutsalg. Favorittlisten administreres på hovedkunden og arves automatisk.
              </p>
            )}
          </div>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded"><X className="w-5 h-5" /></button>
        </div>

        <div className="p-6 space-y-6">
          {/* Restrict toggle (kun på hovedkunde) */}
          {!isSubOutlet && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={restrict}
                  disabled={savingRestrict}
                  onChange={(e) => toggleRestrict(e.target.checked)}
                  className="mt-0.5 rounded border-gray-300"
                />
                <div>
                  <div className="font-medium text-amber-900">Begrens til favorittliste</div>
                  <div className="text-xs text-amber-800 mt-0.5">
                    Hvis aktivert kan kunden kun bestille produkter fra favorittlisten i portalen.
                  </div>
                </div>
              </label>
            </div>
          )}

          {/* Legg til (kun på hovedkunde) */}
          {!isSubOutlet && (
            <div>
              <label className="label">Legg til produkt</label>
              <div className="relative">
                <Search className="w-4 h-4 absolute left-3 top-3 text-gray-400" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Søk produktnavn eller SKU…"
                  className="input pl-10"
                />
              </div>
              {searching && <div className="text-xs text-gray-500 mt-1">Søker…</div>}
              {searchResults.length > 0 && (
                <div className="mt-2 border border-gray-200 rounded-lg divide-y max-h-64 overflow-y-auto">
                  {searchResults.map(p => (
                    <SearchResultRow key={p.id} product={p} onAdd={addFavorite} />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Liste */}
          <div>
            <h3 className="font-medium text-gray-900 mb-2">
              Favoritter ({favorites.length})
            </h3>
            {loading && <div className="text-sm text-gray-500">Laster…</div>}
            {error && <div className="text-sm text-red-600">{error}</div>}
            {!loading && !error && favorites.length === 0 && (
              <div className="text-sm text-gray-500 italic">Ingen favoritter lagt til ennå.</div>
            )}
            {!loading && favorites.length > 0 && (
              <div className="border border-gray-200 rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
                    <tr>
                      <th className="text-left px-3 py-2">Produkt</th>
                      <th className="text-right px-3 py-2 w-28">Standardpris</th>
                      <th className="text-right px-3 py-2 w-40">Spesialpris (NOK)</th>
                      {!isSubOutlet && <th className="px-3 py-2 w-32"></th>}
                    </tr>
                  </thead>
                  <tbody>
                    {favorites.map(fav => (
                      <tr key={fav.id} className="border-t border-gray-100">
                        <td className="px-3 py-2">
                          <div className="font-medium">{fav.name}</div>
                          {fav.sku && <div className="text-xs text-gray-500">{fav.sku} · {fav.unit}</div>}
                        </td>
                        <td className="px-3 py-2 text-right text-gray-600">
                          {fav.default_price != null ? Number(fav.default_price).toFixed(2) : '—'}
                        </td>
                        <td className="px-3 py-2 text-right">
                          {isSubOutlet ? (
                            <span className="text-gray-700">
                              {fav.custom_price != null ? Number(fav.custom_price).toFixed(2) : '—'}
                            </span>
                          ) : (
                            <input
                              type="number"
                              step="0.01"
                              min="0"
                              value={editPrice[fav.id] ?? ''}
                              onChange={(e) => setEditPrice({ ...editPrice, [fav.id]: e.target.value })}
                              placeholder="(standard)"
                              className="input text-right py-1"
                            />
                          )}
                        </td>
                        {!isSubOutlet && (
                          <td className="px-3 py-2">
                            <div className="flex items-center justify-end gap-1">
                              <button
                                onClick={() => savePrice(fav)}
                                className="p-1.5 text-emerald-700 hover:bg-emerald-50 rounded"
                                title="Lagre pris"
                              >
                                <Check className="w-4 h-4" />
                              </button>
                              <button
                                onClick={() => removeFavorite(fav)}
                                className="p-1.5 text-red-600 hover:bg-red-50 rounded"
                                title="Fjern fra favoritter"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        <div className="p-4 border-t flex justify-end">
          <button onClick={onClose} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg">
            Lukk
          </button>
        </div>
      </div>
    </div>
  );
}

function SearchResultRow({ product, onAdd }) {
  const [price, setPrice] = useState('');
  return (
    <div className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50">
      <div className="flex-1 min-w-0">
        <div className="font-medium text-sm truncate">{product.name}</div>
        <div className="text-xs text-gray-500">
          {product.sku} · standard {product.default_price != null ? Number(product.default_price).toFixed(2) : '—'}
        </div>
      </div>
      <input
        type="number"
        step="0.01"
        min="0"
        value={price}
        onChange={(e) => setPrice(e.target.value)}
        placeholder="Spesialpris"
        className="input py-1 w-32 text-right text-sm"
      />
      <button
        onClick={() => onAdd(product, price)}
        className="px-3 py-1.5 bg-amber-600 text-white text-sm rounded hover:bg-amber-700 flex items-center gap-1"
      >
        <Plus className="w-3.5 h-3.5" /> Legg til
      </button>
    </div>
  );
}


