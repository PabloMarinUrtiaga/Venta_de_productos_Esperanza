from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from .models import Producto, Pedido, PedidoItem, Perfil
from django.conf import settings
from django.db import transaction, models
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Q, Sum, Count
from decimal import Decimal, InvalidOperation
from django_ratelimit.decorators import ratelimit
import re, mercadopago, json, hmac, hashlib, base64, io
from django.core.paginator import Paginator
from PIL import Image
from .models import Producto, Pedido, PedidoItem, Perfil


sdk = mercadopago.SDK(settings.MP_ACCESS_TOKEN)

def comprimir_imagen(archivo):
    """
    Recibe un archivo de imagen subido, lo redimensiona a 600px de ancho máx,
    lo comprime a JPEG calidad 80 y devuelve el string en base64.
    """
    try:
        img = Image.open(archivo)

        # Convertir a RGB (por si es PNG con transparencia)
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Redimensionar manteniendo proporción
        ancho_max = 600
        if img.width > ancho_max:
            ratio = ancho_max / img.width
            nuevo_alto = int(img.height * ratio)
            img = img.resize((ancho_max, nuevo_alto), Image.LANCZOS)

        # Comprimir a JPEG calidad 80
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=80, optimize=True)
        buffer.seek(0)

        return base64.b64encode(buffer.read()).decode('utf-8')

    except Exception:
        return None

# ── Home ─────────────────────────────────────
def home(request):
    return HttpResponse("Mayorista funcionando 🚀")


# ── Productos ─────────────────────────────────
def lista_productos(request):
    if request.headers.get('Accept') == 'application/json':
        productos = Producto.objects.filter(activo=True, stock__gt=0)

        data = []
        for p in productos:
            data.append({
                'id': p.id,
                'nombre': p.nombre,
                'precio': p.precio,
                'stock': p.stock,
                'categoria': p.categoria,
                'descripcion': p.descripcion,
                'imagen': f'data:image/jpeg;base64,{p.imagen_base64}' if p.imagen_base64 else None,
                'precio_mayorista': str(p.precio_mayorista) if p.precio_mayorista else None,
                'cantidad_mayorista': p.cantidad_mayorista,
                'precio_oferta': str(p.precio_oferta) if p.precio_oferta else None,
                'oferta_activa': p.oferta_activa,
            })

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
            producto = Producto.objects.get(id=producto_id , activo=True)

            cantidad = int(cantidad)

            # VALIDAR CANTIDAD
            if cantidad <= 0:
                continue

            # Lógica mayorista opción B
            precio_base = producto.precio_oferta if (producto.oferta_activa and producto.precio_oferta) else producto.precio

            if producto.precio_mayorista and producto.cantidad_mayorista and cantidad >= producto.cantidad_mayorista:
                packs    = cantidad // producto.cantidad_mayorista
                resto    = cantidad % producto.cantidad_mayorista
                subtotal = (packs * producto.cantidad_mayorista * producto.precio_mayorista) + (resto * precio_base)
            else:
                subtotal = precio_base * cantidad

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
        
        # NOTAS
        if len(notas) > 500:
            messages.error(request, 'Las notas no pueden superar los 500 caracteres')
            return redirect('/checkout/')

        if len(notas_envio) > 500:
            messages.error(request, 'Las notas de envío no pueden superar los 500 caracteres')
            return redirect('/checkout/')

        # TELÉFONO
        telefono_limpio = telefono.replace(' ', '').replace('-', '')

        if not telefono_limpio.isdigit():
            messages.error(request, 'Teléfono inválido')
            return redirect('/checkout/')

        if len(telefono_limpio) < 6:
            messages.error(request, 'Teléfono demasiado corto')
            return redirect('/checkout/')
        
        if len(telefono_limpio) > 16:
            messages.error(request, 'Teléfono demasiado largo')
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
                    producto = Producto.objects.select_for_update().get(id=producto_id , activo=True)

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

                     # Lógica mayorista opción B
                    precio_base = producto.precio_oferta if (producto.oferta_activa and producto.precio_oferta) else producto.precio

                    if producto.precio_mayorista and producto.cantidad_mayorista and cantidad >= producto.cantidad_mayorista:
                        packs    = cantidad // producto.cantidad_mayorista
                        resto    = cantidad % producto.cantidad_mayorista
                        subtotal = (packs * producto.cantidad_mayorista * producto.precio_mayorista) + (resto * precio_base)
                    else:
                        subtotal = precio_base * cantidad

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

                precio_real = producto.precio_oferta if (producto.oferta_activa and producto.precio_oferta) else producto.precio

                PedidoItem.objects.create(
                    pedido=pedido,
                    producto=producto,
                    cantidad=cantidad,
                    precio=precio_real,
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

                'back_urls': {
                    'success': f'{settings.SITE_URL}/compra-exitosa/{pedido.id}/',
                    'failure': f'{settings.SITE_URL}/carrito/',
                    'pending': f'{settings.SITE_URL}/carrito/',
                },

                'auto_return': 'approved',

                'notification_url': f'{settings.SITE_URL}/webhook/mercadopago/',
                }

            preference_response = sdk.preference().create(preference_data)

            status = preference_response.get('status')

            if status not in [200, 201]:

                messages.error(request, 'Error al conectar con MercadoPago')
                return redirect('/carrito/')

            preference = preference_response['response']
            

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

    if pedido.pago == 'mercadopago' and not pedido.pagado:
        messages.error(request, 'El pago con MercadoPago no fue completado')
        return redirect('/carrito/')

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

@ratelimit(key='ip', rate='3/m', block=True)
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

        ultimo_numero = Perfil.objects.aggregate(
            maximo=models.Max('numero_cliente')
        )['maximo'] or 0

        Perfil.objects.create(
            user=user,
            numero_cliente=ultimo_numero + 1,
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
    total_pedidos = Pedido.objects.filter(user=request.user).count()
    return render(request, 'productos/perfil.html', {
        'perfil': perfil_obj,
        'pedidos': pedidos,
        'total_pedidos': total_pedidos,
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
@login_required
def logout_view(request):
    if request.method != 'POST':
        return redirect('/productos/')
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
        return render(request, 'productos/403.html', status=403)

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
    paginator = Paginator(productos, 20)
    pagina = request.GET.get('pagina', 1)
    productos = paginator.get_page(pagina)

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
    

    # 🔎 Buscador de clientes
    busqueda_cliente = request.GET.get('cliente')


    clientes_data = list(
    Perfil.objects.select_related('user')
    .annotate(
        cantidad_pedidos=Count('user__pedido'),
        total_gastado=Sum('user__pedido__total')
    )
    .filter(
        user__username__icontains=busqueda_cliente if busqueda_cliente else ''
    )
    .values(
        'user__id',
        'user__username',
        'user__email',
        'user__first_name',
        'user__last_name',
        'numero_cliente',
        'telefono',
        'cantidad_pedidos',
        'total_gastado',
    )
)

    # ─────────────────────────────────────
    # 📤 Render final
    # ─────────────────────────────────────
    return render(request, 'productos/panel.html', {
    'productos': productos,
    'clientes': clientes_data,
    'pedidos': pedidos,
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
    # PRECIO MAYORISTA
    # ─────────────────────────────

    precio_mayorista   = request.POST.get('precio_mayorista', '').strip()
    cantidad_mayorista = request.POST.get('cantidad_mayorista', '').strip()

    precio_mayorista_val   = None
    cantidad_mayorista_val = None

    if precio_mayorista:
        try:
            precio_mayorista_val = Decimal(precio_mayorista)
        except InvalidOperation:
            messages.error(request, 'Precio mayorista inválido')
            return redirect('/panel/')

        if precio_mayorista_val <= 0:
            messages.error(request, 'Precio mayorista inválido')
            return redirect('/panel/')

        if precio_mayorista_val >= precio:
            messages.error(request, 'El precio mayorista debe ser menor al precio unitario')
            return redirect('/panel/')

    if cantidad_mayorista:
        try:
            cantidad_mayorista_val = int(cantidad_mayorista)
        except ValueError:
            messages.error(request, 'Cantidad mayorista inválida')
            return redirect('/panel/')

        if cantidad_mayorista_val < 2:
            messages.error(request, 'La cantidad mayorista debe ser al menos 2')
            return redirect('/panel/')

    # ─────────────────────────────
    # CATEGORÍA
    # ─────────────────────────────

    categoria = request.POST.get('categoria', '').strip()

    categorias_validas = ['Lácteos', 'Enlatados', 'Cereales', 'Snacks', 'Condimentos']

    if categoria and categoria not in categorias_validas:
        messages.error(request, 'Categoría inválida')
        return redirect('/panel/')

    # ─────────────────────────────
    # IMAGEN
    # ─────────────────────────────

    imagen_archivo = request.FILES.get('imagen')
    imagen_base64 = None

    if imagen_archivo:

        # 🔒 Límite de tamaño del archivo subido (5MB antes de comprimir)
        if imagen_archivo.size > 5 * 1024 * 1024:
            messages.error(request, 'La imagen no puede superar los 5MB')
            return redirect('/panel/')

        # 🔒 Tipos permitidos
        tipos_validos = ['image/jpeg', 'image/png', 'image/webp']
        if imagen_archivo.content_type not in tipos_validos:
            messages.error(request, 'Formato de imagen no permitido (solo JPG, PNG o WEBP)')
            return redirect('/panel/')

        imagen_base64 = comprimir_imagen(imagen_archivo)

        if imagen_base64 is None:
            messages.error(request, 'No se pudo procesar la imagen')
            return redirect('/panel/')

    # ─────────────────────────────
    # CREAR PRODUCTO
    # ─────────────────────────────

    Producto.objects.create(
        nombre=nombre,
        precio=precio,
        stock=stock,
        categoria=categoria,
        imagen_base64=imagen_base64,
        precio_mayorista=precio_mayorista_val,
        cantidad_mayorista=cantidad_mayorista_val,
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
        estados_validos = ['pendiente_pago', 'en_preparacion', 'enviado', 'entregado', 'cancelado']
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

#OFERTAS:
@login_required
def editar_oferta(request, producto_id): 


    # 🔒 Solo admin
    if not request.user.is_staff:
        messages.error(request, 'No autorizado')
        return redirect('/')

    # 🔒 Solo POST
    if request.method != 'POST':
        messages.error(request, 'Método inválido')
        return redirect('/panel/')

    producto = get_object_or_404(
        Producto,
        id=producto_id
    )

    # ─────────────────────────────
    # CHECKBOX
    # ─────────────────────────────
    oferta_activa = bool(
        request.POST.get('oferta_activa')
    )

    # ─────────────────────────────
    # INPUT
    # ─────────────────────────────
    precio_oferta_input = request.POST.get(
        'precio_oferta',
        ''
    ).strip()

    # ─────────────────────────────
    # ACTUALIZAR PRECIO SI VINO
    # ─────────────────────────────
    if precio_oferta_input != '':

        if len(precio_oferta_input) > 20:
            messages.error(
                request,
                'Precio inválido'
            )
            return redirect('/panel/')

        try:

            precio_oferta = Decimal(
                precio_oferta_input
            )

        except InvalidOperation:

            messages.error(
                request,
                'Precio inválido'
            )
            return redirect('/panel/')

        # 🔒 NaN / infinito
        if not precio_oferta.is_finite():
            messages.error(
                request,
                'Precio inválido'
            )
            return redirect('/panel/')

        # 🔒 Mayor a 0
        if precio_oferta <= 0:
            messages.error(
                request,
                'La oferta debe ser mayor a 0'
            )
            return redirect('/panel/')

        # 🔒 Máximo 2 decimales
        if precio_oferta.as_tuple().exponent < -2:
            messages.error(
                request,
                'Máximo 2 decimales'
            )
            return redirect('/panel/')

        # 🔒 Menor al precio normal
        if precio_oferta >= producto.precio:
            messages.error(
                request,
                'La oferta debe ser menor al precio normal'
            )
            return redirect('/panel/')

        producto.precio_oferta = precio_oferta

    # ─────────────────────────────
    # ACTIVAR / DESACTIVAR
    # ─────────────────────────────
    producto.oferta_activa = oferta_activa

    # 🔒 No permitir activar sin precio
    if (
        producto.oferta_activa
        and not producto.precio_oferta
    ):
        messages.error(
            request,
            'Primero cargá un precio de oferta'
        )
        return redirect('/panel/')

    producto.save(update_fields=[
        'precio_oferta',
        'oferta_activa'
    ])

    messages.success(
        request,
        f'Oferta actualizada para {producto.nombre}'
    )

    return redirect('/panel/')

#CATALOGO
@login_required
def editar_categoria(request, producto_id):

    if not request.user.is_staff:
        messages.error(request, 'No autorizado')
        return redirect('/')

    if request.method != 'POST':
        return redirect('/panel/')

    try:
        producto = Producto.objects.get(id=producto_id)
    except Producto.DoesNotExist:
        messages.error(request, 'Producto no encontrado')
        return redirect('/panel/')

    categoria = request.POST.get('categoria', '').strip()
    categorias_validas = ['Lácteos', 'Enlatados', 'Cereales', 'Snacks', 'Condimentos']

    if categoria not in categorias_validas:
        messages.error(request, 'Categoría inválida')
        return redirect('/panel/')

    producto.categoria = categoria
    producto.save(update_fields=['categoria'])

    messages.success(request, 'Categoría actualizada')
    return redirect('/panel/')

#Cambiar imagen
@login_required
def editar_imagen(request, producto_id):

    if not request.user.is_staff:
        messages.error(request, 'No autorizado')
        return redirect('/')

    if request.method != 'POST':
        return redirect('/panel/')

    try:
        producto = Producto.objects.get(id=producto_id)
    except Producto.DoesNotExist:
        messages.error(request, 'Producto no encontrado')
        return redirect('/panel/')

    imagen_archivo = request.FILES.get('imagen')

    if not imagen_archivo:
        messages.error(request, 'Seleccioná una imagen')
        return redirect('/panel/')

    if imagen_archivo.size > 5 * 1024 * 1024:
        messages.error(request, 'La imagen no puede superar los 5MB')
        return redirect('/panel/')

    tipos_validos = ['image/jpeg', 'image/png', 'image/webp']
    if imagen_archivo.content_type not in tipos_validos:
        messages.error(request, 'Formato de imagen no permitido (solo JPG, PNG o WEBP)')
        return redirect('/panel/')

    imagen_base64 = comprimir_imagen(imagen_archivo)

    if imagen_base64 is None:
        messages.error(request, 'No se pudo procesar la imagen')
        return redirect('/panel/')

    producto.imagen_base64 = imagen_base64
    producto.save(update_fields=['imagen_base64'])

    messages.success(request, 'Imagen actualizada')
    return redirect('/panel/')

# WEBHOOK
@csrf_exempt
def mp_webhook(request):

    if request.method != "POST":
        return HttpResponse(status=405)

    # ─────────────────────────────
    # VERIFICAR FIRMA DE MP
    # ─────────────────────────────
    webhook_secret = settings.MP_WEBHOOK_SECRET

    if webhook_secret:
        x_signature  = request.headers.get("x-signature", "")
        x_request_id = request.headers.get("x-request-id", "")

        ts   = ""
        v1   = ""

        for part in x_signature.split(","):
            part = part.strip()
            if part.startswith("ts="):
                ts = part[3:]
            elif part.startswith("v1="):
                v1 = part[3:]

        if not ts or not v1:
            return HttpResponse(status=400)

        data_id = request.GET.get("data.id", "")

        manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"

        expected = hmac.new(
            key =webhook_secret.encode("utf-8"),
            msg =manifest.encode("utf-8"),
            digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected, v1):
            return HttpResponse(status=401)

    # ─────────────────────────────
    # JSON SEGURO
    # ─────────────────────────────
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

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
        return HttpResponse(status=500)

    payment = payment_info.get("response", {})

    if payment.get("status") != "approved":
        return HttpResponse(status=200)

    pedido_id = payment.get("external_reference")

    if not pedido_id:
        return HttpResponse(status=200)

    try:
        pedido = Pedido.objects.get(id=pedido_id)
    except Pedido.DoesNotExist:
        return HttpResponse(status=200)

    if pedido.pagado:
        return HttpResponse(status=200)

    monto_mp = Decimal(str(payment.get("transaction_amount", 0)))

    if monto_mp != pedido.total:
        return HttpResponse(status=400)

    payment_id_str = str(payment_id)

    if Pedido.objects.filter(mp_payment_id=payment_id_str).exists():
        return HttpResponse(status=200)

    # ─────────────────────────────
    # TODO OK → PAGAR (todo dentro del atomic)
    # ─────────────────────────────
    with transaction.atomic():

        pedido = Pedido.objects.select_for_update().get(id=pedido.id)

        if pedido.pagado:
            return HttpResponse(status=200)

        items = PedidoItem.objects.select_related('producto').filter(pedido=pedido)

        for item in items:
            producto = Producto.objects.select_for_update().get(id=item.producto.id)

            if producto.stock < item.cantidad:
                return HttpResponse(status=400)

            producto.stock -= item.cantidad
            producto.save(update_fields=['stock'])

        # MARCAR PAGADO DENTRO DEL ATOMIC
        pedido.pagado        = True
        pedido.estado        = "en_preparacion"
        pedido.mp_payment_id = payment_id_str
        pedido.fecha_pago    = timezone.now()
        pedido.save()

    return HttpResponse(status=200)

@login_required
def agregar_cliente(request):
    if not request.user.is_staff:
        messages.error(request, 'No autorizado')
        return redirect('/')

    if request.method != 'POST':
        return redirect('/panel/')

    username = request.POST.get('username', '').strip()
    nombre   = request.POST.get('nombre_completo', '').strip()
    telefono = request.POST.get('telefono', '').strip()
    print('DATOS RECIBIDOS:', repr(username), repr(nombre), repr(telefono))

    if not username or not nombre or not telefono:
        messages.error(request, 'Completá todos los campos')
        return redirect('/panel/')

    if User.objects.filter(username=username).exists():
        messages.error(request, 'Ya existe un cliente con ese usuario')
        return redirect('/panel/')

    try:
        user = User.objects.create_user(
            username=username,
            password='esperanza1234',
            first_name=nombre,
        )
        print('USUARIO CREADO:', user.id, user.username)
        Perfil.objects.filter(user=user).update(telefono=telefono)
        print('PERFIL ACTUALIZADO')
    except Exception as e:
        print('ERROR:', e)
        messages.error(request, f'Error: {e}')
        return redirect('/panel/')

    messages.success(request, f'Cliente {nombre} creado. Contraseña temporal: esperanza1234')
    return redirect('/panel/')


@login_required
def eliminar_cliente(request, user_id):
    if not request.user.is_staff:
        return redirect('/')
    if request.method != 'POST':
        return redirect('/panel/')
    try:
        user = User.objects.get(id=user_id)
        user.delete()
        messages.success(request, 'Cliente eliminado')
    except User.DoesNotExist:
        messages.error(request, 'Cliente no encontrado')
    return redirect('/panel/')

@login_required
def crear_pedido(request, user_id):
    if not request.user.is_staff:
        return HttpResponse(status=403)

    cliente = get_object_or_404(User, id=user_id)
    productos = Producto.objects.filter(activo=True, stock__gt=0).order_by('nombre')

    if request.method == 'POST':
        items_seleccionados = []
        total = Decimal('0')

        for producto in productos:
            cantidad_str = request.POST.get(f'cantidad_{producto.id}', '0')
            try:
                cantidad = int(cantidad_str)
            except ValueError:
                cantidad = 0

            if cantidad > 0:
                if cantidad > producto.stock:
                    messages.error(request, f'Stock insuficiente para {producto.nombre}')
                    return redirect(f'/panel/crear-pedido/{user_id}/')

                precio_base = producto.precio_oferta if (producto.oferta_activa and producto.precio_oferta) else producto.precio

                if producto.precio_mayorista and producto.cantidad_mayorista and cantidad >= producto.cantidad_mayorista:
                    packs    = cantidad // producto.cantidad_mayorista
                    resto    = cantidad % producto.cantidad_mayorista
                    subtotal = (packs * producto.cantidad_mayorista * producto.precio_mayorista) + (resto * precio_base)
                else:
                    subtotal = precio_base * cantidad

                items_seleccionados.append((producto, cantidad, subtotal))
                total += subtotal

        if not items_seleccionados:
            messages.error(request, 'Seleccioná al menos un producto')
            return redirect(f'/panel/crear-pedido/{user_id}/')

        pedido = Pedido.objects.create(
            user=cliente,
            total=total,
            nombre=cliente.first_name or cliente.username,
            apellido='',
            email=cliente.email,
            pago='efectivo',
            entrega='retiro',
            estado='en_preparacion',
            pagado=True,
        )

        for producto, cantidad, subtotal in items_seleccionados:
            precio_unitario = subtotal / cantidad
            PedidoItem.objects.create(
                pedido=pedido,
                producto=producto,
                cantidad=cantidad,
                precio=precio_unitario,
            )
            producto.stock -= cantidad
            producto.save(update_fields=['stock'])

        messages.success(request, f'Pedido #{pedido.id} creado para {cliente.username}')
        return redirect(f'/historial/{user_id}/')

    return render(request, 'productos/crear_pedido.html', {
        'cliente': cliente,
        'productos': productos,
    })

@login_required
def factura_pedido(request, pedido_id):
    if not request.user.is_staff:
        return HttpResponse(status=403)
    pedido = get_object_or_404(Pedido, id=pedido_id)
    items = PedidoItem.objects.filter(pedido=pedido).select_related('producto')
    return render(request, 'productos/factura.html', {
        'pedido': pedido,
        'items': items,
    })


#Errores
def error_404(request, exception=None):
    return render(request, 'productos/404.html', status=404)

def error_500(request):
    return render(request, 'productos/500.html', status=500)

def error_403(request, exception=None):
    return render(request, 'productos/403.html', status=403)
