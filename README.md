# purgatory-sync

Bot de Discord independiente, responsabilidad única: mantener sincronizado en Postgres (Supabase) el estado de Discord de cada miembro del servidor de **PURG4TORY**, para que la web ([pagina-web-purgatory](https://github.com/punkyyy01/pagina-web-purgatory)) pueda derivar de ahí propiedades **verificadas** de las cards (4LMA) — cosas que el usuario no puede falsificar porque no las escribe él, las escribe este bot a partir de lo que dice Discord.

No tiene comandos, no responde en el servidor, no tiene web ni dominio propio. Es un worker de fondo: escucha el Gateway, escribe en la base, y listo.

```
Discord (rol, boost, ban, member) → este bot (Gateway) → Postgres → la web lee de ahí
```

---

## Qué sincroniza y por qué

| Campo | De dónde sale | Evento del Gateway |
|---|---|---|
| `is_member` | ¿está en el server ahora mismo? | `GUILD_MEMBER_ADD` / `GUILD_MEMBER_REMOVE` |
| `is_banned` | ¿está baneado? | `GUILD_BAN_ADD` / `GUILD_BAN_REMOVE` |
| `roles` | IDs de rol crudos | `GUILD_MEMBER_UPDATE` |
| `is_booster` / `boosting_since` | `premium_since` de Discord | `GUILD_MEMBER_UPDATE` |
| `raw_member` (jsonb) | escotilla de escape para lo que todavía no tiene columna propia | — |

**Qué NO hace este bot:** no decide qué significa un rol para una card (¿ese ID es "moderador"? ¿shiny?), no calcula nada de producto. Eso vive en la web, que lee esta tabla como fuente de verdad y aplica su propia lógica. El contrato entre los dos repos es la tabla — nada de código compartido (ver `sql/0001_init.sql`).

---

## Intents, permisos y por qué (leer antes de tocar `build_intents()`)

Pedimos exactamente lo que usamos, nada más — esto quedó definido así a propósito, no por default de una librería. Los eventos que de verdad nos importan cuelgan de dos intents, no de tres:

```
GUILD_MEMBERS
 ├── GUILD_MEMBER_ADD
 ├── GUILD_MEMBER_UPDATE
 └── GUILD_MEMBER_REMOVE

GUILD_MODERATION
 ├── GUILD_BAN_ADD
 └── GUILD_BAN_REMOVE
```

- **`GUILD_MEMBERS`** (**privilegiado** — hay que activar "Server Members Intent" a mano en el Developer Portal) — join/leave/update, incluyendo `roles` y `premium_since`.
- **`GUILD_MODERATION`** (no privilegiado) — ban add/remove.
- **`GUILDS`** (no privilegiado) — según la [doc de Discord](https://discord.com/developers/docs/events/gateway#gateway-intents), esto NO gatea los eventos de arriba — gatea `GUILD_CREATE`/`UPDATE`/`DELETE` y los de roles/canales. La prendemos igual, pero por una razón de `discord.py`, no de la API: sus parsers de member/ban (`state.py`) resuelven `guild = self._get_guild(id)` antes de dispatchear, y si ese guild no está en caché lo descartan en silencio — `on_member_join/update/remove/ban/unban` simplemente no se disparan. Ese caché solo se puebla vía `GUILD_CREATE`, que sí depende de `GUILDS`. Es decir: Discord mandaría el evento igual sin `GUILDS`, pero la librería lo tiraría antes de que nuestro handler lo vea. Confirmado leyendo el propio `state.py` de discord.py, no de memoria.
- **NO** `GUILD_PRESENCES` — no nos importa si alguien está online/jugando algo, y es privilegiado: pedirlo sería exactamente el tipo de sobre-alcance que hay que evitar.
- **NO** `MESSAGE_CONTENT` — el bot no lee mensajes, no tiene comandos.
- **NO** voice/invites/webhooks/emojis/etc.

**Permiso del bot: solo `Ban Members`.** No para banear a nadie — es lectura pura — pero `GET /guilds/{id}/bans` (necesario para la reconciliación) lo exige del lado de la API de Discord aunque el uso sea de solo lectura. Ningún otro permiso (nada de manage roles, manage server, kick, send messages).

---

## Reconciliación

Los eventos del Gateway cubren el caso en vivo. Si el bot estuvo caído, se pierden — por eso además corre una reconciliación completa **al arrancar** y después **cada `RECONCILE_INTERVAL_HOURS`** (default 6): trae la lista completa de miembros y de baneos por REST (paginado) y pisa el estado en la base con la verdad actual de Discord. Cualquier drift se corrige solo, sin intervención manual.

---

## Setup

### 1. Discord Developer Portal

Se puede reusar la Application que ya existe para el bot de eventos de la web, o crear una nueva — recomendado crear una **separada**, ya que este es un repo/servicio independiente y así un secreto comprometido de un lado no afecta al otro.

1. https://discord.com/developers/applications → *New Application* (o la que ya exista).
2. **Bot** → activar **Server Members Intent** (privilegiado — sin esto el bot arranca pero no recibe nada útil).
3. **Bot** → *Reset Token* → copiar (va en `DISCORD_BOT_TOKEN`).
4. **OAuth2 → URL Generator**: scope `bot`, permiso **Ban Members** únicamente → abrir el link generado e invitar al bot al servidor de PURG4TORY.

### 2. Supabase

1. Correr `sql/0001_init.sql` en el SQL Editor del proyecto (crea `discord_members` y `sync_meta`).
2. Project Settings → Database → Connection string → **URI**, puerto **5432** (directo, no el pooler 6543) → `DATABASE_URL`.
3. Correr `sql/0002_web_read_role.sql` (reemplazando la contraseña) — crea el rol de solo lectura que usa `pagina-web-purgatory` para consultar `discord_members` sin poder escribirlo nunca. Ese connection string es para el otro repo, no para este bot.

### 3. Local

```bash
cp .env.example .env   # completar los 3 valores
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m purgatory_sync.main
```

### 4. Railway

Nuevo proyecto → Deploy from GitHub repo → este repo. Es un **worker**, no un servicio web: no hace falta asignarle dominio ni puerto. `railway.toml` ya define el `startCommand`. Cargar las mismas variables de `.env.example` en Railway → Variables.

---

## Por qué estas decisiones técnicas

- **`discord.Client`, no `commands.Bot`** — no hay comandos de usuario, no tiene sentido cargar ese framework.
- **`asyncpg` directo, no `supabase-py`** — es un worker de confianza con credenciales propias; ir por la capa PostgREST sería una dependencia y un salto de red de más. Conexión directa (5432), no el pooler PgBouncer (6543): asyncpg usa prepared statements que no conviven bien con el modo transacción del pooler, y acá sobra con un pool chico (`min=1, max=3`) porque es un solo proceso siempre vivo, no serverless.
- **`chunk_guilds_at_startup=False`** — la reconciliación propia (REST, paginada, escribe directo a la base) reemplaza el chunking automático de discord.py.
- **Sin framework de comandos, sin caché de mensajes (`max_messages=None`)** — cada dependencia/feature de más es RAM y CPU de más en un worker que tiene que vivir dentro de un presupuesto de Railway muy chico.

---

## Estructura

```
purgatory_sync/
├── main.py       # entrypoint — Client, intents, wiring
├── config.py     # variables de entorno
├── db.py         # todas las queries — único lugar que toca Postgres
├── models.py     # discord.Member → dict que espera db.py
├── events.py     # handlers del Gateway (join/remove/update/ban/unban)
└── reconcile.py  # reconciliación al arrancar + periódica
sql/
└── 0001_init.sql # el contrato de datos compartido con la web
```
