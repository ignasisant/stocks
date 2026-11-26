# MyBrainStock — KPI semanal

Una hoja, cada lunes. Se rellena con `./scripts/kpi_week.sh` (lee los logs de
producción; mismos comandos que `stocks logs`). Una fila por semana, abajo.

## Qué se mira

| KPI | De dónde sale | Por qué |
|---|---|---|
| Vistas de landing | `funnel`, columna `views` | Alcance real, no seguidores |
| Entradas a la app | `funnel`, `entries` | Cuánta gente pasa de la landing a la app |
| Altas | `funnel`, `signups` | Cuentas nuevas |
| Primer import | `funnel`, `imports` | La activación: sin cartera no hay producto |
| Cuentas activas por día | `usage`, `users` | Retención de quien ya está dentro |
| Altas por fuente | `funnel`, tabla `by source` | Qué red o guía trae gente (utm de `docs/BRAND.md`) |
| Instalaciones en inicio | `installs` | Quien lo mete en la pantalla de inicio vuelve |

La métrica que manda es **altas con primer import**. Las vistas sin altas no
cuentan como avance.

## Línea base (19–26 nov 2026, antes de lanzar)

- 324 vistas de landing, 130 entradas a la app (40,1 %), 1 alta (0,8 % de las vistas), 1 primer import.
- Cuentas activas por día: entre 2 y 8.
- Fuentes con entradas: guías de la web (`guide-forms-720-721`, `guide-revolut-tax-return`, `guide-dividends-and-with…`). Las redes aún no traen nada.

## Registro semanal

| Semana | Vistas | Entradas | Altas | Primer import | Cuentas activas (máx. día) | Fuente que más trae | Nota |
|---|---|---|---|---|---|---|---|
| 19–26 nov | 324 | 130 | 1 | 1 | 8 | guías web | línea base |
