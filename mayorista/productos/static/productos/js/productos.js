// =============================================
//  PRODUCTOS.JS — Catálogo de productos
//  Se conecta a la API Django: GET /productos/
// =============================================

const EMOJIS_CATEGORIA = {
  'Lácteos':     '🥛',
  'Gaseosas':    '🥤',
  'Aperitivos':  '🥪',
  'Almacén':     '📦',
  'Bebidas Alcohólicas': '🍷',
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

function agregarAlCarrito(id, nombre, cantidad) {
  cantidad = cantidad || 1;
  const carrito = getCarrito();

  const producto = todosLosProductos.find(p => p.id === id);
  const stock = producto?.stock ?? Infinity;

  const cantidadActual = carrito[id] || 0;

  // 🚫 NO PERMITIR SUPERAR STOCK
  if (cantidadActual + cantidad > stock) {
    mostrarToast("🚫 No hay suficiente stock disponible", "var(--rojo)");
    return;
  }

  carrito[id] = cantidadActual + cantidad;

  setCarrito(carrito);

  const msg = cantidad > 1
    ? `✅ Pack x${cantidad} de ${nombre} agregado`
    : `✅ ${nombre} agregado al carrito`;

  mostrarToast(msg);
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
  console.log('renderProductos llamado con', lista.length, 'productos');
  document.getElementById('loader').style.display = 'none';
  document.getElementById('productos-grid').style.visibility = 'visible';
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

    const imagenHtml = p.imagen
      ? `<img src="${p.imagen}" alt="${p.nombre}" style="width:100%; height:100%; object-fit:cover;">`
      : emoji;

     const tieneOferta   = p.oferta_activa && p.precio_oferta;
     const tieneMayorista = p.precio_mayorista && p.cantidad_mayorista;

      let precioHtml = '';

      if (tieneOferta) {
        precioHtml += `
          <div class="producto-precio">
            <span style="text-decoration:line-through; color:var(--gris); font-size:1rem; margin-right:0.4rem;">$${parseFloat(p.precio).toFixed(2)}</span>
            <span style="color:var(--rojo);">$${parseFloat(p.precio_oferta).toFixed(2)}</span>
          </div>
          <div style="font-size:0.75rem; font-weight:800; color:var(--rojo); margin-bottom:0.2rem;">🔥 Precio de oferta</div>`;
      } else {
        precioHtml += `<div class="producto-precio">$${parseFloat(p.precio).toFixed(2)}</div>`;
      }

      if (tieneMayorista) {
        precioHtml += `
          <div style="font-size:0.82rem; font-weight:800; color:var(--azul); margin-bottom:0.4rem;">
            💼 $${parseFloat(p.precio_mayorista).toFixed(2)}/u comprando ${p.cantidad_mayorista} o más
          </div>`;
      }

    const botonesHtml = p.precio_mayorista && p.cantidad_mayorista
      ? `<div style="display:flex; gap:0.5rem;">
           <button class="btn-agregar" style="flex:1;" onclick="agregarAlCarrito(${p.id}, '${p.nombre.replace(/'/g,"\\'")}', 1)">
             🛒 x1
           </button>
           <button class="btn-agregar" style="flex:1; background:var(--azul);" onclick="agregarAlCarrito(${p.id}, '${p.nombre.replace(/'/g,"\\'")}', ${p.cantidad_mayorista})">
             💼 Pack x${p.cantidad_mayorista}
           </button>
         </div>`
      : `<button class="btn-agregar" onclick="agregarAlCarrito(${p.id}, '${p.nombre.replace(/'/g,"\\'")}', 1)">
           🛒 Agregar al carrito
         </button>`;

    return `
      <div class="producto-card">
        <div class="producto-card-img">
          ${imagenHtml}
        </div>
        <div class="producto-card-body">
          <div class="producto-nombre">${p.nombre}</div>
          <div class="producto-categoria">${p.categoria || 'General'}</div>
          ${precioHtml}
          ${botonesHtml}
        </div>
      </div>`;
  }).join('');
}

function filtrarYRender() {
  console.log('filtrarYRender llamado');
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
  console.log('cargarProductos iniciado');
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
      { id: 3, nombre: 'Atún al Natural x3',     precio: '1250.00',stock: 80,  categoria: 'Gaseosas' },
      { id: 4, nombre: 'Arvejas en Lata 400g',   precio: '420.00', stock: 12,  categoria: 'Gaseosas' },
      { id: 5, nombre: 'Arroz Largo Fino 1kg',   precio: '580.00', stock: 200, categoria: 'Aperitivos' },
      { id: 6, nombre: 'Avena Instantánea 500g', precio: '490.00', stock: 3,   categoria: 'Aperitivos' },
      { id: 7, nombre: 'Galletitas Dulces x3',   precio: '760.00', stock: 60,  categoria: 'Almacén' },
      { id: 8, nombre: 'Papas Fritas 200g',      precio: '680.00', stock: 18,  categoria: 'Almacén' },
      { id: 9, nombre: 'Aceite de Girasol 900ml',precio: '1100.00',stock: 90,  categoria: 'Bebidas Alcohólicas' },
      { id:10, nombre: 'Mayonesa 500g',           precio: '870.00', stock: 35,  categoria: 'Bebidas Alcohólicas' },
    ];
    filtrarYRender();
    console.warn('Usando datos de demostración. Conectá el backend Django para datos reales.');
  }
}
