// =============================================
//  LOGIN.JS — Autenticación y registro
//  Conecta con Django: /api/login/ y /api/registro/
// =============================================

// ── Tab toggle ───────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.auth-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
  document.getElementById('panel-' + tab).classList.add('active');
  ocultarMensajes();
}

function ocultarMensajes() {
  document.querySelectorAll('.auth-msg').forEach(el => el.style.display = 'none');
}

function mostrarError(id, msg) {
  const el = document.getElementById(id);
  el.textContent = '⚠️ ' + msg;
  el.style.display = 'block';
  shake(el.closest('.auth-panel'));
}

function mostrarExito(id, msg) {
  const el = document.getElementById(id);
  el.textContent = '✅ ' + msg;
  el.style.display = 'block';
}

function shake(el) {
  if (!el) return;
  el.style.animation = 'none';
  el.offsetHeight;
  el.style.animation = 'shake 0.4s ease';
}

// ── Helpers ──────────────────────────────────
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return '';
}

function setLoading(btnId, loading) {
  const btn = document.getElementById(btnId);
  btn.disabled = loading;
  btn.textContent = loading ? 'Procesando...' : btn.dataset.label;
}

// ── LOGIN ─────────────────────────────────────
async function iniciarSesion() {
  const usuario  = document.getElementById('login-usuario').value.trim();
  const password = document.getElementById('login-password').value;
  ocultarMensajes();

  if (!usuario || !password) {
    mostrarError('login-error', 'Completá todos los campos.');
    return;
  }

  setLoading('btn-login', true);

  try {
    const csrfToken = getCookie('csrftoken');
    const res = await fetch('/api/login/', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken,
      },
      body: JSON.stringify({ username: usuario, password }),
    });

    if (res.ok) {
      localStorage.setItem('usuario', usuario);
      mostrarExito('login-success', '¡Bienvenido! Redirigiendo...');
      setTimeout(() => window.location.href = 'index.html', 1200);
    } else {
      const data = await res.json().catch(() => ({}));
      mostrarError('login-error', data.error || 'Usuario o contraseña incorrectos.');
    }

  } catch {
    // Demo mode sin backend
    localStorage.setItem('usuario', usuario);
    mostrarExito('login-success', '¡Bienvenido! Redirigiendo...');
    setTimeout(() => window.location.href = 'index.html', 1200);
  } finally {
    setLoading('btn-login', false);
  }
}

// ── REGISTRO ─────────────────────────────────
async function registrarse() {
  const nombre    = document.getElementById('reg-nombre').value.trim();
  const apellido  = document.getElementById('reg-apellido').value.trim();
  const email     = document.getElementById('reg-email').value.trim();
  const telefono  = document.getElementById('reg-telefono').value.trim();
  const usuario   = document.getElementById('reg-usuario').value.trim();
  const password  = document.getElementById('reg-password').value;
  const password2 = document.getElementById('reg-password2').value;
  ocultarMensajes();

  // Validaciones
  if (!nombre || !apellido || !email || !telefono || !usuario || !password || !password2) {
    mostrarError('reg-error', 'Completá todos los campos.');
    return;
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    mostrarError('reg-error', 'El email no es válido.');
    return;
  }
  if (password.length < 8) {
    mostrarError('reg-error', 'La contraseña debe tener al menos 8 caracteres.');
    return;
  }
  if (password !== password2) {
    mostrarError('reg-error', 'Las contraseñas no coinciden.');
    return;
  }

  setLoading('btn-registro', true);

  try {
    const csrfToken = getCookie('csrftoken');
    const res = await fetch('/api/registro/', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken,
      },
      body: JSON.stringify({ nombre, apellido, email, telefono, username: usuario, password }),
    });

    if (res.ok || res.status === 201) {
      mostrarExito('reg-success', '¡Cuenta creada! Podés ingresar ahora.');
      setTimeout(() => {
        // Pre-rellena el login con el usuario recién creado
        document.getElementById('login-usuario').value = usuario;
        switchTab('login');
      }, 1800);
    } else {
      const data = await res.json().catch(() => ({}));
      mostrarError('reg-error', data.error || 'No se pudo crear la cuenta. Intentá de nuevo.');
    }

  } catch {
    // Demo mode sin backend
    mostrarExito('reg-success', '¡Cuenta creada! Podés ingresar ahora.');
    setTimeout(() => {
      document.getElementById('login-usuario').value = usuario;
      switchTab('login');
    }, 1800);
  } finally {
    setLoading('btn-registro', false);
  }
}

// ── CSS shake ────────────────────────────────
const style = document.createElement('style');
style.textContent = `
  @keyframes shake {
    0%,100%{ transform:translateX(0) }
    20%    { transform:translateX(-8px) }
    40%    { transform:translateX(8px) }
    60%    { transform:translateX(-5px) }
    80%    { transform:translateX(5px) }
  }
`;
document.head.appendChild(style);

// ── Init ─────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Guardar labels para el estado de carga
  document.getElementById('btn-login').dataset.label    = 'Ingresar →';
  document.getElementById('btn-registro').dataset.label = 'Crear cuenta →';

  // Enter en campos dispara la acción del panel activo
  document.querySelectorAll('#panel-login input').forEach(inp => {
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') iniciarSesion(); });
  });
  document.querySelectorAll('#panel-registro input').forEach(inp => {
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') registrarse(); });
  });

  // Redirigir si ya está logueado
  if (localStorage.getItem('usuario')) window.location.href = 'index.html';

  // Si viene con ?registro=1 en la URL, abrir directo el registro
  if (new URLSearchParams(window.location.search).get('registro') === '1') {
    switchTab('registro');
  }
});
