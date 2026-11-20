# Respaldo FR BEISSHOP — 2026-11-20

Este repositorio contiene una copia del código fuente y de los recursos necesarios para reconstruir la tienda FR BEISSHOP.

## Incluido

- `app.py` y módulos auxiliares.
- Plantillas HTML en `templates/`.
- Estilos, JavaScript, iconos, logotipos y fotografías en `static/`.
- Catálogos y contenidos no confidenciales (`products.json`, `homepage.json`, `auctions.json`, etc.).
- `requirements.txt`, `README.md`, `.env.example` y la documentación de publicación.

## Excluido intencionalmente

El repositorio de GitHub es público. Por seguridad no se subieron credenciales ni datos personales:

- `.env`, `.flask-secret`.
- `.admin-config.json`, `.email-config.json`, `.google-config.json` y `.shipping-config.json`.
- `users.sqlite3` (cuentas, datos de clientes y pedidos locales).
- Entornos virtuales, perfiles del navegador, logs y archivos ZIP de respaldo locales.

## Restauración

1. Descarga o clona este repositorio.
2. Crea un entorno virtual e instala `requirements.txt`.
3. Copia `.env.example` como `.env` y agrega las claves de producción en tu equipo.
4. Recupera los archivos de configuración confidenciales desde tu copia segura local (nunca los publiques).
5. Si necesitas conservar usuarios y pedidos, restaura `users.sqlite3` únicamente en el servidor privado.
6. Ejecuta `python app.py` y verifica el flujo de inicio de sesión, catálogo, checkout y administración.

La estructura pública permite recuperar el código y los recursos; las credenciales y la base de datos deben conservarse en una ubicación privada separada.

