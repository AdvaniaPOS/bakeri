import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Calendar, Plus, Copy, Edit2, Trash2, RefreshCw, X, Check } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

const weekdays = ['Mandag', 'Tirsdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lørdag', 'Søndag'];

export default function Templates() {
  const { authFetch } = useAuth();
  const navigate = useNavigate();
  const [templates, setTemplates] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showNewModal, setShowNewModal] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [templatesRes, customersRes, productsRes] = await Promise.all([
        authFetch('/api/v1/templates'),
        authFetch('/api/v1/customers?page_size=1000'),
        authFetch('/api/v1/products?page_size=1000')
      ]);
      
      if (!templatesRes.ok || !customersRes.ok || !productsRes.ok) {
        throw new Error('Kunne ikke hente data');
      }

      const templatesData = await templatesRes.json();
      const customersData = await customersRes.json();
      const productsData = await productsRes.json();

      setTemplates(templatesData);
      setCustomers(customersData.items || []);
      setProducts(productsData.items || []);
      setError(null);
    } catch (err) {
      console.error('Fetch error:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // Helper to get customer name
  const getCustomerName = (customerId) => {
    const customer = customers.find(c => c.id === customerId);
    return customer?.name || `Kunde #${customerId}`;
  };

  // Helper to get product name
  const getProductName = (productId) => {
    const product = products.find(p => p.id === productId);
    return product?.name || `Produkt #${productId}`;
  };

  // Transform API items to day-based structure
  const getDayItems = (template) => {
    const days = {};
    for (const item of template.items || []) {
      const dayIndex = item.day_of_week - 1; // API uses 1-7, we use 0-6
      if (!days[dayIndex]) days[dayIndex] = [];
      days[dayIndex].push({
        product: getProductName(item.product_id),
        qty: item.quantity,
        productId: item.product_id
      });
    }
    return days;
  };

  const handleDeleteTemplate = async (templateId) => {
    if (!confirm('Er du sikker på at du vil slette denne malen?')) return;
    
    try {
      const response = await authFetch(`/api/v1/templates/${templateId}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('Kunne ikke slette mal');
      fetchData();
    } catch (err) {
      alert(err.message);
    }
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <RefreshCw className="w-6 h-6 animate-spin text-amber-600" />
        <span className="ml-2 text-gray-500">Laster maler...</span>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Bestillingsmaler</h1>
          <p className="page-subtitle">Ukentlige bestillingsmaler for faste kunder</p>
        </div>
        <div className="flex gap-2">
          <button onClick={fetchData} className="btn-secondary" title="Oppdater">
            <RefreshCw className="w-4 h-4" /> Oppdater
          </button>
          <button onClick={() => setShowNewModal(true)} className="btn-primary">
            <Plus className="w-4 h-4" /> Ny mal
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">{error}</div>
      )}

      {templates.length === 0 ? (
        <div className="card text-center py-16 text-gray-500">
          <Calendar className="w-10 h-10 mx-auto mb-3 text-gray-300" />
          <p className="text-base font-medium text-gray-700">Ingen bestillingsmaler funnet</p>
          <p className="text-sm mt-1">Opprett en ny mal for å sette opp faste ukentlige bestillinger.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {templates.map((template) => {
            const days = getDayItems(template);
            return (
              <div key={template.id} className="card">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h2 className="text-base font-semibold text-gray-900">{getCustomerName(template.customer_id)}</h2>
                    <p className="text-xs text-gray-500">{template.name}</p>
                    {template.updated_at && (
                      <p className="text-xs text-gray-400 mt-0.5">
                        Sist oppdatert: {new Date(template.updated_at).toLocaleDateString('nb-NO')}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`badge ${template.is_active ? 'badge-success' : 'badge-neutral'}`}>
                      {template.is_active ? 'Aktiv' : 'Inaktiv'}
                    </span>
                    <button onClick={() => navigate(`/maler/kunde/${template.customer_id}`)} className="p-1.5 text-gray-400 hover:text-amber-700 hover:bg-amber-50 rounded" title="Rediger matrise">
                      <Edit2 className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => handleDeleteTemplate(template.id)} className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded" title="Slett">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Week grid */}
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-2">
                  {weekdays.map((day, index) => {
                    const dayItems = days[index] || [];
                    const hasItems = dayItems.length > 0;
                    return (
                      <div
                        key={day}
                        className={`rounded-md p-2.5 min-h-[110px] border ${
                          hasItems ? 'bg-amber-50 border-amber-200' : 'bg-gray-50 border-gray-200'
                        }`}
                      >
                        <div className="flex items-center gap-1 mb-1.5">
                          <span className={`text-xs font-semibold uppercase tracking-wider ${hasItems ? 'text-amber-800' : 'text-gray-500'}`}>
                            {day.slice(0, 3)}
                          </span>
                        </div>
                        {hasItems ? (
                          <div className="space-y-0.5">
                            {dayItems.map((item, i) => (
                              <div key={i} className="text-xs text-gray-700">
                                <span className="font-medium">{item.qty}×</span> <span>{item.product}</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-xs text-gray-400 italic">—</p>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {(showNewModal || editingTemplate) && (
        <TemplateModal
          template={editingTemplate}
          customers={customers}
          products={products}
          onClose={() => { setShowNewModal(false); setEditingTemplate(null); }}
          onSave={() => { setShowNewModal(false); setEditingTemplate(null); fetchData(); }}
        />
      )}
    </div>
  );
}

function TemplateModal({ template, customers, products, onClose, onSave }) {
  const { authFetch } = useAuth();
  const [customerId, setCustomerId] = useState(template?.customer_id || '');
  const [name, setName] = useState(template?.name || 'Standard Ukentlig Ordre');
  const [items, setItems] = useState(template?.items || []);
  const [saving, setSaving] = useState(false);

  const handleAddItem = () => {
    setItems([...items, { product_id: '', day_of_week: 1, quantity: 1 }]);
  };

  const handleRemoveItem = (index) => {
    setItems(items.filter((_, i) => i !== index));
  };

  const handleItemChange = (index, field, value) => {
    const newItems = [...items];
    newItems[index] = { ...newItems[index], [field]: field === 'product_id' || field === 'day_of_week' || field === 'quantity' ? parseInt(value) || 0 : value };
    setItems(newItems);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!customerId) { alert('Velg en kunde'); return; }

    setSaving(true);
    try {
      const url = template ? `/api/v1/templates/${template.id}` : '/api/v1/templates';
      const method = template ? 'PATCH' : 'POST';
      
      const body = template 
        ? { name, is_active: true }
        : { customer_id: parseInt(customerId), name, items: items.filter(i => i.product_id && i.quantity > 0) };

      const response = await authFetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Kunne ikke lagre mal');
      }

      onSave();
    } catch (err) {
      alert(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto m-4">
        <div className="p-6 border-b flex items-center justify-between">
          <h2 className="text-xl font-semibold">{template ? 'Rediger mal' : 'Ny bestillingsmal'}</h2>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded"><X className="w-5 h-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">Kunde *</label>
              <select 
                value={customerId} 
                onChange={(e) => setCustomerId(e.target.value)} 
                className="input"
                disabled={!!template}
                required
              >
                <option value="">Velg kunde...</option>
                {customers.map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Malnavn</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} className="input" />
            </div>
          </div>

          {!template && (
            <>
              <div className="flex items-center justify-between pt-4 border-t">
                <h3 className="font-medium">Produkter</h3>
                <button type="button" onClick={handleAddItem} className="text-sm text-amber-600 hover:underline">+ Legg til produkt</button>
              </div>

              {items.length === 0 ? (
                <p className="text-sm text-gray-500 italic">Ingen produkter lagt til. Klikk "Legg til produkt" for å starte.</p>
              ) : (
                <div className="space-y-3">
                  {items.map((item, index) => (
                    <div key={index} className="grid grid-cols-12 gap-2 items-center">
                      <select 
                        value={item.product_id} 
                        onChange={(e) => handleItemChange(index, 'product_id', e.target.value)}
                        className="input col-span-5"
                      >
                        <option value="">Velg produkt...</option>
                        {products.map(p => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </select>
                      <select 
                        value={item.day_of_week} 
                        onChange={(e) => handleItemChange(index, 'day_of_week', e.target.value)}
                        className="input col-span-3"
                      >
                        {['Mandag', 'Tirsdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lørdag', 'Søndag'].map((day, i) => (
                          <option key={i} value={i + 1}>{day}</option>
                        ))}
                      </select>
                      <input 
                        type="number" 
                        value={item.quantity} 
                        onChange={(e) => handleItemChange(index, 'quantity', e.target.value)}
                        className="input col-span-2"
                        min="1"
                        placeholder="Antall"
                      />
                      <button type="button" onClick={() => handleRemoveItem(index)} className="col-span-2 p-2 text-red-500 hover:bg-red-50 rounded">
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          <div className="flex justify-end gap-3 pt-4 border-t">
            <button type="button" onClick={onClose} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Avbryt</button>
            <button type="submit" disabled={saving} className="btn-primary flex items-center gap-2">
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Lagre
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
