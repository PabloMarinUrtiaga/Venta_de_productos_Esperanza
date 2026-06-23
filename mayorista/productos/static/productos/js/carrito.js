// =============================================
//  CARRITO.JS — Gestión del carrito
//  Lee/escribe localStorage y llama al backend
// =============================================

function getCarrito() {
  return JSON.parse(localStorage.getItem('carrito') || '{}');
}

function setCarrito(c) {
  localStorage.setItem('carrito', JSON.stringify(c));
}

function actualizarContadorNav() {
  const carrito = getCarrito();
  const total   = Object.values(carrito).reduce((a, b) => a + b, 0);
  const el      = document.getElementById('nav-contador');
  if (el) el.textContent = `(${total})`;
}

function mostrarToast(msg, color = 'var(--verde)') {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.style.borderLeftColor = color;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2800);
}

// ── Datos de productos (caché) ────────────────
let catalogoCache = {};

async function obtenerCatalogo() {
  try {
    const res  = await fetch('/productos/', { headers: { 'Accept': 'application/json' } });
    const data = await res.json();
    data.forEach(p => { catalogoCache[p.id] = p; });
  } catch {
    catalogoCache = {
      1:  { id:1,  nombre: 'Leche Entera 1L',        precio: '350.00'  },
      2:  { id:2,  nombre: 'Queso Cremoso 500g',      precio: '980.00'  },
      3:  { id:3,  nombre: 'Atún al Natural x3',      precio: '1250.00' },
      4:  { id:4,  nombre: 'Arvejas en Lata 400g',    precio: '420.00'  },
      5:  { id:5,  nombre: 'Arroz Largo Fino 1kg',    precio: '580.00'  },
      6:  { id:6,  nombre: 'Avena Instantánea 500g',  precio: '490.00'  },
      7:  { id:7,  nombre: 'Galletitas Dulces x3',    precio: '760.00'  },
      8:  { id:8,  nombre: 'Papas Fritas 200g',       precio: '680.00'  },
      9:  { id:9,  nombre: 'Aceite de Girasol 900ml', precio: '1100.00' },
      10: { id:10, nombre: 'Mayonesa 500g',            precio: '870.00'  },
    };
  }
}

// ── Cálculo precio mayorista (Opción B) ──────
function calcularSubtotal(prod, cantidad) {
  const precioNormal = parseFloat(prod.precio);

  if (!prod.precio_mayorista || !prod.cantidad_mayorista) {
    return precioNormal * cantidad;
  }

  const precioMay = parseFloat(prod.precio_mayorista);
  const cantMay   = parseInt(prod.cantidad_mayorista);

  // Packs completos al precio mayorista, resto al precio normal
  const packsCompletos = Math.floor(cantidad / cantMay);
  const resto          = cantidad % cantMay;

  return (packsCompletos * cantMay * precioMay) + (resto * precioNormal);
}

// ── Eliminar producto ────────────────────────
function eliminarDelCarrito(id) {
  const carrito = getCarrito();
  const nombre  = catalogoCache[id]?.nombre || 'Producto';
  delete carrito[String(id)];
  setCarrito(carrito);
  mostrarToast(`🗑️ ${nombre} eliminado`, 'var(--rojo)');
  renderCarrito();
}

// ── Cambiar cantidad ────────────────────────
function cambiarCantidad(id, delta) {
  const carrito = getCarrito();
  const key     = String(id);
  const stock   = catalogoCache[id]?.stock || 0;

  let nuevaCantidad = (carrito[key] || 1) + delta;

  // 🚫 NO BAJAR DE 1
  if (nuevaCantidad <= 0) {
    delete carrito[key];
    setCarrito(carrito);
    renderCarrito();
    return;
  }

  // 🚫 NO SUPERAR STOCK
  if (nuevaCantidad > stock) {
    mostrarToast("🚫 Stock máximo alcanzado", "var(--rojo)");
    return;
  }

  carrito[key] = nuevaCantidad;

  setCarrito(carrito);
  renderCarrito();
}

// ── Vaciar ───────────────────────────────────
function vaciarCarrito() {
  if (!confirm('¿Vaciar todo el carrito?')) return;
  setCarrito({});
  mostrarToast('🗑️ Carrito vaciado', 'var(--naranja)');
  renderCarrito();
}

// ── Render ───────────────────────────────────
function renderCarrito() {
  const carrito    = getCarrito();
  const itemsEl    = document.getElementById('carrito-items');
  const lineasEl   = document.getElementById('resumen-lineas');
  const totalEl    = document.getElementById('resumen-total');
  const containerEl= document.getElementById('carrito-container');
  actualizarContadorNav();

  // Ocultar mientras renderiza para evitar parpadeo
  containerEl.style.display = 'none';

  const ids = Object.keys(carrito);

  if (ids.length === 0) {
    containerEl.style.gridTemplateColumns = '1fr';
    itemsEl.innerHTML = `
      <div class="carrito-vacio">
        <div class="icono-vacio">🛒</div>
        <h3>El carrito está vacío</h3>
        <p style="margin-bottom:1.5rem;">Agregá productos desde el catálogo.</p>
        <a href="/productos/" class="btn btn-rojo" style="display:block; text-align:center; margin-bottom:0.8rem;">Ver catálogo</a>
        <a href="/repetir-pedido/" class="btn" style="display:block; text-align:center; background:var(--verde); color:#fff;">🔁 Repetir último pedido</a>
      </div>`;
    document.getElementById('carrito-resumen').style.display = 'none';
    containerEl.style.display = 'block';
    return;
  }

  document.getElementById('carrito-resumen').style.display = 'block';
  containerEl.style.gridTemplateColumns = '';

  let total = 0;
  let lineasHTML = '';
  let itemsHTML  = '';

  ids.forEach(id => {
    const cantidad = carrito[id];
    const prod     = catalogoCache[id];
    if (!prod) return;

    const precioNormal = parseFloat(prod.precio);
    const subtotal     = calcularSubtotal(prod, cantidad);
    total += subtotal;

    const emoji = { 'Lácteos':'🥛','Enlatados':'🥫','Cereales':'🌾','Snacks':'🍪','Condimentos':'🫙' }[prod.categoria] || '🛒';

    // Info de precio mayorista aplicado
    let precioInfoHtml = `<span style="color:var(--gris); font-size:0.82rem;">× $${precioNormal.toFixed(2)}</span>`;

    if (prod.precio_mayorista && prod.cantidad_mayorista) {
      const precioMay = parseFloat(prod.precio_mayorista);
      const cantMay   = parseInt(prod.cantidad_mayorista);
      const packsCompletos = Math.floor(cantidad / cantMay);
      const resto          = cantidad % cantMay;

      if (packsCompletos > 0 && resto > 0) {
        precioInfoHtml = `
          <span style="color:var(--azul); font-size:0.78rem; font-weight:800;">
            ${packsCompletos * cantMay}u × $${precioMay.toFixed(2)} + ${resto}u × $${precioNormal.toFixed(2)}
          </span>`;
      } else if (packsCompletos > 0) {
        precioInfoHtml = `
          <span style="color:var(--azul); font-size:0.78rem; font-weight:800;">
            💼 Precio mayorista × $${precioMay.toFixed(2)}
          </span>`;
      }
    }

    itemsHTML += `
      <div class="carrito-item" id="item-${id}">
        <div class="carrito-item-icono">${emoji}</div>
        <div class="carrito-item-info">
          <div class="carrito-item-nombre">${prod.nombre}</div>
          <div class="carrito-item-cantidad" style="display:flex; align-items:center; gap:0.5rem; margin-top:0.4rem; flex-wrap:wrap;">
            <button onclick="cambiarCantidad(${id}, -1)" style="border:1.5px solid #ddd; background:#fff; border-radius:6px; width:26px; height:26px; cursor:pointer; font-weight:800;">−</button>
            <span style="font-weight:800; font-size:1rem;">${cantidad}</span>
            <button onclick="cambiarCantidad(${id}, +1)" style="border:1.5px solid #ddd; background:#fff; border-radius:6px; width:26px; height:26px; cursor:pointer; font-weight:800;">+</button>
            ${precioInfoHtml}
          </div>
        </div>
        <div class="carrito-item-precio">$${subtotal.toFixed(2)}</div>
        <button class="btn-eliminar" onclick="eliminarDelCarrito(${id})" title="Eliminar">✕</button>
      </div>`;

    lineasHTML += `
      <div class="resumen-linea">
        <span>${prod.nombre}</span>
        <span>$${subtotal.toFixed(2)}</span>
      </div>`;
  });

  itemsEl.innerHTML  = itemsHTML || '<p style="color:var(--gris); padding:1rem;">Sin datos de productos.</p>';
  lineasEl.innerHTML = lineasHTML;
  totalEl.textContent = `$${total.toFixed(2)}`;

  // Mostrar ahora que está listo
  containerEl.style.display = 'grid';
}

// ── Init ─────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await obtenerCatalogo();
  renderCarrito();
});

// ── Finalizar compra ─────────────────────────
async function finalizarCompra() {
  const carrito = getCarrito();
  const csrfToken = document.cookie.split(';')
    .find(c => c.trim().startsWith('csrftoken='))
    ?.split('=')[1] || '';

  try {
    const res = await fetch('/sincronizar-carrito/', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken,
      },
      body: JSON.stringify({ carrito }),
    });

    if (res.status === 401 || res.status === 403) {
      localStorage.setItem('carrito_pendiente', JSON.stringify(carrito));
      window.location.href = '/login/';
      return;
    }

  } catch (e) {
    mostrarToast('Error de conexión. Intentá de nuevo.', 'var(--rojo)');
    return;
  }

  window.location.href = '/checkout/';
}
