import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, Trash2, ShoppingCart, Calendar, User, Package, Search } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

export default function NewOrder() {
  const navigate = useNavigate();
  const { authFetch } = useAuth();
  const [customers, setCustomers] = useState([]);
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [deliveryDate, setDeliveryDate] = useState('');
  const [orderLines, setOrderLines] = useState([]);
  const [notes, setNotes] = useState('');
  const [customerNotes, setCustomerNotes] = useState('');
  const [productSearch, setProductSearch] = useState('');
  const [showProductPicker, setShowProductPicker] = useState(false);

  // Fetch customers and products on mount
  useEffect(() => {
    async function fetchData() {
      try {
        const [custRes, prodRes] = await Promise.all([
          authFetch('/api/v1/customers?page_size=500&is_active=true'),
          authFetch('/api/v1/products?page_size=500&is_active=true')
        ]);
        
        if (!custRes.ok || !prodRes.ok) {
          throw new Error('Kunne ikke hente data');
        }
        
        const custData = await custRes.json();
        const prodData = await prodRes.json();
        
        setCustomers(custData.items || []);
        setProducts(prodData.items || []);
        
        // Set default delivery date to tomorrow
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        setDeliveryDate(tomorrow.toISOString().split('T')[0]);
      } catch (err) {
        console.error('Fetch error:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  const filteredProducts = products.filter(p => 
    p.name.toLowerCase().includes(productSearch.toLowerCase()) ||
    p.sku?.toLowerCase().includes(productSearch.toLowerCase()) ||
    p.category?.toLowerCase().includes(productSearch.toLowerCase())
  );

  const addProduct = (product) => {
    // Check if product already in order
    const existing = orderLines.find(l => l.product_id === product.id);
    if (existing) {
      setOrderLines(orderLines.map(l => 
        l.product_id === product.id 
          ? { ...l, quantity: l.quantity + 1 }
          : l
      ));
    } else {
      setOrderLines([...orderLines, {
        product_id: product.id,
        product_name: product.name,
        product_sku: product.sku,
        quantity: 1,
        unit_price: parseFloat(product.price_incl_vat || product.default_price || product.price || 0),
        notes: ''
      }]);
    }
    setShowProductPicker(false);
    setProductSearch('');
  };

  const updateLineQuantity = (productId, quantity) => {
    if (quantity <= 0) {
      removeLine(productId);
    } else {
      setOrderLines(orderLines.map(l => 
        l.product_id === productId ? { ...l, quantity } : l
      ));
    }
  };

  const removeLine = (productId) => {
    setOrderLines(orderLines.filter(l => l.product_id !== productId));
  };

  const calculateTotal = () => {
    return orderLines.reduce((sum, l) => sum + (l.quantity * l.unit_price), 0);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!selectedCustomer) {
      setError('Velg en kunde');
      return;
    }
    if (!deliveryDate) {
      setError('Velg leveringsdato');
      return;
    }
    if (orderLines.length === 0) {
      setError('Legg til minst ett produkt');
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const orderData = {
        customer_id: selectedCustomer.id,
        delivery_date: deliveryDate,
        internal_notes: notes || null,
        customer_notes: customerNotes || null,
        lines: orderLines.map(l => ({
          product_id: l.product_id,
          quantity: l.quantity,
          notes: l.notes || null
        }))
      };

      const response = await authFetch('/api/v1/orders', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(orderData)
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Kunne ikke opprette ordre');
      }

      const createdOrder = await response.json();
      console.log('Order created:', createdOrder);
      
      // Navigate back to orders list
      navigate('/bestillinger');
    } catch (err) {
      console.error('Submit error:', err);
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <div className="text-gray-500">Laster data...</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="page-header">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/bestillinger')}
            className="p-1.5 hover:bg-gray-100 rounded-md transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h1 className="page-title">Ny bestilling</h1>
            <p className="page-subtitle">Opprett en ny ordre</p>
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Main form */}
          <div className="lg:col-span-2 space-y-6">
            {/* Customer selection */}
            <div className="card">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <User className="w-5 h-5 text-amber-600" />
                Kunde
              </h2>
              <select
                value={selectedCustomer?.id || ''}
                onChange={(e) => {
                  const cust = customers.find(c => c.id === parseInt(e.target.value));
                  setSelectedCustomer(cust);
                }}
                className="input w-full"
                required
              >
                <option value="">Velg kunde...</option>
                {customers.map(c => (
                  <option key={c.id} value={c.id}>
                    {c.name} {c.city ? `(${c.city})` : ''}
                  </option>
                ))}
              </select>
              {selectedCustomer && (
                <div className="mt-3 p-3 bg-gray-50 rounded-lg text-sm">
                  <p className="font-medium">{selectedCustomer.name}</p>
                  {selectedCustomer.address && <p className="text-gray-600">{selectedCustomer.address}</p>}
                  {selectedCustomer.city && <p className="text-gray-600">{selectedCustomer.zip_code} {selectedCustomer.city}</p>}
                  {selectedCustomer.email && <p className="text-gray-600">{selectedCustomer.email}</p>}
                </div>
              )}
            </div>

            {/* Delivery date */}
            <div className="card">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Calendar className="w-5 h-5 text-amber-600" />
                Leveringsdato
              </h2>
              <input
                type="date"
                value={deliveryDate}
                onChange={(e) => setDeliveryDate(e.target.value)}
                min={new Date().toISOString().split('T')[0]}
                className="input w-full"
                required
              />
            </div>

            {/* Products */}
            <div className="card">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold flex items-center gap-2">
                  <Package className="w-5 h-5 text-amber-600" />
                  Produkter
                </h2>
                <button
                  type="button"
                  onClick={() => setShowProductPicker(true)}
                  className="btn-primary flex items-center gap-2"
                >
                  <Plus className="w-4 h-4" />
                  Legg til produkt
                </button>
              </div>

              {orderLines.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <ShoppingCart className="w-12 h-12 mx-auto mb-3 text-gray-300" />
                  <p>Ingen produkter lagt til</p>
                  <p className="text-sm">Klikk "Legg til produkt" for å starte</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {orderLines.map((line) => (
                    <div key={line.product_id} className="flex items-center gap-4 p-3 bg-gray-50 rounded-lg">
                      <div className="flex-1">
                        <p className="font-medium">{line.product_name}</p>
                        <p className="text-sm text-gray-500">{line.product_sku}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => updateLineQuantity(line.product_id, line.quantity - 1)}
                          className="w-8 h-8 flex items-center justify-center bg-white border border-gray-300 rounded hover:bg-gray-50"
                        >
                          -
                        </button>
                        <input
                          type="number"
                          value={line.quantity}
                          onChange={(e) => updateLineQuantity(line.product_id, parseInt(e.target.value) || 0)}
                          className="w-16 text-center input"
                          min="1"
                        />
                        <button
                          type="button"
                          onClick={() => updateLineQuantity(line.product_id, line.quantity + 1)}
                          className="w-8 h-8 flex items-center justify-center bg-white border border-gray-300 rounded hover:bg-gray-50"
                        >
                          +
                        </button>
                      </div>
                      <div className="w-24 text-right font-medium">
                        kr {(line.quantity * line.unit_price).toFixed(2)}
                      </div>
                      <button
                        type="button"
                        onClick={() => removeLine(line.product_id)}
                        className="p-2 text-red-500 hover:bg-red-50 rounded"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Notes */}
            <div className="card">
              <h2 className="text-lg font-semibold mb-4">Notater</h2>
              <div className="space-y-4">
                <div>
                  <label className="label">Interne notater</label>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    rows={2}
                    className="input w-full"
                    placeholder="Notater kun synlig internt..."
                  />
                </div>
                <div>
                  <label className="label">Kundenotater</label>
                  <textarea
                    value={customerNotes}
                    onChange={(e) => setCustomerNotes(e.target.value)}
                    rows={2}
                    className="input w-full"
                    placeholder="Notater synlig for kunde..."
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Summary sidebar */}
          <div className="lg:col-span-1">
            <div className="card sticky top-8">
              <h2 className="text-lg font-semibold mb-4">Oppsummering</h2>
              
              <div className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-600">Kunde</span>
                  <span className="font-medium">{selectedCustomer?.name || '-'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Leveringsdato</span>
                  <span className="font-medium">
                    {deliveryDate ? new Date(deliveryDate).toLocaleDateString('nb-NO') : '-'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Antall produkter</span>
                  <span className="font-medium">{orderLines.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Antall enheter</span>
                  <span className="font-medium">
                    {orderLines.reduce((sum, l) => sum + l.quantity, 0)}
                  </span>
                </div>
              </div>

              <hr className="my-4" />

              <div className="flex justify-between text-lg font-bold">
                <span>Total</span>
                <span className="text-amber-600">kr {calculateTotal().toFixed(2)}</span>
              </div>

              <button
                type="submit"
                disabled={submitting || !selectedCustomer || orderLines.length === 0}
                className="btn-primary w-full mt-6 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submitting ? 'Oppretter...' : 'Opprett bestilling'}
              </button>

              <button
                type="button"
                onClick={() => navigate('/bestillinger')}
                className="w-full mt-3 px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
              >
                Avbryt
              </button>
            </div>
          </div>
        </div>
      </form>

      {/* Product picker modal */}
      {showProductPicker && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col m-4">
            <div className="p-4 border-b">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-semibold">Velg produkt</h3>
                <button
                  onClick={() => {
                    setShowProductPicker(false);
                    setProductSearch('');
                  }}
                  className="p-2 hover:bg-gray-100 rounded"
                >
                  ✕
                </button>
              </div>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type="text"
                  value={productSearch}
                  onChange={(e) => setProductSearch(e.target.value)}
                  placeholder="Søk etter produkt..."
                  className="input pl-10 w-full"
                  autoFocus
                />
              </div>
            </div>
            <div className="overflow-y-auto flex-1 p-4">
              {filteredProducts.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  Ingen produkter funnet
                </div>
              ) : (
                <div className="grid gap-2">
                  {filteredProducts.slice(0, 50).map((product) => (
                    <button
                      key={product.id}
                      onClick={() => addProduct(product)}
                      className="flex items-center justify-between p-3 hover:bg-amber-50 rounded-lg text-left transition-colors border border-transparent hover:border-amber-200"
                    >
                      <div>
                        <p className="font-medium">{product.name}</p>
                        <p className="text-sm text-gray-500">
                          {product.sku} · {product.category}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="font-semibold text-amber-600">
                          kr {parseFloat(product.price_incl_vat || product.default_price || product.price || 0).toFixed(2)}
                        </p>
                        <p className="text-xs text-gray-500">{product.unit || 'stk'}</p>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
