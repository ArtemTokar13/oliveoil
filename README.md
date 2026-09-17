# Olivarium

Tienda online de aceite de oliva español. Django + PostgreSQL + Stripe Checkout +
plantillas server-rendered con Tailwind CSS y Alpine.js.

## Stack

- **Backend:** Django 5.2 (LTS), PostgreSQL
- **Pagos:** Stripe Checkout Sessions (redirect alojado) + webhook para confirmar el pago
- **Frontend:** plantillas Django + Tailwind CSS (CLI standalone, sin Node/npm) + Alpine.js
  para mejoras progresivas (steppers de cantidad, menú móvil, mini-carrito, mostrar/ocultar
  formulario de dirección). Todos los formularios funcionan como POST normal sin JavaScript.
- Sin `forms.py`: los formularios personalizados (login, direcciones, contacto,
  checkout) se validan a mano en las vistas. No hay contraseñas de cliente en ningún
  sitio: se inicia sesión con Google o con un código de un solo uso por correo, y
  ambos crean la cuenta automáticamente la primera vez — no existen registro ni
  restablecimiento de contraseña independientes.
- Comprar no requiere cuenta (checkout como invitado); después del pago, el comprador
  puede guardar su dirección y su pedido en una cuenta nueva con un código por correo.

## Apps

| App        | Responsabilidad                                                   |
|------------|---------------------------------------------------------------------|
| `catalog`  | Marca, Categoría, Producto, ProductImage — home y ficha de producto |
| `cart`     | Carrito (sesión anónima + fusión al iniciar sesión)                 |
| `orders`   | Checkout, sesión de Stripe, webhook, pedidos, gastos de envío       |
| `accounts` | Registro, dashboard "Mi cuenta", libreta de direcciones             |
| `pages`    | Páginas legales, sobre nosotros, contacto                           |
| `core`     | Filtros de plantilla compartidos (`eur`), context processor de sitio|

## Puesta en marcha

```bash
python -m venv venv && source venv/bin/activate   # ya existe venv/ en este repo
pip install -r requirements.txt

cp .env.example .env   # y rellena los valores reales
```

Crea la base de datos de Postgres (ajusta usuario/contraseña a tu `.env`):

```bash
psql -U postgres -c "CREATE USER oliveoil WITH PASSWORD 'oliveoil_dev_pw';"
psql -U postgres -c "CREATE DATABASE oliveoil OWNER oliveoil;"
```

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_catalog   # datos de ejemplo opcionales para desarrollo
python manage.py runserver
```

### Tailwind CSS

Se usa el CLI standalone de Tailwind (binario en `bin/tailwindcss`, sin Node/npm).
El CSS compilado ya está en `static/css/output.css`; para regenerarlo tras cambiar
clases en las plantillas o `static/src/input.css`:

```bash
./bin/tailwindcss -i static/src/input.css -o static/css/output.css        # build
./bin/tailwindcss -i static/src/input.css -o static/css/output.css --watch # desarrollo
```

### Google Sign-In

Opcional — sin configurar, el botón "Continuar con Google" simplemente no aparece en
la página de login.

1. Crea un cliente OAuth (tipo "Aplicación web") en
   [Google Cloud Console](https://console.cloud.google.com/apis/credentials).
2. Autoriza el URI de redirección `http://localhost:8000/login/google/callback/`
   (y el equivalente en producción).
3. Copia el ID y el secreto de cliente en `.env` (`GOOGLE_OAUTH_CLIENT_ID`,
   `GOOGLE_OAUTH_CLIENT_SECRET`).

Si el correo de Google no existe todavía como usuario, se crea una cuenta nueva
automáticamente (sin contraseña utilizable — no hay forma de establecer una, solo se
entra por Google o por código). Si ya existe una cuenta con ese correo, inicia sesión
en ella directamente. Solo se acepta si Google marca el correo como verificado
(`email_verified`).

### Login sin contraseña (código por correo) y guardar un pedido de invitado

No existen registro ni contraseñas de cliente: `/login/` solo pide un correo y envía
un código. `accounts.LoginCode` es ese código de 6 dígitos, con hash igual que una
contraseña, de un solo uso y caduca a los 10 minutos (`/login/`, `/login/code/verify/`).
Máximo 5 intentos por código; como mínimo 60 segundos entre reenvíos a la misma
dirección. Si el correo no tiene cuenta todavía, se crea una (sin contraseña
utilizable) al verificar el código correcto — igual que con Google.

Esto es también cómo un comprador invitado convierte su compra en una cuenta: en la
página de estado de un pedido pagado sin cuenta asociada aparece "Guardar mis datos",
que envía un código a `order.email`. Al verificarlo:

- si no existe cuenta con ese correo, se crea una;
- si ya existe (p. ej. una segunda compra como invitado, más adelante, con el mismo
  correo), se entra en esa cuenta — nunca se duplica;
- el pedido se asocia a la cuenta (`Order.user`) y su dirección de envío se guarda en
  la libreta de direcciones (como predeterminada, si es la primera; no se duplica si
  ya existe una dirección idéntica guardada).

Verificar el código es la prueba de que esa persona controla el correo — sin eso, no
habría forma segura de saber que quien pulsa "Guardar mis datos" es realmente el dueño
de esa dirección, y no alguien que la escribió sin más en el checkout.

### Stripe

1. Crea una cuenta de Stripe y copia tus claves de **test** en `.env`
   (`STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`).
2. Instala la [Stripe CLI](https://stripe.com/docs/stripe-cli) y reenvía los webhooks
   al servidor local:
   ```bash
   stripe listen --forward-to localhost:8000/stripe/webhook/
   ```
   Copia el `whsec_...` que imprime en `STRIPE_WEBHOOK_SECRET` de tu `.env`.
3. El pedido se crea como `PENDING` al ir a pagar y solo pasa a `PAID` cuando llega el
   evento `checkout.session.completed` al webhook — la página de estado del pedido
   (`/orders/status/<token>/`) se autorrefresca mientras el pedido sigue pendiente, así
   que un usuario que cierra la pestaña antes de la redirección de éxito no deja el
   pedido en un estado incorrecto.

### Checkout como invitado

Comprar **no** requiere cuenta. Un visitante anónimo puede añadir productos al carrito
(carrito de sesión) y pagar directamente indicando su correo y una dirección de envío
de un solo uso — no se guarda en la libreta de direcciones, que es solo para cuentas.

- `Order.user` es `NULL` en los pedidos de invitado; `Order.email` es quien recibe la
  confirmación en ambos casos (cuenta o invitado).
- Cada pedido tiene un `access_token` (UUID) impredecible. El correo de confirmación
  (enviado desde el webhook, cuando el pago se confirma) enlaza a
  `/orders/status/<token>/` — así un invitado puede volver a ver su pedido sin haber
  iniciado sesión nunca. Los pedidos de usuarios registrados usan además las URLs
  `/orders/<pk>/` (protegidas por sesión, para "Mis pedidos").
- El carrito de un invitado se localiza por `session_key` en el webhook (que no tiene
  cookies de sesión, al ser una llamada servidor-a-servidor de Stripe) en lugar de por
  usuario.

## Variables de entorno

Ver `.env.example` para la lista completa. Además de la base de datos, Stripe y Google
Sign-In, hay identidad legal del vendedor (`SITE_LEGAL_NAME`, `SITE_NIF`, `SITE_ADDRESS`,
`SITE_IAE`) como constantes en `app/settings.py` — aparecen en el Aviso Legal y en el
pie de página; actualízalas si cambian los datos fiscales del vendedor.

## Estado de los pedidos

`PENDING` (creado al ir a pagar) → `PAID` (confirmado por el webhook de Stripe: stock
descontado, carrito vaciado y correo de confirmación enviado) → o `CANCELLED` si el
usuario vuelve desde Stripe sin completar el pago.
