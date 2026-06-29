from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# ── Producto ──────────────────────────────────
CATEGORIA_CHOICES = [
    ('Lácteos',              'Lácteos'),
    ('Aperitivos',           'Aperitivos'),
    ('Almacén',              'Almacén'),
    ('Bebidas Alcohólicas',  'Bebidas Alcohólicas'),
    ('Limpieza', 'Limpieza'),
    ('Bebidas', 'Bebidas'),

]


class Producto(models.Model):
    nombre      = models.CharField(max_length=100)
    precio      = models.DecimalField(max_digits=10, decimal_places=2)
    stock       = models.IntegerField()
    categoria   = models.CharField(max_length=50, choices=CATEGORIA_CHOICES, blank=True)
    descripcion = models.TextField(blank=True)
    activo      = models.BooleanField(default=True)

    imagen_base64 = models.TextField(blank=True, null=True)
    
    precio_mayorista  = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cantidad_mayorista = models.IntegerField(null=True, blank=True)

    precio_oferta = models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    oferta_activa = models.BooleanField(default=False)

    def __str__(self):
        return self.nombre


# ── Pedido ────────────────────────────────────
class Pedido(models.Model):
    ENTREGA_CHOICES = [
        ('retiro',    'Retiro en el local'),
        ('domicilio', 'Envío a domicilio'),
    ]
    PAGO_CHOICES = [
        ('transferencia', 'Transferencia bancaria'),
        ('efectivo',      'Efectivo'),
    ]
    ESTADOS_PEDIDO = [
    ('pendiente_pago', 'Pendiente de pago'),
    ('pagado', 'Pagado'),
    ('en_preparacion', 'En preparación'),
    ('enviado', 'Enviado'),
    ('entregado', 'Entregado'),
    ('cancelado', 'Cancelado'),
    ]

    user          = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    fecha         = models.DateTimeField(auto_now_add=True)
    total         = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=30,choices=ESTADOS_PEDIDO,default='pendiente_pago')

    # Datos del cliente
    nombre        = models.CharField(max_length=100, blank=True)
    apellido      = models.CharField(max_length=100, blank=True)
    email         = models.EmailField(blank=True)
    telefono      = models.CharField(max_length=20, blank=True)

    # Entrega
    entrega       = models.CharField(max_length=20, choices=ENTREGA_CHOICES, default='retiro')
    direccion     = models.CharField(max_length=200, blank=True)
    piso_depto    = models.CharField(max_length=50, blank=True)
    localidad     = models.CharField(max_length=100, blank=True)
    codigo_postal = models.CharField(max_length=10, blank=True)
    notas_envio   = models.TextField(blank=True)

    # Pago
    pago          = models.CharField(max_length=20, choices=PAGO_CHOICES, default='transferencia')

    # Notas generales
    notas         = models.TextField(blank=True)
    

    def __str__(self):
        return f"Pedido #{self.id} — {self.nombre} {self.apellido} [{self.estado}]"


# ── PedidoItem ────────────────────────────────
class PedidoItem(models.Model):
    pedido   = models.ForeignKey(Pedido, on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.IntegerField()
    precio   = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def subtotal(self):
        return self.precio * self.cantidad

    def __str__(self):
        return f"{self.cantidad}x {self.producto.nombre}"


# ── Perfil ────────────────────────────────────
class Perfil(models.Model):
    user           = models.OneToOneField(User, on_delete=models.CASCADE)
    numero_cliente = models.IntegerField(unique=True)
    telefono       = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"Perfil de {self.user.username}"

@receiver(post_save, sender=User)
def crear_perfil(sender, instance, created, **kwargs):
    if created:
        ultimo = Perfil.objects.order_by('-numero_cliente').first()
        numero = (ultimo.numero_cliente + 1) if ultimo and ultimo.numero_cliente else 1
        Perfil.objects.create(user=instance, numero_cliente=numero)