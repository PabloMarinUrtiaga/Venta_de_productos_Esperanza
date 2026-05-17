from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from .models import Producto, Pedido, PedidoItem, Perfil
import mercadopago, json
from django.conf import settings
from django.db import transaction
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Q, Sum
from decimal import Decimal, InvalidOperation
from django_ratelimit.decorators import ratelimit
import re

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

    # 🔒 Solo POST
    if request.method != 'POST':
        return redirect('/productos/')

    # 🔒 Validar producto existente
    try:
        producto = Producto.objects.get(id=producto_id, activo=True)

    except Producto.DoesNotExist:
        messages.error(request, 'Producto no encontrado')
        return redirect('/productos/')

    # 🔒 Validar stock
    if producto.stock <= 0:
        messages.error(request, 'Producto sin stock')
        return redirect('/productos/')

    carrito = request.session.get('carrito', {})

    cantidad_actual = carrito.get(str(producto_id), 0)

    # 🔒 Cantidad máxima
    CANTIDAD_MAXIMA = 5000

    nueva_cantidad = cantidad_actual + 1

    if nueva_cantidad > CANTIDAD_MAXIMA:
        messages.error(request, 'Cantidad máxima alcanzada')
        return redirect('/productos/')

    # 🔒 No permitir superar stock
    if nueva_cantidad > producto.stock:
        messages.error(
            request,
            f'Solo hay {producto.stock} unidades disponibles'
        )
        return redirect('/productos/')

    carrito[str(producto_id)] = nueva_cantidad

    request.session['carrito'] = carrito
    request.session.modified = True

    return redirect('/productos/')
    


# ── Ver carrito ───────────────────────────────
def ver_carrito(request):
    carrito = request.session.get('carrito', {})
    productos = []
    total = 0
    for producto_id, cantidad in carrito.items():
        try:
            producto = Producto.objects.get(id=producto_id,activo=True)
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
    if request.method != 'POST':
        return redirect('/carrito/')
    carrito = request.session.get('carrito', {})
    if str(producto_id) in carrito:
        del carrito[str(producto_id)]
    request.session['carrito'] = carrito
    return redirect('/carrito/')


# ── Vaciar carrito ────────────────────────────
def vaciar_carrito(request):
    if request.method != 'POST':
        return redirect('/carrito/')
    request.session['carrito'] = {}
    return redirect('/carrito/')

# ── Sincronizacion Carrito ────────────────────────────

@login_required
def sincronizar_carrito(request):
   # 🔒 Solo POST
    if request.method != 'POST':
        return JsonResponse({
            'ok': False,
            'error': 'Método inválido'
        }, status=405)

    # 🔒 Content-Type JSON
    if request.content_type != 'application/json':
        return JsonResponse({
            'ok': False,
            'error': 'Formato inválido'
        }, status=400)

    # 🔒 Limitar tamaño del body
    if len(request.body) > 10000:
        return JsonResponse({
            'ok': False,
            'error': 'Request demasiado grande'
        }, status=413)

    # 🔒 Parsear JSON seguro
    try:

        data = json.loads(request.body)

    except json.JSONDecodeError:

        return JsonResponse({
            'ok': False,
            'error': 'JSON inválido'
        }, status=400)

    carrito = data.get('carrito')

    # 🔒 Debe ser dict
    if not isinstance(carrito, dict):

        return JsonResponse({
            'ok': False,
            'error': 'Carrito inválido'
        }, status=400)

    # 🔒 Máximo productos
    if len(carrito) > 100:

        return JsonResponse({
            'ok': False,
            'error': 'Demasiados productos'
        }, status=400)

    carrito_limpio = {}

    for producto_id, cantidad in carrito.items():

        # 🔒 ID numérico
        try:
            producto_id = int(producto_id)

        except ValueError:

            continue

        # 🔒 Cantidad entera
        try:
            cantidad = int(cantidad)

        except ValueError:

            continue

        # 🔒 Cantidad válida
        if cantidad <= 0:
            continue

        # 🔒 Evitar abusos
        if cantidad > 1000:
            cantidad = 1000

        # 🔒 Verificar producto real
        try:

            producto = Producto.objects.get(
                id=producto_id,
                activo=True
            )

        except Producto.DoesNotExist:

            continue

        # 🔒 Nunca superar stock real
        cantidad = min(cantidad, producto.stock)

        # 🔒 Si no hay stock, no agregar
        if cantidad <= 0:
            continue

        carrito_limpio[str(producto_id)] = cantidad

    # 🔒 Guardar solo carrito validado
    request.session['carrito'] = carrito_limpio
    request.session.modified = True

    return JsonResponse({
        'ok': True
    })
#Repetir pedido

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

    # ─────────────────────────────
    # VALIDAR CARRITO
    # ─────────────────────────────
    if not carrito:
        messages.error(request, 'Tu carrito está vacío')
        return redirect('/carrito/')

    # 👤 Perfil opcional
    try:
        perfil = Perfil.objects.get(user=request.user)
    except Perfil.DoesNotExist:
        perfil = None

    # ─────────────────────────────
    # PREVIEW
    # ─────────────────────────────
    items = []
    total = Decimal('0.00')

    for producto_id, cantidad in carrito.items():

        try:
            producto = Producto.objects.get(id=producto_id)

            cantidad = int(cantidad)

            # VALIDAR CANTIDAD
            if cantidad <= 0:
                continue

            subtotal = producto.precio * cantidad
            total += subtotal

            items.append({
                'nombre': producto.nombre,
                'cantidad': cantidad,
                'subtotal': subtotal,
            })

        except Producto.DoesNotExist:
            continue #REVISAR

        except ValueError:
            continue # REVISAR

    # ─────────────────────────────
    # POST → PROCESAR COMPRA
    # ─────────────────────────────
    if request.method == 'POST':

        # ─────────────────────────────
        # DATOS FORM
        # ─────────────────────────────
        nombre = request.POST.get('nombre', '').strip()
        apellido = request.POST.get('apellido', '').strip()
        email = request.POST.get('email', '').strip()
        telefono = request.POST.get('telefono', '').strip()

        entrega = request.POST.get('entrega', 'retiro').strip()

        direccion = request.POST.get('direccion', '').strip()
        piso_depto = request.POST.get('piso_depto', '').strip()
        localidad = request.POST.get('localidad', '').strip()
        codigo_postal = request.POST.get('codigo_postal', '').strip()
        notas_envio = request.POST.get('notas_envio', '').strip()

        pago = request.POST.get('pago', '').strip()
        notas = request.POST.get('notas', '').strip()

        # ─────────────────────────────
        # VALIDACIONES PERSONALES
        # ─────────────────────────────
        if not nombre:
            messages.error(request, 'Ingresá tu nombre')
            return redirect('/checkout/')

        if len(nombre) > 100:
            messages.error(request, 'Nombre demasiado largo')
            return redirect('/checkout/')

        if len(apellido) > 100:
            messages.error(request, 'Apellido demasiado largo')
            return redirect('/checkout/')

        # EMAIL
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, 'Email inválido')
            return redirect('/checkout/')

        # TELÉFONO
        telefono_limpio = telefono.replace(' ', '').replace('-', '')

        if not telefono_limpio.isdigit():
            messages.error(request, 'Teléfono inválido')
            return redirect('/checkout/')

        if len(telefono_limpio) < 6:
            messages.error(request, 'Teléfono demasiado corto')
            return redirect('/checkout/')

        # ─────────────────────────────
        # VALIDAR ENTREGA
        # ─────────────────────────────
        entregas_validas = ['retiro', 'domicilio']

        if entrega not in entregas_validas:
            messages.error(request, 'Tipo de entrega inválido')
            return redirect('/checkout/')

        # SI ES DOMICILIO
        if entrega == 'domicilio':

            if not direccion:
                messages.error(request, 'Ingresá la dirección')
                return redirect('/checkout/')

            if not localidad:
                messages.error(request, 'Ingresá la localidad')
                return redirect('/checkout/')
            
            if not codigo_postal:
                messages.error(request, 'Ingresá el código postal')
                return redirect('/checkout/')
            
        # ─────────────────────────────
        # VALIDAR PAGO
        # ─────────────────────────────
        pagos_validos = [
            'transferencia',
            'efectivo',
            'mercadopago'
        ]

        if pago not in pagos_validos:
            messages.error(request, 'Método de pago inválido')
            return redirect('/checkout/')

        # ─────────────────────────────
        # VALIDAR STOCK + LOCK DB
        # ─────────────────────────────
        with transaction.atomic():

            productos_bloqueados = []
            total = Decimal('0.00')

            for producto_id, cantidad in carrito.items():

                try:
                    producto = Producto.objects.select_for_update().get(id=producto_id)

                    cantidad = int(cantidad)

                    # VALIDAR CANTIDAD
                    if cantidad <= 0:
                        messages.error(request, 'Cantidad inválida')
                        return redirect('/carrito/')

                    # LIMITAR ABUSOS
                    if cantidad > 1000:
                        messages.error(request, 'Cantidad demasiado grande')
                        return redirect('/carrito/')

                    # STOCK
                    if producto.stock < cantidad:
                        messages.error(
                            request,
                            f'Stock insuficiente para {producto.nombre}'
                        )
                        return redirect('/carrito/')

                    subtotal = producto.precio * cantidad
                    total += subtotal

                    productos_bloqueados.append((producto, cantidad))

                except Producto.DoesNotExist:
                    messages.error(request, 'Un producto ya no existe')
                    return redirect('/carrito/')

                except ValueError:
                    messages.error(request, 'Cantidad inválida')
                    return redirect('/carrito/')

             # VALIDAR TOTAL
            if total <= 0:
                messages.error(request, 'Total inválido')
                return redirect('/carrito/')

            # ─────────────────────────────
            # CREAR PEDIDO
            # ─────────────────────────────
            pedido = Pedido.objects.create(
                user=request.user,
                total=total,
                nombre=nombre,
                apellido=apellido,
                email=email,
                telefono=telefono,
                entrega=entrega,
                direccion=direccion,
                piso_depto=piso_depto,
                localidad=localidad,
                codigo_postal=codigo_postal,
                notas_envio=notas_envio,
                pago=pago,
                notas=notas,
            )

            # ─────────────────────────────
            # CREAR ITEMS
            # ─────────────────────────────
            for producto, cantidad in productos_bloqueados:

                PedidoItem.objects.create(
                    pedido=pedido,
                    producto=producto,
                    cantidad=cantidad,
                    precio=producto.precio,
                )

                # SOLO descontar stock si NO es MercadoPago
                if pago != 'mercadopago':

                    producto.stock -= cantidad

                    producto.save(update_fields=['stock'])

        # LIMPIAR CARRITO
        request.session['carrito'] = {}
        request.session.modified = True

        # ─────────────────────────────
        # MERCADOPAGO
        # ─────────────────────────────
        if pago == 'mercadopago':

            preference_data = {
                'items': [
                    {
                        'title': f'Pedido #{pedido.id}',
                        'quantity': 1,
                        'currency_id': 'ARS',
                        'unit_price': float(total)
                    }
                ],

                'external_reference': str(pedido.id),
#CAMBIAR EN PRODUCCION#########################################################################
                'back_urls': {
                    'success': f'http://127.0.0.1:8000/compra-exitosa/{pedido.id}/',#HTTPS_TODO
                    'failure': 'http://127.0.0.1:8000/carrito/',
                    'pending': 'http://127.0.0.1:8000/carrito/',
                },

                'auto_return': 'approved',

                'notification_url': 'https://TU-URL/webhook/mercadopago/',
            }
##############################################################################################
            preference_response = sdk.preference().create(preference_data)

            status = preference_response.get('status')

            if status not in [200, 201]:
                print("ERROR MP STATUS:", status)
                print(preference_response)

                messages.error(request, 'Error al conectar con MercadoPago')
                return redirect('/carrito/')

            preference = preference_response['response']
            print(preference_response)

            pedido.mp_preference_id = preference.get('id', '')
            pedido.save()

            return redirect(preference['init_point'])

        # ─────────────────────────────
        # OTROS PAGOS
        # ─────────────────────────────
        messages.success(request, 'Compra realizada correctamente')

        return redirect(f'/compra-exitosa/{pedido.id}/')

    # ─────────────────────────────
    # GET
    # ─────────────────────────────
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
EMAILS_TEMPORALES = [
    'tempmail.com',
    '10minutemail.com',
    'guerrillamail.com',
    'mailinator.com',
    'yopmail.com',
]
def registro(request):

    if request.method == 'POST':

        username  = request.POST.get('username', '').strip()
        password  = request.POST.get('password', '')
        password2 = request.POST.get('password2', '')
        email     = request.POST.get('email', '').strip().lower()
        telefono  = request.POST.get('telefono', '').strip()

        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()

        # ─────────────────────────────
        # VALIDAR USERNAME
        # ─────────────────────────────

        if len(username) < 3:
            return render(request, 'productos/login.html', {
                'error_registro': 'El usuario debe tener al menos 3 caracteres',
                'modo_registro': True,
            })

        if len(username) > 30:
            return render(request, 'productos/login.html', {
                'error_registro': 'El usuario es demasiado largo',
                'modo_registro': True,
            })

        # Solo letras, números y _
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            return render(request, 'productos/login.html', {
                'error_registro': 'El usuario solo puede tener letras, números y guiones bajos',
                'modo_registro': True,
            })

        # ─────────────────────────────
        # VALIDAR EMAIL
        # ─────────────────────────────

        if not email:
            return render(request, 'productos/login.html', {
                'error_registro': 'El email es obligatorio',
                'modo_registro': True,
            })

        if len(email) > 120:
            return render(request, 'productos/login.html', {
                'error_registro': 'El email es demasiado largo',
                'modo_registro': True,
            })

        # Validar formato real
        try:
            validate_email(email)

        except ValidationError:

            return render(request, 'productos/login.html', {
                'error_registro': 'Ingresá un email válido',
                'modo_registro': True,
            })

        # Bloquear emails temporales
        dominio = email.split('@')[-1].lower()

        if dominio in EMAILS_TEMPORALES:

            return render(request, 'productos/login.html', {
                'error_registro': 'No se permiten emails temporales',
                'modo_registro': True,
            })

        # ─────────────────────────────
        # VALIDAR TELÉFONO
        # ─────────────────────────────

        if telefono and len(telefono) > 25:
            return render(request, 'productos/login.html', {
                'error_registro': 'El teléfono es demasiado largo',
                'modo_registro': True,
            })

        # ─────────────────────────────
        # VALIDAR NOMBRE/APELLIDO
        # ─────────────────────────────

        if len(first_name) > 100 or len(last_name) > 100:
            return render(request, 'productos/login.html', {
                'error_registro': 'Nombre o apellido demasiado largo',
                'modo_registro': True,
            })

        # ─────────────────────────────
        # VALIDAR PASSWORDS
        # ─────────────────────────────

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

        # ─────────────────────────────
        # VALIDAR DUPLICADOS
        # ─────────────────────────────

        if User.objects.filter(username=username).exists():

            return render(request, 'productos/login.html', {
                'error_registro': 'El usuario ya existe',
                'modo_registro': True,
            })

        if User.objects.filter(email=email).exists():

            return render(request, 'productos/login.html', {
                'error_registro': 'Ese email ya está registrado',
                'modo_registro': True,
            })

        # ─────────────────────────────
        # CREAR USUARIO
        # ─────────────────────────────

        user = User.objects.create_user(
            username=username,
            password=password,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )

        Perfil.objects.create(
            user=user,
            numero_cliente=user.id,
            telefono=telefono,
        )

        return render(request, 'productos/login.html', {
            'exito_registro': '¡Cuenta creada! Ya podés ingresar.',
        })

    return render(request, 'productos/login.html', {
        'modo_registro': True
    })
    
# ── Login ─────────────────────────────────────
@ratelimit(key='ip', rate='5/m', block=True)
def login_view(request):

    # 🔒 Solo GET y POST
    if request.method not in ['GET', 'POST']:
        return HttpResponse(status=405)

    if request.method == 'POST':

        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        # 🔒 Validaciones básicas
        if not username or not password:

            return render(request, 'productos/login.html', {
                'error_login': 'Completá usuario y contraseña.',
            })

        # 🔒 Longitudes máximas razonables
        if len(username) > 150 or len(password) > 128:

            return render(request, 'productos/login.html', {
                'error_login': 'Datos inválidos.',
            })

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user:

            login(request, user)

            request.session['carrito'] = {}

            request.session['recien_logueado'] = True

            return redirect('/productos/')

        return render(request, 'productos/login.html', {
            'error_login': 'Usuario o contraseña incorrectos.',
        })

    # GET
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

    # 🔒 Solo GET
    if request.method != 'GET':
        return HttpResponse(status=405)

    # ─────────────────────────────
    # ADMIN → puede ver cualquiera
    # ─────────────────────────────
    if user_id is not None:

        # 🔒 Bloquear usuarios normales
        if not request.user.is_staff:
            return HttpResponse(status=403)

        usuario = get_object_or_404(
            User,
            id=user_id
        )

        pedidos = Pedido.objects.filter(
            user=usuario
        ).order_by('-fecha')

    # ─────────────────────────────
    # Usuario normal → solo su historial
    # ─────────────────────────────
    else:

        usuario = request.user

        pedidos = Pedido.objects.filter(
            user=request.user
        ).order_by('-fecha')

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

    # 🔒 Solo GET
    if request.method != 'GET':
        return HttpResponse(status=405)

    # 🔒 Admin puede ver todo
    if request.user.is_staff:

        pedido = get_object_or_404(
            Pedido,
            id=pedido_id
        )

    # 🔒 Usuario solo sus pedidos
    else:

        pedido = get_object_or_404(
            Pedido,
            id=pedido_id,
            user=request.user
        )

    items = PedidoItem.objects.select_related(
        'producto'
    ).filter(
        pedido=pedido
    )

    return render(request, 'productos/detalle_pedido.html', {
        'pedido': pedido,
        'items': items,
    })
# Panel


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

    # 🔒 Solo admin
    if not request.user.is_staff:
        messages.error(request, 'No autorizado')
        return redirect('/')

    # 🔒 Solo POST
    if request.method != 'POST':
        messages.error(request, 'Método inválido')
        return redirect('/panel/')

    nombre = request.POST.get('nombre', '').strip()
    precio = request.POST.get('precio', '').strip()
    stock = request.POST.get('stock', '').strip()

    # ─────────────────────────────
    # NOMBRE
    # ─────────────────────────────

    if not nombre:
        messages.error(request, 'Ingresá un nombre')
        return redirect('/panel/')

    # 🔒 Longitud
    if len(nombre) > 200:
        messages.error(request, 'Nombre demasiado largo')
        return redirect('/panel/')

    # 🔒 Mínimo caracteres
    if len(nombre) < 2:
        messages.error(request, 'Nombre demasiado corto')
        return redirect('/panel/')

    # 🔒 Evitar espacios absurdos
    nombre = ' '.join(nombre.split())

    # 🔒 Evitar duplicados exactos
    if Producto.objects.filter(nombre__iexact=nombre).exists():
        messages.error(request, 'Ese producto ya existe')
        return redirect('/panel/')

    # ─────────────────────────────
    # PRECIO
    # ─────────────────────────────

    if not precio:
        messages.error(request, 'Ingresá un precio')
        return redirect('/panel/')

    try:

        precio = Decimal(precio)

    except InvalidOperation:

        messages.error(request, 'Precio inválido')
        return redirect('/panel/')

    # 🔒 NaN / infinito
    if not precio.is_finite():
        messages.error(request, 'Precio inválido')
        return redirect('/panel/')

    # 🔒 Precio mínimo
    if precio <= 0:
        messages.error(request, 'Precio inválido')
        return redirect('/panel/')

    # 🔒 Precio absurdo
    if precio > Decimal('99999999'):
        messages.error(request, 'Precio demasiado grande')
        return redirect('/panel/')

    # 🔒 Máximo 2 decimales
    if precio.as_tuple().exponent < -2:
        messages.error(request, 'Máximo 2 decimales')
        return redirect('/panel/')

    # ─────────────────────────────
    # STOCK
    # ─────────────────────────────

    if not stock:
        messages.error(request, 'Ingresá el stock')
        return redirect('/panel/')

    try:

        stock = int(stock)

    except ValueError:

        messages.error(request, 'Stock inválido')
        return redirect('/panel/')

    # 🔒 Stock negativo
    if stock < 0:
        messages.error(request, 'El stock no puede ser negativo')
        return redirect('/panel/')

    # 🔒 Evitar stocks absurdos
    if stock > 999999:
        messages.error(request, 'Stock demasiado grande')
        return redirect('/panel/')

    # ─────────────────────────────
    # CREAR PRODUCTO
    # ─────────────────────────────

    Producto.objects.create(
        nombre=nombre,
        precio=precio,
        stock=stock,
        activo=True
    )

    messages.success(
        request,
        f'Producto "{nombre}" agregado correctamente'
    )

    return redirect('/panel/')

#Eliminar productos

@login_required
def eliminar_producto(request, producto_id):

    if not request.user.is_staff:
        return redirect('/')

    if request.method != 'POST':
        return redirect('/panel/')

    producto = get_object_or_404(Producto, id=producto_id)

    producto.delete()

    return redirect('/panel/')

#Editar precio

@login_required
def editar_precio(request, producto_id):

    # 🔒 Solo admin
    if not request.user.is_staff:
        messages.error(request, 'No autorizado')
        return redirect('/')

    # 🔒 Solo POST
    if request.method != 'POST':
        messages.error(request, 'Método inválido')
        return redirect('/panel/')

    producto = get_object_or_404(Producto, id=producto_id)

    nuevo_precio = request.POST.get('precio', '').strip()

    # 🔒 Obligatorio
    if not nuevo_precio:
        messages.error(request, 'Ingresá un precio')
        return redirect('/panel/')

    # 🔒 Longitud máxima
    if len(nuevo_precio) > 20:
        messages.error(request, 'Precio inválido')
        return redirect('/panel/')

    try:

        nuevo_precio = Decimal(nuevo_precio)

    except InvalidOperation:

        messages.error(request, 'Precio inválido')
        return redirect('/panel/')

    # 🔒 No NaN / infinitos
    if not nuevo_precio.is_finite():
        messages.error(request, 'Precio inválido')
        return redirect('/panel/')

    # 🔒 Precio mínimo
    if nuevo_precio <= 0:
        messages.error(request, 'El precio debe ser mayor a 0')
        return redirect('/panel/')

    # 🔒 Evitar precios absurdos
    if nuevo_precio > Decimal('99999999'):
        messages.error(request, 'Precio demasiado grande')
        return redirect('/panel/')

    # 🔒 Máximo 2 decimales
    if nuevo_precio.as_tuple().exponent < -2:
        messages.error(request, 'Máximo 2 decimales')
        return redirect('/panel/')

    # 🔒 Evitar cambios innecesarios
    if producto.precio == nuevo_precio:
        messages.warning(request, 'El precio ya es ese')
        return redirect('/panel/')

    producto.precio = nuevo_precio
    producto.save(update_fields=['precio'])

    messages.success(
        request,
        f'Precio actualizado para {producto.nombre}'
    )

    return redirect('/panel/')

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

@login_required
def cambiar_stock_ajax(request, producto_id, accion):

    # 🔒 Solo POST
    if request.method != 'POST':
        return JsonResponse({
            'ok': False,
            'error': 'Método inválido'
        }, status=405)

    # 🔒 Solo admin
    if not request.user.is_staff:
        return JsonResponse({
            'ok': False,
            'error': 'No autorizado'
        }, status=403)

    # 🔒 Validar acción
    acciones_validas = ['sumar', 'restar']

    if accion not in acciones_validas:
        return JsonResponse({
            'ok': False,
            'error': 'Acción inválida'
        }, status=400)

    producto = get_object_or_404(Producto, id=producto_id)

    # 🔒 Stock máximo
    STOCK_MAXIMO = 999999

    if accion == 'sumar':

        if producto.stock >= STOCK_MAXIMO:
            return JsonResponse({
                'ok': False,
                'error': 'Stock máximo alcanzado'
            })

        producto.stock += 1

    elif accion == 'restar':

        # 🔒 Nunca negativo
        if producto.stock <= 0:
            return JsonResponse({
                'ok': False,
                'error': 'Stock insuficiente'
            })

        producto.stock -= 1

    producto.save(update_fields=['stock'])

    return JsonResponse({
        'ok': True,
        'stock': producto.stock
    })
    
@login_required
def stock_actual(request, producto_id):
    if not request.user.is_staff:
        return JsonResponse({'ok': False}, status=403)
    producto = get_object_or_404(Producto, id=producto_id)
    return JsonResponse({'stock': producto.stock})

#Editar el stock por mas de a 1
@login_required
def editar_stock(request, producto_id):

    # 🔒 Solo admin
    if not request.user.is_staff:
        return redirect('/')

    # 🔒 Solo POST
    if request.method != 'POST':
        messages.error(request, 'Método inválido')
        return redirect('/panel/')

    producto = get_object_or_404(
        Producto,
        id=producto_id
    )

    nuevo_stock = request.POST.get(
        'stock',
        ''
    ).strip()

    # 🔒 Obligatorio
    if nuevo_stock == '':
        messages.error(request, 'Ingresá un stock')
        return redirect('/panel/')

    # 🔒 Longitud máxima
    if len(nuevo_stock) > 10:
        messages.error(request, 'Stock inválido')
        return redirect('/panel/')

    try:

        nuevo_stock = int(nuevo_stock)

    except ValueError:

        messages.error(request, 'Stock inválido')
        return redirect('/panel/')

    # 🔒 Nunca negativo
    if nuevo_stock < 0:
        messages.error(request, 'El stock no puede ser negativo')
        return redirect('/panel/')

    # 🔒 Límite máximo
    if nuevo_stock > 999999:
        messages.error(request, 'Stock demasiado grande')
        return redirect('/panel/')

    # 🔒 Evitar cambios innecesarios
    if producto.stock == nuevo_stock:
        messages.warning(request, 'El stock ya es ese')
        return redirect('/panel/')

    producto.stock = nuevo_stock

    producto.save(update_fields=['stock'])

    messages.success(
        request,
        f'Stock actualizado para {producto.nombre}'
    )

    return redirect('/panel/')

# WEBHOOK
@csrf_exempt
def mp_webhook(request):

    # ─────────────────────────────
    # SOLO POST
    # ─────────────────────────────
    if request.method != "POST":
        return HttpResponse(status=405)

    # ─────────────────────────────
    # JSON SEGURO
    # ─────────────────────────────
    try:

        data = json.loads(request.body)

    except json.JSONDecodeError:

        print("JSON inválido en webhook")
        return HttpResponse(status=400)

    print("WEBHOOK RECIBIDO:")
    print(data)

    # ─────────────────────────────
    # SOLO PAYMENTS
    # ─────────────────────────────
    if data.get("type") != "payment":
        return HttpResponse(status=200)

    payment_id = data.get("data", {}).get("id")

    if not payment_id:
        return HttpResponse(status=200)

    # ─────────────────────────────
    # CONSULTAR A MP
    # ─────────────────────────────
    try:

        payment_info = sdk.payment().get(payment_id)

    except Exception as e:

        print("Error consultando MP:", e)
        return HttpResponse(status=500)

    payment = payment_info.get("response", {})

    print(payment)

    # ─────────────────────────────
    # VALIDAR STATUS
    # ─────────────────────────────
    if payment.get("status") != "approved":
        return HttpResponse(status=200)

    # ─────────────────────────────
    # VALIDAR EXTERNAL REFERENCE
    # ─────────────────────────────
    pedido_id = payment.get("external_reference")

    if not pedido_id:
        print("Sin external_reference")
        return HttpResponse(status=200)

    # ─────────────────────────────
    # BUSCAR PEDIDO
    # ─────────────────────────────
    try:

        pedido = Pedido.objects.get(id=pedido_id)

    except Pedido.DoesNotExist:

        print("Pedido no encontrado")
        return HttpResponse(status=200)

    # ─────────────────────────────
    # EVITAR DOBLE PROCESAMIENTO
    # ─────────────────────────────
    if pedido.pagado:

        print(f"Pedido {pedido.id} ya estaba pagado")
        return HttpResponse(status=200)

    # ─────────────────────────────
    # VALIDAR MONTO
    # ─────────────────────────────
    monto_mp = Decimal(str(payment.get("transaction_amount", 0)))

    if monto_mp != pedido.total:

        print("Monto inválido")
        print("MP:", monto_mp)
        print("DB:", pedido.total)

        return HttpResponse(status=400)

    # ─────────────────────────────
    # VALIDAR PAYMENT ID
    # ─────────────────────────────
    payment_id_str = str(payment_id)

    if Pedido.objects.filter(mp_payment_id=payment_id_str).exists():

        print("Payment ID duplicado")
        return HttpResponse(status=200)

    # ─────────────────────────────
    # TODO OK → PAGAR
    # ─────────────────────────────
    with transaction.atomic():

        # 🔒 Lock pedido
        pedido = Pedido.objects.select_for_update().get(id=pedido.id)

        # 🔒 Evitar doble procesamiento
        if pedido.pagado:
            return HttpResponse(status=200)

        # ─────────────────────────────
        # DESCONTAR STOCK
        # ─────────────────────────────
        items = PedidoItem.objects.select_related(
            'producto'
        ).filter(
            pedido=pedido
        )

        for item in items:

            producto = Producto.objects.select_for_update().get(
                id=item.producto.id
            )

            # 🔒 Validar stock nuevamente
            if producto.stock < item.cantidad:

                print("Stock insuficiente en webhook")

                return HttpResponse(status=400)

            producto.stock -= item.cantidad

            producto.save(update_fields=['stock'])

    # ─────────────────────────────
    # MARCAR PAGADO
    # ─────────────────────────────
    pedido.pagado = True

    pedido.estado = "en_preparacion"

    pedido.mp_payment_id = payment_id_str

    pedido.fecha_pago = timezone.now()

    pedido.save()

    print(f"Pedido {pedido.id} PAGADO")

    return HttpResponse(status=200)

#Errores
def error_404(request, exception=None):
    return render(request, 'productos/404.html', status=404)

def error_500(request):
    return render(request, 'productos/500.html', status=500)

def error_403(request, exception=None):
    return render(request, 'productos/403.html', status=403)
