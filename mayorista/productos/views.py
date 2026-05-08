from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
import json
from .models import Producto, Pedido, PedidoItem, Perfil


# ── Home ─────────────────────────────────────
def home(request):
    return HttpResponse("Mayorista funcionando 🚀")


# ── Productos ─────────────────────────────────
def lista_productos(request):
    if request.headers.get('Accept') == 'application/json':
        productos = Producto.objects.filter(activo=True, stock__gt=0)
        data = list(productos.values('id', 'nombre', 'precio', 'stock', 'categoria', 'descripcion'))
        return JsonResponse(data, safe=False)

    recien_logueado = request.session.pop('recien_logueado', False)
    recien_logout   = request.session.pop('recien_logout', False)
    return render(request, 'productos/lista.html', {
        'recien_logueado': recien_logueado,
        'recien_logout':   recien_logout,
    })


# ── Agregar al carrito ────────────────────────
def agregar_al_carrito(request, producto_id):
    carrito = request.session.get('carrito', {})
    if str(producto_id) in carrito:
        carrito[str(producto_id)] += 1
    else:
        carrito[str(producto_id)] = 1
    request.session['carrito'] = carrito
    return redirect('/productos/')


# ── Ver carrito ───────────────────────────────
def ver_carrito(request):
    carrito = request.session.get('carrito', {})
    productos = []
    total = 0
    for producto_id, cantidad in carrito.items():
        try:
            producto = Producto.objects.get(id=producto_id)
            subtotal = producto.precio * cantidad
            total += subtotal
            productos.append({
                'producto': producto,
                'cantidad': cantidad,
                'subtotal': subtotal,
            })
        except Producto.DoesNotExist:
            pass
    return render(request, 'productos/carrito.html', {
        'productos': productos,
        'total': total,
    })


# ── Sincronizar carrito ───────────────────────
def sincronizar_carrito(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        request.session['carrito'] = data.get('carrito', {})
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False})


# ── Eliminar del carrito ──────────────────────
def eliminar_del_carrito(request, producto_id):
    carrito = request.session.get('carrito', {})
    if str(producto_id) in carrito:
        del carrito[str(producto_id)]
    request.session['carrito'] = carrito
    return redirect('/carrito/')


# ── Vaciar carrito ────────────────────────────
def vaciar_carrito(request):
    request.session['carrito'] = {}
    return redirect('/carrito/')


# ── Checkout ──────────────────────────────────
@login_required
def checkout(request):
    carrito = request.session.get('carrito', {})

    if not carrito:
        return redirect('/carrito/')

    try:
        perfil = Perfil.objects.get(user=request.user)
    except Perfil.DoesNotExist:
        perfil = None

    items = []
    total = 0
    for producto_id, cantidad in carrito.items():
        try:
            producto = Producto.objects.get(id=producto_id)
            subtotal = producto.precio * cantidad
            total += subtotal
            items.append({
                'nombre':   producto.nombre,
                'cantidad': cantidad,
                'subtotal': subtotal,
            })
        except Producto.DoesNotExist:
            pass

    if request.method == 'POST':
        pedido = Pedido.objects.create(
            user          = request.user,
            total         = total,
            estado        = 'pendiente',
            nombre        = request.POST.get('nombre', ''),
            apellido      = request.POST.get('apellido', ''),
            email         = request.POST.get('email', ''),
            telefono      = request.POST.get('telefono', ''),
            entrega       = request.POST.get('entrega', 'retiro'),
            direccion     = request.POST.get('direccion', ''),
            piso_depto    = request.POST.get('piso_depto', ''),
            localidad     = request.POST.get('localidad', ''),
            codigo_postal = request.POST.get('codigo_postal', ''),
            notas_envio   = request.POST.get('notas_envio', ''),
            pago          = request.POST.get('pago', 'transferencia'),
            notas         = request.POST.get('notas', ''),
        )

        for producto_id, cantidad in carrito.items():
            try:
                producto = Producto.objects.get(id=producto_id)
                PedidoItem.objects.create(
                    pedido   = pedido,
                    producto = producto,
                    cantidad = cantidad,
                    precio   = producto.precio,
                )
                producto.stock -= cantidad
                producto.save()
            except Producto.DoesNotExist:
                pass

        request.session['carrito'] = {}
        return render(request, 'productos/checkout.html', {
            'total':  total,
            'pedido': pedido,
        })

    return render(request, 'productos/checkout_form.html', {
        'items':  items,
        'total':  total,
        'perfil': perfil,
    })


# ── Cambiar estado del pedido ─────────────────
@login_required
def cambiar_estado(request, pedido_id):
    if not request.user.is_staff:
        return JsonResponse({'ok': False}, status=403)

    if request.method == 'POST':
        pedido = get_object_or_404(Pedido, id=pedido_id)
        nuevo_estado = request.POST.get('estado')
        estados_validos = ['pendiente', 'en_preparacion', 'enviado', 'entregado']
        if nuevo_estado in estados_validos:
            pedido.estado = nuevo_estado
            pedido.save()
        return redirect('/panel/')

    return JsonResponse({'ok': False})


# ── Registro ──────────────────────────────────
def registro(request):
    if request.method == 'POST':
        username  = request.POST['username']
        password  = request.POST['password']
        password2 = request.POST['password2']
        email     = request.POST['email']
        telefono  = request.POST['telefono']

        if password != password2:
            return render(request, 'productos/login.html', {
                'error_registro': 'Las contraseñas no coinciden',
                'modo_registro': True,
            })

        try:
            validate_password(password)
        except ValidationError as e:
            return render(request, 'productos/login.html', {
                'error_registro': e.messages,
                'modo_registro': True,
            })

        if User.objects.filter(username=username).exists():
            return render(request, 'productos/login.html', {
                'error_registro': 'El usuario ya existe',
                'modo_registro': True,
            })

        user = User.objects.create_user(
            username   = username,
            password   = password,
            email      = email,
            first_name = request.POST.get('first_name', ''),
            last_name  = request.POST.get('last_name', ''),
        )
        Perfil.objects.create(
            user           = user,
            numero_cliente = user.id,
            telefono       = telefono,
        )
        return render(request, 'productos/login.html', {
            'exito_registro': '¡Cuenta creada! Ya podés ingresar.',
        })

    return render(request, 'productos/login.html', {'modo_registro': True})


# ── Login ─────────────────────────────────────
def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            request.session['carrito'] = {}
            request.session['recien_logueado'] = True
            return redirect('/productos/')
        else:
            return render(request, 'productos/login.html', {
                'error_login': 'Usuario o contraseña incorrectos.',
            })
    return render(request, 'productos/login.html')


# ── Perfil ────────────────────────────────────
@login_required
def perfil(request):
    try:
        perfil_obj = Perfil.objects.get(user=request.user)
    except Perfil.DoesNotExist:
        perfil_obj = None
    pedidos = Pedido.objects.filter(user=request.user).order_by('-fecha')[:3]
    return render(request, 'productos/perfil.html', {
        'perfil':  perfil_obj,
        'pedidos': pedidos,
    })


# ── Historial ─────────────────────────────────
@login_required
def historial(request, user_id=None):
    if user_id and request.user.is_staff:
        usuario = get_object_or_404(User, id=user_id)
        pedidos = Pedido.objects.filter(user=usuario).order_by('-fecha')
    else:
        usuario = request.user
        pedidos = Pedido.objects.filter(user=request.user).order_by('-fecha')
    return render(request, 'productos/historial.html', {
        'pedidos': pedidos,
        'usuario': usuario,
    })


# ── Detalle de pedido ─────────────────────────
@login_required
def detalle_pedido(request, pedido_id):
    if request.user.is_staff:
        pedido = get_object_or_404(Pedido, id=pedido_id)
    else:
        pedido = get_object_or_404(Pedido, id=pedido_id, user=request.user)
    items = PedidoItem.objects.filter(pedido=pedido)
    return render(request, 'productos/detalle_pedido.html', {
        'pedido': pedido,
        'items':  items,
    })


# ── Logout ────────────────────────────────────
def logout_view(request):
    logout(request)
    request.session['recien_logout'] = True
    return redirect('/login/')


# ── Stock AJAX ───────────────────────────────
def cambiar_stock_ajax(request, producto_id, accion):
    if request.method == 'POST' and request.user.is_staff:
        producto = get_object_or_404(Producto, id=producto_id)
        if accion == 'sumar':
            producto.stock += 1
        elif accion == 'restar' and producto.stock > 0:
            producto.stock -= 1
        producto.save()
        return JsonResponse({'ok': True, 'stock': producto.stock})
    return JsonResponse({'ok': False})


def stock_actual(request, producto_id):
    producto = get_object_or_404(Producto, id=producto_id)
    return JsonResponse({'stock': producto.stock})
