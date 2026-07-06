# Distribuidora Esperanza 🛒

Plataforma de e-commerce mayorista B2B para la venta de productos de la Distribuidora Esperanza. Desarrollada en Django con despliegue en Railway y base de datos PostgreSQL.

## Tecnologías

- **Backend:** Python 3.13 / Django 5.2
- **Base de datos:** PostgreSQL (Railway)
- **Frontend:** HTML, CSS, JavaScript vanilla
- **Imágenes:** Almacenamiento en base64 en PostgreSQL via Pillow
- **Autenticación:** Sistema de usuarios Django con perfiles extendidos
- **Deploy:** Railway con Gunicorn + WhiteNoise

## Funcionalidades

### Catálogo
- Listado de productos con imágenes, precios y stock en tiempo real
- Filtrado por categoría y búsqueda por nombre
- Precios de oferta con badge visual
- Precios mayoristas por cantidad mínima

### Carrito
- Carrito persistente via `localStorage` sincronizado con sesión del servidor
- Cálculo automático de precios mayoristas según cantidad
- Validación de stock en tiempo real

### Checkout
- Formulario con autocompletado de datos del cliente
- Opciones de entrega: retiro en local / envío a domicilio
- Métodos de pago: transferencia bancaria / efectivo
- Datos de transferencia (CBU, Alias, Titular) mostrados automáticamente
- Validación completa de datos en el backend
- Transacción atómica para garantizar consistencia de stock

### Panel de administración
- Gestión de productos: agregar, editar precio, stock, categoría, imagen y ofertas
- Paginación con persistencia de página al realizar acciones
- Gestión de clientes: creacion y eliminaicon de clientes
- Gestión de pedidos: cambio de estado, eliminación con restauración de stock y creacion de pedidos
- Filtros de stock: bajo stock, stock crítico, sin stock
- Búsqueda de productos y clientes

### Pedidos
- Historial de pedidos por usuario
- Detalle de pedido con items y subtotales
- Factura/nota de pedido imprimible
- Botón de envío de comprobante por WhatsApp (para pagos con transferencia)
- Repetir último pedido

