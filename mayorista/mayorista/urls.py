from django.contrib import admin
from django.urls import path
from productos.views import (home, lista_productos, agregar_al_carrito, sincronizar_carrito,
                             ver_carrito, eliminar_del_carrito, vaciar_carrito,
                             checkout, registro, login_view, historial,
                             logout_view, perfil, detalle_pedido, panel,
                             agregar_producto, eliminar_producto, 
                             editar_precio, repetir_pedido, compra_exitosa,
                             cambiar_estado, cambiar_stock_ajax, stock_actual,
                             mp_webhook, editar_stock,)
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('cambiar-estado/<int:pedido_id>/', cambiar_estado),
    path('cambiar-stock-ajax/<int:producto_id>/<str:accion>/', cambiar_stock_ajax),
    path('stock-actual/<int:producto_id>/', stock_actual),
    path('historial/<int:user_id>/', historial),
    path('sincronizar-carrito/', sincronizar_carrito),
    path('admin/', admin.site.urls),
    path('', home),
    path('productos/', lista_productos),
    path('agregar/<int:producto_id>/', agregar_al_carrito),
    path('carrito/', ver_carrito),
    path('eliminar/<int:producto_id>/', eliminar_del_carrito),
    path('vaciar/', vaciar_carrito),
    path('checkout/', checkout),
    path('registro/', registro),
    path('login/', login_view),
    path('perfil/', perfil),
    path('historial/', historial),
    path('logout/', logout_view),
    path('password_reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('password_reset_done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset_done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path('pedido/<int:pedido_id>/', detalle_pedido, name='detalle_pedido'),
    path('panel/', panel, name='panel'),
    path('panel/agregar/', agregar_producto, name='agregar_producto'),
    path('panel/eliminar/<int:producto_id>/', eliminar_producto, name='eliminar_producto'),
    path('panel/producto/<int:producto_id>/precio/', editar_precio, name='editar_precio'),
    path('repetir-pedido/', repetir_pedido, name='repetir_pedido'),
    path('compra-exitosa/<int:pedido_id>/', compra_exitosa, name='compra_exitosa'),
    path('webhook/mercadopago/', mp_webhook),
    path('editar-stock/<int:producto_id>/',editar_stock,name='editar_stock'),
]

handler404 = 'productos.views.error_404'
handler500 = 'productos.views.error_500'
handler403 = 'productos.views.error_403'
