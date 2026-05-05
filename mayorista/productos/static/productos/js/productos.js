// =============================================
//  PRODUCTOS.JS — Catálogo de productos
//  Se conecta a la API Django: GET /productos/
// =============================================

const EMOJIS_CATEGORIA = {
  'Lácteos':     '🥛',
  'Enlatados':   '🥫',
  'Cereales':    '🌾',
  'Snacks':      '🍪',
  'Condimentos': '🫙',
  'default':     '🛒',
};

// ── Estado ──────────────────────────────────
let todosLosProductos = [];
let categoriaActiva   = 'todos';
let busqueda          = '';

// ── Carrito (localStorage) ───────────────────
function getCarrito() {
  return JSON.parse(localStorage.getItem('carrito') || '{}');
}

function setCarrito(c) {
  localStorage.setItem('carrito', JSON.stringify(c));
  actualizarContadorNav();
}

function actualizarContadorNav() {
  const carrito = getCarrito();
  const total   = Object.values(carrito).reduce((a, b) => a + b, 0);
  const el      = document.getElementById('nav-contador');
  if (el) el.textContent = `(${total})`;
}

function agregarAlCarrito(id, nombre) {
  const carrito = getCarrito();

  const producto = todosLosProductos.find(p => p.id === id);
  const stock = producto?.stock ?? Infinity;

  const cantidadActual = carrito[id] || 0;

  // 🚫 NO PERMITIR SUPERAR STOCK
  if (cantidadActual >= stock) {
    mostrarToast("🚫 No hay más stock disponible", "var(--rojo)");
    return;
  }

  carrito[id] = cantidadActual + 1;

  setCarrito(carrito);
  mostrarToast(`✅ ${nombre} agregado al carrito`);
}

// ── Toast ────────────────────────────────────
function mostrarToast(msg) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2800);
}

// ── Render ───────────────────────────────────
function renderProductos(lista) {
  const grid  = document.getElementById('productos-grid');
  const count = document.getElementById('resultado-count');
  if (!grid) return;

  count.textContent = `${lista.length} producto${lista.length !== 1 ? 's' : ''}`;

  if (lista.length === 0) {
    grid.innerHTML = `
      <div style="grid-column:1/-1; text-align:center; padding:3rem; color:var(--gris);">
        <div style="font-size:3rem; margin-bottom:1rem;">🔍</div>
        <p style="font-weight:700;">No se encontraron productos</p>
      </div>`;
    return;
  }

  grid.innerHTML = lista.map(p => {
    const emoji = EMOJIS_CATEGORIA[p.categoria] || EMOJIS_CATEGORIA['default'];
    return `
      <div class="producto-card">
        <div class="producto-card-img">
          ${emoji}
        </div>
        <div class="producto-card-body">
          <div class="producto-nombre">${p.nombre}</div>
          <div class="producto-categoria">${p.categoria || 'General'}</div>
          <div class="producto-precio">$${parseFloat(p.precio).toFixed(2)}</div>
          <button class="btn-agregar" onclick="agregarAlCarrito(${p.id}, '${p.nombre.replace(/'/g,"\\'")}')">
            🛒 Agregar al carrito
          </button>
        </div>
      </div>`;
  }).join('');
}

function filtrarYRender() {
  let lista = todosLosProductos;

  if (categoriaActiva !== 'todos') {
    lista = lista.filter(p => p.categoria === categoriaActiva);
  }

  if (busqueda.trim()) {
    const q = busqueda.toLowerCase();
    lista   = lista.filter(p =>
      p.nombre.toLowerCase().includes(q) ||
      (p.categoria || '').toLowerCase().includes(q)
    );
  }

  renderProductos(lista);
}

// ── Filtros ──────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Filtros botones
  document.querySelectorAll('.filtro-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filtro-btn').forEach(b => b.classList.remove('activo'));
      btn.classList.add('activo');
      categoriaActiva = btn.dataset.cat;
      filtrarYRender();
    });
  });

  // Categorías del hero
  document.querySelectorAll('.categoria-card').forEach(card => {
    card.addEventListener('click', e => {
      e.preventDefault();
      const cat = card.dataset.cat;
      categoriaActiva = cat;
      document.querySelectorAll('.filtro-btn').forEach(b => {
        b.classList.toggle('activo', b.dataset.cat === cat);
      });
      document.getElementById('productos')?.scrollIntoView({ behavior: 'smooth' });
      filtrarYRender();
    });
  });

  // Buscador
  const buscadorEl = document.getElementById('buscador');
  if (buscadorEl) {
    buscadorEl.addEventListener('input', e => {
      busqueda = e.target.value;
      filtrarYRender();
    });
  }

  // Nav login
  const loginLink = document.getElementById('nav-login-link');
  if (loginLink) {
    const usuario = localStorage.getItem('usuario');
    if (usuario) {
      loginLink.textContent = `👤 ${usuario}`;
      loginLink.href = '#';
    }
  }

  actualizarContadorNav();
  cargarProductos();
});

// ── API ──────────────────────────────────────
async function cargarProductos() {
  const grid = document.getElementById('productos-grid');

  // Skeleton loading
  grid.innerHTML = Array(6).fill(`
    <div class="producto-card" style="opacity:0.4; pointer-events:none;">
      <div class="producto-card-img" style="background:#eee;"></div>
      <div class="producto-card-body">
        <div style="height:14px; background:#eee; border-radius:8px; margin-bottom:8px;"></div>
        <div style="height:10px; background:#eee; border-radius:8px; width:60%; margin-bottom:12px;"></div>
        <div style="height:28px; background:#eee; border-radius:8px; margin-bottom:8px;"></div>
        <div style="height:36px; background:#eee; border-radius:8px;"></div>
      </div>
    </div>`).join('');

  try {
    const res = await fetch('/productos/', {
      headers: { 'Accept': 'application/json' }
    });

    if (!res.ok) throw new Error('Error de red');
    const data = await res.json();

    todosLosProductos = data;
    filtrarYRender();

  } catch (err) {
    // Datos de demostración si no hay backend
    todosLosProductos = [
      { id: 1, nombre: 'Leche Entera 1L',       precio: '350.00', stock: 150, categoria: 'Lácteos' },
      { id: 2, nombre: 'Queso Cremoso 500g',     precio: '980.00', stock: 45,  categoria: 'Lácteos' },
      { id: 3, nombre: 'Atún al Natural x3',     precio: '1250.00',stock: 80,  categoria: 'Enlatados' },
      { id: 4, nombre: 'Arvejas en Lata 400g',   precio: '420.00', stock: 12,  categoria: 'Enlatados' },
      { id: 5, nombre: 'Arroz Largo Fino 1kg',   precio: '580.00', stock: 200, categoria: 'Cereales' },
      { id: 6, nombre: 'Avena Instantánea 500g', precio: '490.00', stock: 3,   categoria: 'Cereales' },
      { id: 7, nombre: 'Galletitas Dulces x3',   precio: '760.00', stock: 60,  categoria: 'Snacks' },
      { id: 8, nombre: 'Papas Fritas 200g',      precio: '680.00', stock: 18,  categoria: 'Snacks' },
      { id: 9, nombre: 'Aceite de Girasol 900ml',precio: '1100.00',stock: 90,  categoria: 'Condimentos' },
      { id:10, nombre: 'Mayonesa 500g',           precio: '870.00', stock: 35,  categoria: 'Condimentos' },
    ];
    filtrarYRender();
    console.warn('Usando datos de demostración. Conectá el backend Django para datos reales.');
  }
}
