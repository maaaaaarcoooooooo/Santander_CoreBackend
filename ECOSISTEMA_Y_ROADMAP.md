# Estado Global del Ecosistema + Roadmap (Recuperaciones / Mora)

## 1. Mapa del ecosistema (4 proyectos + BD compartida)

```
                         ┌──────────────────────────────┐
                         │  PostgreSQL: bd_core_financiero │  (80 tablas, datos recalibrados)
                         └──────────────┬───────────────┘
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
   ┌──────────▼──────────┐   ┌──────────▼──────────┐   ┌──────────▼──────────┐
   │ BACKEND CORE  :8001 │   │ BACKEND HB   :8002  │   │  (comparten la BD)  │
   │ FastAPI             │   │ FastAPI (portal     │   │                     │
   │ scoring, solicitud, │   │ cliente)            │   │                     │
   │ comité, desembolso, │   │ login, movimientos, │   │                     │
   │ dashboard, bandeja  │   │ pagar, solicitar    │   │                     │
   └──────────┬──────────┘   └──────────┬──────────┘   └─────────────────────┘
              │                         │
   ┌──────────▼──────────┐   ┌──────────▼──────────┐
   │ FRONT CORE   :5173  │   │ FRONT HB     :5174  │
   │ personal del banco  │   │ portal del cliente  │
   │ (asesor/comité/...) │   │ (Caja Virtual)      │
   └─────────────────────┘   └─────────────────────┘
```

## 2. Estado por proyecto

| Proyecto | Estado | Detalle |
|---|---|---|
| **Backend Core (8001)** | ✅ Operativo | Flujo MPR-003-CRE completo + dashboard + bandeja + desembolso + productos dinámicos |
| **Front Core (5173)** | ✅ Alineado | Consume todos los endpoints; pendiente menor: tipos dinámicos vía /creditos/productos |
| **Backend HB (8002)** | 🟡 Por construir | Prompt entregado (PROMPT_BACKEND_HOMEBANKING.md). Datos HB ya poblados en la BD |
| **Front HB (5174)** | 🟡 Por construir | Prompt entregado (portal del cliente) |
| **BD** | ✅ Recalibrada | 2 productos (Empresarial/Consumo), mora realista ~13%, datos SGN |

## 3. Lo construido en el Core (resumen)

- **Otorgamiento (MPR-003-CRE):** solicitud → scoring → RDS → elegibilidad → ruta por monto →
  opiniones → comité → resolución → desembolso → cronograma.
- **Homebanking (datos + endpoints /hb):** login cliente, movimientos, solicitar, pagar.
- **Dashboard:** KPIs, mora, productividad, desembolsos por oficina/zona.
- **Bandeja:** listado con filtros (estado/búsqueda/fechas) + resumen/KPIs.
- **Roles reales:** dpersonalcargo (cargo) + dpersonalasesor (asesor) → token JWT.

---

## 4. NUEVO: Recuperaciones / Mora (MPR Recuperación del Crédito)

### 4.1 ¿La BD lo soporta? — Parcialmente (verificado)

**SÍ existe (en fagcuentacredito):**
- `diasatrasocredito`, `montosaldovencido`, `montosaldomoratorio`, `tasainteresmoratoria`
- `flagjudicial`, `flagcastigado`, `fechaingresojudicial`, `nrodiasatrasoinicio`
- Carteras por condición: car_vig / car_ven / car_ref / car_rep / car_jud / car_cas

**Estados de cobranza (destadocredito):**
- 01 Vigente · 02 Vencido · 03 En Cobranza Judicial · 07 Castigado · etc.

**NO existe (habría que crear):**
- Tabla de **acciones de cobranza** (gestiones: SMS, llamada, visita, fecha, gestor, resultado).
- Tabla de **asignación gestor↔cartera** de mora.
- Tabla de **compromisos de pago**.

### 4.2 Bandas de mora del proceso (del PDF) vs. datos actuales

| Subproceso (PDF) | Días de mora | Créditos hoy en esa banda |
|---|---|---|
| P01 Mora preventiva | -1 a 2 | (al día: 895) |
| P02 Mora temprana | 7 a 30 | 46 (9-30) |
| P03 Mora tardía | desde 31 | 21 (31-120) |
| P04 Cobranza judicial | 106/121/76 según tipo | 11 (121-180) |
| P06 Castigados | > 180 | 127 |

> Los datos recalibrados YA distribuyen la cartera en estas bandas de forma realista.
> Falta la CAPA DE GESTIÓN (registrar acciones de cobranza sobre esos créditos morosos).

### 4.3 Alcance propuesto para Recuperaciones (incremental, como el otorgamiento)

**Fase R1 — Consulta de mora (solo lectura, ya hay datos):**
- Endpoint: cartera en mora por banda (preventiva/temprana/tardía/judicial/castigado).
- Dashboard de mora: ratio por agencia/asesor, evolución.

**Fase R2 — Gestión de cobranza (requiere 1 tabla nueva):**
- Crear `fgestioncobranza` (pkcredito, fecha, tipo_accion[SMS|LLAMADA|VISITA|CARTA],
  gestor, resultado, compromiso_pago, monto_comprometido).
- Endpoints: registrar gestión, listar gestiones de un crédito, agenda del gestor.

**Fase R3 — Acciones de estado (transiciones):**
- Pasar crédito a Cobranza Judicial (flagjudicial, fechaingresojudicial).
- Castigar crédito (>180 días, flagcastigado).
- Cada transición con su regla y permiso de rol.

---

## 5. Roles para Recuperaciones (a mapear en cfg_roles)
- **gestor_cobranza** / **asesor** (mora temprana: SMS/llamada)
- **administrador** (mora tardía, decide acciones)
- **funcionario_recuperaciones** (judicial)
- **comite** / **gerencia** (castigo, transferencia de cartera)
