from django.contrib import admin
from django.urls import path
from productos.views import (home, lista_productos, agregar_al_carrito,
                             ver_carrito, eliminar_del_carrito, vaciar_carrito,
                             sincronizar_carrito, checkout, registro, login_view,
                             perfil, historial, detalle_pedido, logout_view,
                             cambiar_estado, cambiar_stock_ajax, stock_actual)
from django.contrib.auth import views as auth_views

urlpatterns = [
    
    path('admin/', admin.site.urls),
    path('', home),
    path('productos/', lista_productos),
    path('agregar/<int:producto_id>/', agregar_al_carrito),
    path('carrito/', ver_carrito),
    path('eliminar/<int:producto_id>/', eliminar_del_carrito),
    path('vaciar/', vaciar_carrito),
    path('sincronizar-carrito/', sincronizar_carrito),
    path('checkout/', checkout),
    path('registro/', registro),
    path('login/', login_view),
    path('perfil/', perfil),
    path('historial/', historial),
    path('historial/<int:user_id>/', historial),
    path('pedido/<int:pedido_id>/', detalle_pedido),
    path('logout/', logout_view),
    path('cambiar-estado/<int:pedido_id>/', cambiar_estado),
    path('cambiar-stock-ajax/<int:producto_id>/<str:accion>/', cambiar_stock_ajax),
    path('stock-actual/<int:producto_id>/', stock_actual),
    path('password_reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('password_reset_done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset_done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
]
