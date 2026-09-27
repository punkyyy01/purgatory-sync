-- ═══════════════════════════════════════════════════════════
-- purgatory-sync — contrato de datos compartido con la web
-- ───────────────────────────────────────────────────────────
-- Esta es la ÚNICA superficie que este bot comparte con la app web
-- (pagina-web-purgatory / Astro). El bot es el único que escribe acá;
-- la web solo lee, para derivar propiedades VERIFICADAS de las cards
-- (booster → shiny, expulsado → void, etc. — esa lógica de producto
-- vive del lado de la web, no acá).
--
-- discord_members guarda el estado ACTUAL de Discord por usuario,
-- pisado en cada evento del Gateway y, como red de seguridad, en cada
-- reconciliación completa. No es un log de eventos — es una foto viva.
-- ═══════════════════════════════════════════════════════════

create table if not exists discord_members (
  discord_id      bigint primary key,

  -- Identidad verificada — el usuario no puede editar esto desde la web.
  username        text not null,
  global_name     text,
  avatar_url      text,

  -- Pertenencia al servidor.
  joined_at       timestamptz,
  left_at         timestamptz,
  is_member       boolean not null default true,

  -- Baneos. No se borra la fila al banear — se marca, igual que el
  -- resto del sitio ("el Infierno no olvida").
  is_banned       boolean not null default false,
  banned_at       timestamptz,
  unbanned_at     timestamptz,

  -- Roles tal cual los tiene Discord — IDs crudos. Qué rol "significa"
  -- algo para una card (moderador, etc.) lo decide la web, no el bot.
  roles           bigint[] not null default '{}',

  -- Boost de servidor. boosting_since espeja 1:1 el campo premium_since
  -- de Discord (null = no está boosteando).
  is_booster      boolean not null default false,
  boosting_since  timestamptz,

  -- Escotilla de escape para lo que todavía no tiene columna propia
  -- (avatar decoration, timeout activo, etc.) — evita una migración
  -- por cada campo nuevo que a futuro quiera usar una card.
  raw_member      jsonb,

  synced_at       timestamptz not null default now(),
  created_at      timestamptz not null default now()
);

create index if not exists discord_members_is_member_idx  on discord_members (is_member);
create index if not exists discord_members_is_banned_idx  on discord_members (is_banned);
create index if not exists discord_members_is_booster_idx on discord_members (is_booster);
create index if not exists discord_members_roles_idx      on discord_members using gin (roles);

-- Una sola fila — metadata operativa de la última sincronización, útil
-- para detectar si el bot dejó de correr (alertas, debug), sin tener
-- que loguear cada evento individual.
create table if not exists sync_meta (
  id                  boolean primary key default true check (id),
  last_event_at       timestamptz,
  last_reconciled_at  timestamptz,
  last_reconcile_ms   integer,
  guild_member_count  integer
);
insert into sync_meta (id) values (true) on conflict (id) do nothing;
