# Historias de Usuario y Requisitos Funcionales — Core Banco Andino

> Convención: **HU** = Historia de Usuario, **RF** = Requisito Funcional.
> Estado: ✅ implementado · 🟡 parcial · ⬜ pendiente.

---

## ÉPICA 1 — Otorgamiento de Créditos (MPR-003-CRE)  [✅]

### HU-01 — Solicitar crédito (cliente vía Homebanking)  ✅
> Como **cliente**, quiero solicitar un crédito desde el portal, para no ir a la agencia.
- RF-01.1 El cliente autenticado envía monto, plazo, tipo (ME/PE/CO), actividad, ingreso. ✅
- RF-01.2 El sistema crea la solicitud en estado "En Evaluación". ✅
- RF-01.3 Si el cliente no es sujeto de crédito, se rechaza con motivo (HTTP 422). ✅

### HU-02 — Pre-scoring y evaluación de riesgo  ✅
> Como **asesor**, quiero un pre-scoring automático, para priorizar la evaluación.
- RF-02.1 Calcular score (capacidad, historial, sector, plazo) y decisión. ✅
- RF-02.2 Calcular RDS (3 ratios Art.13) con semáforo apetito/tolerancia. ✅
- RF-02.3 Validar elegibilidad (sujeto de crédito, Política 2.3.A). ✅

### HU-03 — Registrar ingresos y evaluación  ✅
> Como **asesor**, quiero registrar la fuente de ingreso y la evaluación del cliente.
- RF-03.1 Registrar ingreso (negocio/boleta/RxH) → fclientefuenteingreso. ✅
- RF-03.2 Registrar evaluación ME (activos) o CO (capacidad de pago). ✅

### HU-04 — Ruta de aprobación por monto  ✅
> Como **sistema**, debo derivar la solicitud al nivel correcto (Art. 30/34).
- RF-04.1 Determinar nivel por monto (dnivelaprobacion, 7 niveles). ✅
- RF-04.2 Determinar si requiere opinión Admin/Jefe Regional/Riesgos. ✅

### HU-05 — Comité y resolución  ✅
> Como **comité**, quiero aprobar/denegar y dejar registro.
- RF-05.1 Enviar a comité (estado En Comité). ✅
- RF-05.2 Resolver: Aprobado / Denegado temporal / Denegado definitivo. ✅
- RF-05.3 Regla dura: opinión Riesgos desfavorable ⇒ ningún comité aprueba. ✅

### HU-06 — Desembolso  ✅
> Como **comité/operaciones**, quiero desembolsar y que el cliente lo vea en su portal.
- RF-06.1 Crear cuenta de crédito + movimiento de desembolso. ✅
- RF-06.2 El desembolso aparece en los movimientos del homebanking. ✅
- RF-06.3 Generar cronograma de pagos referencial. ✅

---

## ÉPICA 2 — Homebanking (Caja Virtual)  [🟡 datos ✅ / endpoints en core, backend dedicado por construir]

### HU-07 — Login del cliente  ✅ (en core /hb)
- RF-07.1 Autenticación username+password (bcrypt), token tipo "cliente". ✅
- RF-07.2 Bloqueo tras N intentos fallidos. 🟡 (modelado, validar)

### HU-08 — Consultar cuentas y movimientos  🟡
> Como **cliente**, quiero ver mis cuentas de ahorro/crédito y movimientos.
- RF-08.1 Listar cuentas de ahorro con saldo. 🟡 (datos ✅, endpoint en backend HB)
- RF-08.2 Listar créditos con saldo y cuotas. ✅ (/hb/mis-creditos)
- RF-08.3 Ver movimientos (desembolsos, pagos). ✅ (/hb/movimientos)

### HU-09 — Pagar cuota desde el portal  ✅
- RF-09.1 Pagar la próxima cuota pendiente de un crédito. ✅
- RF-09.2 Registrar el pago como movimiento (canal App). ✅

### HU-10 — Transferencias propias  ⬜ (en prompt del backend HB)

---

## ÉPICA 3 — Gestión / Dashboard  [✅]

### HU-11 — Dashboard institucional  ✅
- RF-11.1 KPIs de cartera (total, vigente, vencida, ratio mora). ✅
- RF-11.2 Productividad de asesores vs metas. ✅
- RF-11.3 Desembolsos por mes/año/oficina/zona. ✅

### HU-12 — Bandeja de solicitudes  ✅
- RF-12.1 Listar con filtros (estado, búsqueda, rango de fechas). ✅
- RF-12.2 Contadores por estado (resumen). ✅

### HU-13 — Mi Cartera (asesor)  ✅
- RF-13.1 El asesor ve su cartera automáticamente (pkasesor del token). ✅

---

## ÉPICA 4 — Recuperaciones / Mora (MPR Recuperación)  [⬜ NUEVO — propuesto]

### HU-14 — Consultar cartera en mora  ⬜
> Como **gestor/administrador**, quiero ver los créditos morosos por banda.
- RF-14.1 Listar cartera por banda: preventiva(-1..2), temprana(7..30),
  tardía(31+), judicial(106/121/76 según tipo), castigado(>180). ⬜
- RF-14.2 KPIs de mora por agencia/asesor. ⬜
> Soporte BD: ✅ diasatrasocredito, flags, montos moratorios ya existen.

### HU-15 — Registrar gestión de cobranza  ⬜
> Como **gestor de cobranza**, quiero registrar las acciones (SMS, llamada, visita).
- RF-15.1 Registrar acción: tipo, fecha, gestor, resultado, compromiso de pago. ⬜
- RF-15.2 Listar el historial de gestiones de un crédito. ⬜
- RF-15.3 Agenda de gestiones pendientes del gestor. ⬜
> Soporte BD: ⬜ requiere tabla nueva **fgestioncobranza**.

### HU-16 — Transiciones de estado de cobranza  ⬜
> Como **funcionario de recuperaciones**, quiero escalar el crédito.
- RF-16.1 Pasar a Cobranza Judicial (flagjudicial, fechaingresojudicial). ⬜
- RF-16.2 Castigar crédito >180 días (flagcastigado). ⬜
- RF-16.3 Cada transición con regla de días + permiso de rol. ⬜
> Soporte BD: ✅ campos existen; ⬜ falta lógica/endpoints.

### HU-17 — Mora preventiva automática  ⬜
> Como **sistema**, quiero notificar (SMS/llamada) antes y al inicio del atraso.
- RF-17.1 Identificar créditos -1..2 días y generar recordatorios. ⬜

---

## Matriz de permisos por rol (épica Recuperaciones — propuesta)
| Acción | Roles |
|---|---|
| Consultar mora | asesor, administrador, riesgos, gerencia |
| Registrar gestión (SMS/llamada) | asesor, gestor_cobranza |
| Registrar visita | gestor_cobranza, administrador |
| Pasar a judicial | funcionario_recuperaciones, administrador |
| Castigar crédito | comite, gerencia |

---

## Definición de Hecho (DoD) — aplica a toda HU
1. Endpoint(s) con validación de rol.
2. Verificado contra datos reales (no asumido).
3. Sin romper integridad referencial.
4. Frontend consume y muestra el resultado.
5. Trazabilidad a la norma (artículo/proceso citado).
