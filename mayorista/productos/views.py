from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import Producto, Pedido, PedidoItem, Perfil
import mercadopago, json
from django.conf import settings
from django.db import transaction
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

sdk = mercadopago.SDK(settings.MP_ACCESS_TOKEN)

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
    
    pedidos = []
    if request.user.is_authenticated:
        pedidos = Pedido.objects.filter(user=request.user)
    
    return render(request, 'productos/carrito.html', {
        'productos': productos,
        'total': total,
        'pedidos': pedidos,
    })


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

# ── Sincronizacion Carrito ────────────────────────────


def sincronizar_carrito(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        request.session['carrito'] = data.get('carrito', {})
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False})

#Repetir pedido
from django.http import JsonResponse

@login_required
def repetir_pedido(request):
    ultimo_pedido = Pedido.objects.filter(user=request.user).order_by('-fecha').first()

    if not ultimo_pedido:
        return redirect('/perfil/')

    items = PedidoItem.objects.filter(pedido=ultimo_pedido)

    carrito = {}

    for item in items:
        if item.producto_id:
            producto = item.producto

            if producto.stock > 0:
                cantidad = min(item.cantidad, producto.stock)
                carrito[str(producto.id)] = cantidad

    request.session['carrito'] = carrito

    # 👇 PASAMOS EL CARRITO AL FRONT
    return render(request, 'productos/repetir_redirect.html', {
        'carrito_json': carrito
    })

#CHECKOUT

@login_required
def checkout(request):

    carrito = request.session.get('carrito', {})

    if not carrito:
        return redirect('/carrito/')

    # 👤 Perfil
    try:
        perfil = Perfil.objects.get(user=request.user)
    except Perfil.DoesNotExist:
        perfil = None

    # 🧾 PREVIEW
    items = []
    total = 0

    for producto_id, cantidad in carrito.items():

        try:
            producto = Producto.objects.get(id=producto_id)

            subtotal = producto.precio * cantidad
            total += subtotal

            items.append({
                'nombre': producto.nombre,
                'cantidad': cantidad,
                'subtotal': subtotal,
            })

        except Producto.DoesNotExist:
            pass

    # ==================================================
    # 🚀 POST → PROCESAR COMPRA
    # ==================================================
    if request.method == 'POST':

        with transaction.atomic():

            productos_bloqueados = []
            total = 0

            # 🔒 VALIDAR STOCK
            for producto_id, cantidad in carrito.items():

                try:
                    producto = Producto.objects.select_for_update().get(
                        id=producto_id
                    )

                    if cantidad <= 0:
                        messages.error(
                            request,
                            "Cantidad inválida en el carrito"
                        )
                        return redirect('/carrito/')

                    if producto.stock < cantidad:

                        messages.error(
                            request,
                            f"No hay suficiente stock de {producto.nombre}. Disponible: {producto.stock}"
                        )

                        return redirect('/carrito/')

                    subtotal = producto.precio * cantidad
                    total += subtotal

                    productos_bloqueados.append(
                        (producto, cantidad)
                    )

                except Producto.DoesNotExist:

                    messages.error(
                        request,
                        "Un producto ya no existe"
                    )

                    return redirect('/carrito/')

            # ==================================================
            # 🧾 CREAR PEDIDO
            # ==================================================
            pedido = Pedido.objects.create(

                user=request.user,
                total=total,

                nombre=request.POST.get('nombre', ''),
                apellido=request.POST.get('apellido', ''),
                email=request.POST.get('email', ''),
                telefono=request.POST.get('telefono', ''),

                entrega=request.POST.get('entrega', 'retiro'),

                direccion=request.POST.get('direccion', ''),
                piso_depto=request.POST.get('piso_depto', ''),
                localidad=request.POST.get('localidad', ''),
                codigo_postal=request.POST.get('codigo_postal', ''),

                notas_envio=request.POST.get('notas_envio', ''),

                pago=request.POST.get('pago', 'transferencia'),

                notas=request.POST.get('notas', ''),
            )

            # ==================================================
            # 📦 ITEMS + DESCONTAR STOCK
            # ==================================================
            for producto, cantidad in productos_bloqueados:

                PedidoItem.objects.create(
                    pedido=pedido,
                    producto=producto,
                    cantidad=cantidad,
                    precio=producto.precio,
                )

                producto.stock -= cantidad

                producto.save(
                    update_fields=['stock']
                )

        # 🧹 limpiar carrito
        request.session['carrito'] = {}

        # ==================================================
        # 💙 MERCADO PAGO
        # ==================================================
        if pedido.pago == 'mercadopago':

            preference_data = {

                "items": [
                    {
                        "title": f"Pedido #{pedido.id} - Esperanza",

                        "quantity": 1,

                        "currency_id": "ARS",

                        "unit_price": float(pedido.total)
                    }
                ],

                "back_urls": {

                    "success":
                        f"http://127.0.0.1:8000/compra-exitosa/{pedido.id}/",

                    "failure":
                        "http://127.0.0.1:8000/carrito/",

                    "pending":
                        "http://127.0.0.1:8000/carrito/",
                },

                

                "external_reference": str(pedido.id),
            }

            preference_response = sdk.preference().create(
                preference_data
            )

            print(preference_response)

            preference = preference_response.get("response", {})

            if "id" not in preference:

                messages.error(
                    request,
                    "Error al conectar con Mercado Pago"
                )

                return redirect('/carrito/')

            pedido.mp_preference_id = preference.get("id")

            pedido.save()

            return redirect(
                preference.get("init_point")
            )

        # ==================================================
        # 💵 EFECTIVO / TRANSFERENCIA
        # ==================================================
        messages.success(
            request,
            "Compra realizada con éxito"
        )

        return redirect(
            f'/compra-exitosa/{pedido.id}/'
        )

    # ==================================================
    # 👀 GET
    # ==================================================
    return render(request, 'productos/checkout_form.html', {

        'items': items,
        'total': total,
        'perfil': perfil,
    })
    
#── Compra exitosa ─────────────────────────────
@login_required
def compra_exitosa(request, pedido_id):
    try:
        pedido = Pedido.objects.get(id=pedido_id, user=request.user)
    except Pedido.DoesNotExist:
        return redirect('/')

    return render(request, 'productos/checkout.html', {
        'pedido': pedido,
        'total': pedido.total
    })

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
            username=username,
            password=password,
            email=email,
            first_name=request.POST.get('first_name', ''),
            last_name=request.POST.get('last_name', ''),
        )
        Perfil.objects.create(
            user=user,
            numero_cliente=user.id,
            telefono=telefono,
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
        'perfil': perfil_obj,
        'pedidos': pedidos,
    })


# ── Historial de pedidos ──────────────────────
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

# ── Logout ────────────────────────────────────
def logout_view(request):
    logout(request)
    request.session['recien_logout'] = True
    return redirect('/login/')

@login_required
def detalle_pedido(request, pedido_id):
    if request.user.is_staff:
        pedido = get_object_or_404(Pedido, id=pedido_id)
    else:
        pedido = get_object_or_404(Pedido, id=pedido_id, user=request.user)
    items = PedidoItem.objects.filter(pedido=pedido)
    return render(request, 'productos/detalle_pedido.html', {
        'pedido': pedido,
        'items': items,
    })
# Panel
from django.db.models import Q, Sum

@login_required
def panel(request):
    # 🔒 Solo admin puede acceder
    if not request.user.is_staff:
        return redirect('/')

    # ─────────────────────────────────────
    # 📦 PRODUCTOS
    # ─────────────────────────────────────
    productos = Producto.objects.all()
    
    # 🔎 Buscador de productos
    busqueda = request.GET.get('q')
    if busqueda:
        productos = productos.filter(
            Q(nombre__icontains=busqueda) |
            Q(descripcion__icontains=busqueda)
        )

    # 🎯 Filtros de stock
    filtro = request.GET.get('filtro')

    if filtro == 'bajo_stock':
        productos = productos.filter(stock__lte=20, stock__gt=5)
    elif filtro == 'stock_critico':
        productos = productos.filter(stock__lte=5, stock__gt=0)
    elif filtro == 'sin_stock':
        productos = productos.filter(stock__lte=0)

    productos = productos.order_by('nombre')

    # ─────────────────────────────────────
    # 📦 PEDIDOS
    # ─────────────────────────────────────
    pedidos = Pedido.objects.select_related('user')

    # 📅 Filtro por fecha
    fecha_desde = request.GET.get('desde')
    fecha_hasta = request.GET.get('hasta')

    if fecha_desde:
        pedidos = pedidos.filter(fecha__date__gte=fecha_desde)

    if fecha_hasta:
        pedidos = pedidos.filter(fecha__date__lte=fecha_hasta)

    pedidos = pedidos.order_by('-fecha')

    # ─────────────────────────────────────
    # 👥 CLIENTES (con métricas)
    # ─────────────────────────────────────
    clientes = Perfil.objects.select_related('user')

    # 🔎 Buscador de clientes
    busqueda_cliente = request.GET.get('cliente')
    if busqueda_cliente:
        clientes = clientes.filter(
            user__username__icontains=busqueda_cliente
        )

    clientes_data = []

    for perfil in clientes:
        pedidos_cliente = Pedido.objects.filter(user=perfil.user)

        # 💰 Total gastado
        total_gastado = pedidos_cliente.aggregate(
            total=Sum('total')
        )['total'] or 0

        # 📦 Cantidad de pedidos
        cantidad_pedidos = pedidos_cliente.count()

        clientes_data.append({
            'usuario': perfil.user,
            'perfil': perfil,
            'total': total_gastado,
            'pedidos': cantidad_pedidos
        })

    # ─────────────────────────────────────
    # 📤 Render final
    # ─────────────────────────────────────
    return render(request, 'productos/panel.html', {
        'productos': productos,
        'clientes': clientes_data,
        'pedidos': pedidos
    })
    

#Agregar productos

@login_required
def agregar_producto(request):
    if not request.user.is_staff:
        return redirect('/')

    if request.method == 'POST':
        nombre = request.POST['nombre']
        precio = request.POST['precio']
        stock = request.POST['stock']

        Producto.objects.create(
            nombre=nombre,
            precio=precio,
            stock=stock,
            activo=True
        )

        return redirect('/panel/')

    return redirect('/panel/')

#Eliminar productos

@login_required
def eliminar_producto(request, producto_id):
    if not request.user.is_staff:
        return redirect('/')

    producto = get_object_or_404(Producto, id=producto_id)
    producto.delete()

    return redirect('/panel/')

#Botones rapido de stock

@login_required
def cambiar_stock(request, producto_id, accion):
    if not request.user.is_staff:
        return redirect('/')

    producto = get_object_or_404(Producto, id=producto_id)

    if accion == 'sumar':
        producto.stock += 1
    elif accion == 'restar':
        if producto.stock > 0:
            producto.stock -= 1

    producto.save()

    return redirect('/panel/')

#Editar precio

@login_required
def editar_precio(request, producto_id):
    if not request.user.is_staff:
        return redirect('/')

    producto = get_object_or_404(Producto, id=producto_id)

    if request.method == 'POST':
        nuevo_precio = request.POST.get('precio', '').strip()
        if nuevo_precio:
            producto.precio = nuevo_precio
            producto.save()

    return redirect('/panel/')

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

#Editar el stock por mas de a 1
@login_required
def editar_stock(request, producto_id):

    if not request.user.is_staff:
        return redirect('/')

    producto = get_object_or_404(Producto, id=producto_id)

    if request.method == 'POST':

        nuevo_stock = request.POST.get('stock', '').strip()

        if nuevo_stock != '':

            try:
                nuevo_stock = int(nuevo_stock)

                if nuevo_stock >= 0:
                    producto.stock = nuevo_stock
                    producto.save()

            except ValueError:
                pass

    return redirect('/panel/')

#WEBHOOK

@csrf_exempt
def mp_webhook(request):

    if request.method != "POST":
        return HttpResponse(status=400)

    data = json.loads(request.body)

    print("WEBHOOK RECIBIDO:")
    print(data)

    # Solo pagos
    if data.get("type") != "payment":
        return HttpResponse(status=200)

    payment_id = data.get("data", {}).get("id")

    if not payment_id:
        return HttpResponse(status=200)

    # Buscar info del pago en Mercado Pago
    payment_info = sdk.payment().get(payment_id)

    payment = payment_info.get("response", {})

    print(payment)

    # Verificar si fue aprobado
    if payment.get("status") == "approved":

        pedido_id = payment.get("external_reference")

        try:

            pedido = Pedido.objects.get(id=pedido_id)

            pedido.pagado = True

            pedido.estado = "en_preparacion"

            pedido.mp_payment_id = str(payment_id)

            pedido.fecha_pago = timezone.now()

            pedido.save()

            print(f"Pedido {pedido.id} PAGADO")

        except Pedido.DoesNotExist:

            print("Pedido no encontrado")

    return HttpResponse(status=200)