# Seguridad antes de publicar FR BEISSHOP

## Ya aplicado en el código

- Las sesiones usan cookies `HttpOnly` y `SameSite=Lax`; en `APP_ENV=production` también exigen HTTPS.
- En producción, la aplicación se niega a iniciar si falta `SECRET_KEY` o tiene menos de 32 caracteres.
- Los intentos fallidos de inicio de sesión quedan limitados durante cinco minutos y se guardan en SQLite; el identificador se almacena como huella HMAC, no como correo o IP en texto claro.
- Las imágenes se validan por su contenido, se limitan a 8 MB y 24 megapíxeles y se vuelven a codificar para quitar metadatos. Se aceptan JPG, PNG y WEBP.

## Pendiente al contratar/configurar el hosting

1. Configurar un dominio propio con HTTPS y ejecutar Flask detrás de un servidor WSGI de producción; no publicar con `app.run()` ni con el servidor de desarrollo de Flask.
2. Cargar `APP_ENV=production` y una `SECRET_KEY` aleatoria de 32 caracteres o más en el administrador de secretos del hosting. No subir `.env`, contraseñas SMTP, claves de Stripe ni credenciales de paquetería al repositorio.
3. Si el hosting usa un proxy HTTPS, configurar correctamente el proxy de confianza para que Flask reciba el esquema HTTPS; no confiar en encabezados reenviados desde cualquier origen.
4. Configurar respaldos automáticos y probar una restauración. Incluir `users.sqlite3`, `products.json`, `auctions.json`, `deleted_products.json`, los archivos de configuración que se decida conservar y `static/uploads/`. Guardarlos cifrados y con acceso restringido.
5. Activar autenticación de dos pasos para la cuenta administradora y revisar que exista un procedimiento de recuperación de acceso.
6. Revisar los registros del hosting, actualizaciones de dependencias y alertas de errores antes de abrir la tienda al público.

La protección de intentos de acceso usa la base SQLite local. Si el hosting ejecuta varias copias independientes de la aplicación, hace falta una base compartida o un limitador compartido para que el límite cubra todas las copias.

