# FR BEISSHOP

Tienda web de ejemplo para vender equipo de béisbol y softball en México, con pedidos preparados para enviar por WhatsApp. Los pedidos salen desde Mexicali; el costo y el tiempo de envío se confirman según el código postal.

## Requisitos

- Python 3.10 o posterior
- pip

## Instalar y ejecutar en Windows PowerShell

```powershell
cd "$HOME\Documents\FR-Beisshop"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:WHATSAPP_NUMBER = "526861234567"
$env:SECRET_KEY = "cambia-esto-por-una-clave-privada"
$env:ADMIN_PASSWORD = "elige-una-contrasena-segura"
$env:ADMIN_USERNAME = "Javiersin"
$env:GOOGLE_CLIENT_ID = "tu-cliente-web.apps.googleusercontent.com"
python app.py
```

El acceso al panel de administración usa el usuario configurado en `ADMIN_USERNAME`. En esta copia local, el archivo `.admin-config.json` conserva el hash de la contraseña inicial; el archivo está excluido de Git. Antes de publicar, define `ADMIN_USERNAME` y `ADMIN_PASSWORD` o `ADMIN_PASSWORD_HASH` mediante variables de entorno.

Abre `http://localhost:5000` en el navegador. Reemplaza el número de ejemplo por el WhatsApp real del negocio, con código de país y lada, sin `+` ni espacios. Si PowerShell bloquea la activación del entorno virtual, ejecuta `\.venv\Scripts\python.exe -m pip install -r requirements.txt` y luego `\.venv\Scripts\python.exe app.py`.

Los clientes pueden crear una cuenta desde **Iniciar sesión** en la tienda. Las cuentas se guardan localmente en `users.sqlite3` y las contraseñas se almacenan con hash; ese archivo se crea automáticamente al registrar o iniciar sesión.

## Acceso con Google

1. En Google Cloud Console, crea un cliente OAuth de tipo **Aplicación web**.
2. Agrega `http://localhost:5000` como origen autorizado de JavaScript.
3. Copia el ID del cliente a `GOOGLE_CLIENT_ID` antes de iniciar la tienda. Este flujo no requiere un secreto OAuth.
4. Instala las dependencias con `python -m pip install -r requirements.txt` y reinicia `python app.py`.

El botón de Google aparece en **Crear cuenta** e **Iniciar sesión** cuando `GOOGLE_CLIENT_ID` está configurado. El servidor valida el token de identidad de Google antes de crear o vincular la cuenta.

## Antes de vender

- Cambia el catálogo, los precios, las descripciones y las imágenes de muestra en `app.py` por información real. Las imágenes actuales son referencias externas de ejemplo.
- Configura `WHATSAPP_NUMBER` y una `SECRET_KEY` privada.
- El inventario mostrado se considera disponible; los costos y tiempos de envío se calculan según el código postal. Stripe cobra el subtotal de productos; el costo final de envío se confirma por separado.
- `FLASK_DEBUG` está desactivado por defecto. Para publicar el sitio, configura una `SECRET_KEY`, credenciales administrativas, `WHATSAPP_NUMBER` y usa un servidor WSGI.

## Funciones configurables

- El checkout solicita correo y datos de entrega; Stripe es el único método de pago para pedidos nuevos. Los pedidos se guardan con inventario descontado y pueden revisarse desde el panel.
- Para confirmaciones automáticas, configura `EMAIL_NOTIFICATIONS=1`, `SHOP_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` y, opcionalmente, `EMAIL_REPLY_TO`. El comprador recibe el detalle del pedido y la tienda recibe un aviso cuando Stripe confirma el pago. Si SMTP no está configurado, el pedido sigue funcionando sin bloquearse.
- `STRIPE_SECRET_KEY` activa Stripe Checkout con pagos en MXN. Usa una clave `sk_test_...` durante las pruebas y `sk_live_...` al publicar.
- `STRIPE_WEBHOOK_SECRET` confirma los pagos mediante `/webhooks/stripe`. En pruebas locales puedes ejecutar `stripe listen --forward-to http://127.0.0.1:5000/webhooks/stripe` y copiar el valor `whsec_...`.
- `APP_BASE_URL` debe ser la URL pública de la tienda al publicar; en local puede quedarse como `http://127.0.0.1:5000`.
- El sitio incluye contacto, privacidad, términos, cambios y devoluciones en /contacto, /privacidad, /terminos y /cambios-devoluciones.

- Envíos: para activar cotizaciones con Skydropx, configura SKYDROPX_CLIENT_ID, SKYDROPX_CLIENT_SECRET y los datos de origen indicados en .env.example. Las credenciales se usan solo en el servidor; mientras falten, el checkout conserva SHIPPING_ESTIMATE como respaldo.

