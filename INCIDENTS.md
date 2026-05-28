# Incidentes — registro de pérdidas de data y bugs mayores

## 2026-05-28: Pérdida de collab de Arantxa durante migración a Turso

### Resumen
Lucy creó una collab para `arantxa.quintero` desde Streamlit Cloud. La data se perdió cuando se hizo la migración a Turso porque vivía en el filesystem efímero del container de Streamlit Cloud, no en la SQLite local de la Mac (que era la fuente que se migró).

### Secuencia
1. **Antes del 28 de mayo**: Lucy crea la collab en Streamlit Cloud (Collabs → Crear nueva). Se guarda en el SQLite del container.
2. **2026-05-28 mañana**: yo (Claude) corrí `migrate_to_turso.py` contra `data/felyfit_kol.db` de la Mac — encontré `collabs: 0 filas` y reporté la migración como completa.
3. **2026-05-28 ~16:00**: agregué TURSO_DATABASE_URL + TURSO_AUTH_TOKEN a los Secrets de Streamlit Cloud. El container reinició con filesystem limpio. La SQLite del container vieja quedó descartada — su data NO se migró.

### Data perdida
Una entrada en la tabla `collabs` con `handle = 'arantxa.quintero'`. Detalles exactos desconocidos (Lucy debe recrearla).

### Data preservada (no se perdió)
- Candidata `arantxa.quintero` (en `candidates` table) ✅
- 3 entradas en `lookup_history` para Arantxa (los Stalker analyses del 19 de mayo) ✅

### Causa raíz
Asumí que la única fuente de data era la SQLite local de la Mac. No consideré que Streamlit Cloud podía tener data nueva (escrita en su filesystem efímero) entre la última actualización de la Mac y mi migración.

### Mitigación a futuro
Ahora con Turso, este problema YA NO PUEDE PASAR — toda la data va a Turso (que es persistente cloud). Streamlit Cloud, GitHub Actions y la Mac local todos escriben/leen la misma DB. Cuando Lucy recree la collab, va a quedar segura en Turso.

### Acción
Lucy recreará la collab manualmente. El record de Arantxa como candidata + sus lookups en Stalker siguen intactos.

---

*Si pasa algo similar en el futuro, agregar entrada aquí con misma estructura.*
