-- ═══════════════════════════════════════════════════════════
-- Rol de solo lectura para la web (pagina-web-purgatory)
-- ───────────────────────────────────────────────────────────
-- El bot sigue usando el rol dueño de la base (el que ya tenés en
-- DATABASE_URL de purgatory-sync) para escribir discord_members.
-- La web usa ESTE rol nuevo, que solo puede leer esa tabla — nunca
-- insertar, actualizar ni borrar. Así, aunque hubiera un bug o una
-- inyección SQL del lado de la web, estructuralmente no hay forma de
-- que toque el estado verificado de Discord: el permiso no está.
--
-- Correr en el SQL Editor de Supabase, reemplazando la contraseña.
-- ═══════════════════════════════════════════════════════════

create role web_app with login password 'CAMBIAR_ESTA_CONTRASEÑA';

grant connect on database postgres to web_app;
grant usage on schema public to web_app;
grant select on discord_members to web_app;
-- sync_meta es operativo del bot — la web no necesita leerlo.

-- Cuando exista la tabla de cards/almas (Fase 6 de la web), a este
-- mismo rol se le da select+insert+update+delete SOLO sobre esa tabla.
-- discord_members se queda de solo lectura para siempre desde este rol.

-- Connection string resultante para DATABASE_URL de la web (puerto
-- 6543, el pooler — la web corre en funciones serverless de Vercel,
-- muchas conexiones cortas, para eso está el pooler):
--   postgresql://web_app:<password>@<host>:6543/postgres
