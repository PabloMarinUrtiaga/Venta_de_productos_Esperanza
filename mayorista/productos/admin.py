from django.contrib import admin

# Register your models here.

from .models import Producto, Pedido, PedidoItem

admin.site.register(Producto)
admin.site.register(Pedido)
admin.site.register(PedidoItem)