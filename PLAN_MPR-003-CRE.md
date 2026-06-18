# Plan de implementación — MPR-003-CRE Otorgamiento de Créditos (V24)

> Estado: PLAN (sin código todavía). Decisión de persistencia: **reutilizar `dsolicitud` + catálogos existentes**.
> Base: Caja Huancayo MPR-003-CRE V24 (vigente 02/01/2019) + esquema real de `bd_core_financiero`.

---

## 1. Resumen ejecutivo

El backend actual implementa **solo el motor de pre-scoring** (paso 4 / Anexo 02) y consultas de
cartera. El procedimiento es un **workflow de ~56 actividades** con cadena de aprobación por monto,
opinión de Gerencia de Riesgos y resolución de Comité.

**Buena noticia:** la BD ya tiene casi todo el modelo necesario (`dsolicitud`, `dnivelaprobacion`,
`dsolicitudestado`, `dcomite`, `devaluacion`, etc.), así que NO hay que inventar tablas; hay que
**escribir la capa de servicios** que las orqueste.

Alcance de esta primera etapa (acordado): **Solicitud + cadena de aprobación** (núcleo del Sección I
del procedimiento: actividades 13 → 16 → 22 → 41 → 43). Las secciones II–V (seguimiento, COFIDE,
tasaciones) y los desembolsos (MPR-010) quedan fuera por ahora.

---

## 2. Mapeo Procedimiento ⇄ Código ⇄ Base de datos

| Actividad MPR-003-CRE | ¿Implementado hoy? | Dónde irá | Tabla/Catálogo BD |
|---|---|---|---|
| 4 — Pre-scoring (referencia de riesgo, variables de mayor incidencia) | ✅ Sí | `ctl_scoring.calcular_score` | (cálculo en memoria; persistir en `devaluacion`) |
| 13 — Genera la solicitud en el sistema | ❌ No (`ctl_creditos` vacío) | **NUEVO** `ctl_creditos.crear_solicitud` | `dsolicitud` (estado 01 En Evaluación) |
| 13 (nota) — alerta "denegación definitiva" bloquea registro | ❌ No | regla en `crear_solicitud` | (marca de cliente — definir) |
| 14/15 — Pre-deniega / deniega (temporal o definitiva) | ❌ No | **NUEVO** `denegar_solicitud` | `dsolicitud.pksolicitudestado` = 03 |
| 16 — Registra propuesta (tipo, producto, modalidad, desembolso) | ❌ No | **NUEVO** `registrar_propuesta` | `dsolicitud` (pkproducto, pkmodalidad, pkcanaldesembolso) |
| 17 — Evalúa RDS (sobreendeudamiento, MPR-014-CTR) | ❌ No | placeholder/servicio | (fuera de alcance fino; dejar hook) |
| 22 — Ruteo por nivel de endeudamiento/monto | ❌ No | **NUEVO** `determinar_nivel_aprobacion` | `dnivelaprobacion` (montominimo/maximo) |
| 23-24 — Opinión viabilidad Administrador (Formato 03, ≥100k) | ❌ No | **NUEVO** registro de opinión | `dsolicitud` + tabla opinión (ver §4) |
| 25-26 — Opinión Jefe Neg. Regional (Formato 04, ≥300k) | ❌ No | idem | idem |
| 27-36 — Opinión Gerencia de Riesgos + ciclo observaciones | ❌ No | **NUEVO** estados intermedios | `dsolicitud` estado 06 / situación |
| 41 — Pre-aprueba y presenta a Comité | ❌ No | **NUEVO** `enviar_a_comite` | `dsolicitud.pksolicitudestado` = 06 En Comité; `pkcomite` |
| 42-43 — Resolución del Comité (aprobado/deneg. temporal/definitivo) | ⚠️ Parcial (decisión automática del scoring) | **NUEVO** `resolver_comite` | `dsolicitud.pksolicitudestado` = 02/03 |
| 45 — Genera plan de pagos referencial | ⚠️ Parcial (scoring calcula cuota) | **NUEVO** `generar_cronograma` | `fplanpagomes` (ya consultable) |
| 46-48 — Seguros / contratos / desembolso | ❌ No (otros MPR) | fuera de alcance | — |
| II–V — Seguimiento, COFIDE, tasaciones, SUNARP | ❌ No | fuera de alcance | — |

---

## 3. Umbrales reales (extraídos del procedimiento y de la BD)

### 3.1 Niveles de aprobación por monto — `dnivelaprobacion` (ya cargada)
| Nivel | Rol | Rango (S/) |
|---|---|---|
| N1 | Asesor de Negocios | 0 – 10 000 |
| N2 | Administrador de Agencia | 10 001 – 50 000 |
| N3 | Jefe de Negocios Regional | 50 001 – 150 000 |
| N4 | Comité de Créditos Agencia | 150 001 – 500 000 |
| N5 | Comité de Créditos Central | 500 001 – 1 500 000 |
| N6 | Directorio | > 1 500 000 |

### 3.2 Ruteo de opinión (actividad 22 del procedimiento)
- Endeudamiento global **< S/ 100 000** → directo a Comité (act. 41).
- **≥ S/ 100 000** → opinión de **Administrador** (Formato 03) → Gerencia de Riesgos.
- **≥ S/ 300 000** → además opinión de **Jefe de Negocios Regional** (Formato 04).
- ME/Consumo con **≥ S/ 50 000** y 3+ entidades → opinión de Gerencia de Riesgos.

### 3.3 Ruteo interno de Riesgos (actividad 32)
- ≤ 50k y > 15k → vuelve al asesor.
- ≤ 300k y > 50k → analista senior de riesgos.
- < 1 000 000 y > 300k → subjefe de riesgos.
- > 1 000 000 → gerente de riesgos.

> ⚠️ **Decisión pendiente:** el procedimiento rutea por **endeudamiento global en el sistema
> financiero** (dato de central de riesgos que NO está en la BD). Propuesta: en esta etapa rutear por
> **monto solicitado** usando `dnivelaprobacion`, dejando un parámetro `endeudamiento_global` opcional
> para cuando exista la fuente. Confirmar con el usuario.

---

## 4. Cambios concretos de implementación

### 4.1 Modelos nuevos (SQLAlchemy) — sobre tablas existentes
- `mdl_solicitud.py` → mapea `dsolicitud`.
- `mdl_catalogos.py` → `dsolicitudestado`, `dsolicitudsituacion`, `dtipocredito`, `dproducto`,
  `dmodalidad`, `dnivelaprobacion`, `dcomite`, `dcalificacioncrediticia`.
- `mdl_evaluacion.py` → mapea `devaluacion` (hoy vacía) para guardar el resultado del scoring (act. 4).

### 4.2 Repositorio `rep_solicitudes.py` (NUEVO)
- `crear(...)`, `obtener(codsolicitud)`, `cambiar_estado(...)`, `listar_por_asesor(...)`.
- `siguiente_codsolicitud()` → genera `SOL-XXXXXXX` (continuar la serie `SOL0000001…`).
- `nivel_por_monto(monto)` → consulta `dnivelaprobacion`.

### 4.3 Controlador `ctl_creditos.py` (hoy VACÍO → llenar)
Orquesta el flujo de la Sección I:
1. `crear_solicitud(SolicitudIn)` → corre scoring (reusa `ctl_scoring`), persiste en `dsolicitud`
   estado **01**, guarda detalle en `devaluacion`. Aplica regla de "denegación definitiva".
2. `determinar_ruta(solicitud)` → usa §3.2 + `dnivelaprobacion` → devuelve nivel y si requiere
   opinión de Riesgos.
3. `registrar_opinion(codsolicitud, rol, favorable, comentario)` → Formatos 02/03/04.
4. `enviar_a_comite(codsolicitud)` → estado **06 En Comité**, asigna `pkcomite`.
5. `resolver(codsolicitud, decision, motivo)` → estado **02 Aprobado** / **03 Rechazado**.
6. `generar_cronograma(codsolicitud)` → plan de pagos referencial (act. 45).

### 4.4 Rutas nuevas en `rtr_creditos.py`
```
POST /creditos/solicitudes                 → crear (corre scoring + persiste)
GET  /creditos/solicitudes/{cod}           → detalle + estado + ruta de aprobación
POST /creditos/solicitudes/{cod}/opinion   → registrar opinión (admin / jefe reg / riesgos)
POST /creditos/solicitudes/{cod}/comite    → enviar a comité
POST /creditos/solicitudes/{cod}/resolver  → resolución (aprobado/denegado)
GET  /creditos/solicitudes/{cod}/cronograma→ plan de pagos referencial
```

### 4.5 Schemas `sch_creditos.py` (ampliar)
- Reusar `SolicitudIn` (ya existe).
- `SolicitudOut`, `RutaAprobacionOut`, `OpinionIn`, `ResolucionIn`.

---

## 5. Máquina de estados de la solicitud (alineada a `dsolicitudestado`)

```
[crear] → 01 En Evaluación
  ├─ (no califica) → 03 Rechazado (deneg. temporal/definitiva)   [act. 14/15]
  └─ (califica)    → registra propuesta [act.16] → evalúa ruta [act.22]
         ├─ < 100k → 06 En Comité [act.41]
         └─ ≥ 100k → opiniones (admin/jefe reg/riesgos) [act.23-36] → 06 En Comité
                       └─ riesgos desfavorable → 03 Rechazado [act.34]
  06 En Comité → resolución [act.42-43]
         ├─ Aprobado            → 02 Aprobado → cronograma [act.45]
         ├─ Denegado temporal   → 03 Rechazado (reconsiderable)
         └─ Denegado definitivo → 03 Rechazado (+ marca observada)
  02 Aprobado → (fuera de alcance: 04 Desembolsado vía MPR-010)
```

---

## 6. Orden de implementación sugerido

1. **Modelos + repositorio** de solicitud y catálogos (base, sin lógica).
2. **`crear_solicitud`** (scoring + persistencia en `dsolicitud`/`devaluacion`) + endpoint POST.
3. **Ruteo por monto** (`dnivelaprobacion`) + endpoint de consulta de ruta.
4. **Opiniones + envío a comité + resolución** (estados 06/02/03).
5. **Cronograma referencial** (act. 45).
6. Pruebas con un cliente real de la BD (extremo a extremo).

---

## 7. Decisiones tomadas (confirmadas con el usuario)

1. **Ruteo de aprobación** → **campo manual opcional `endeudamiento_global`** en la solicitud.
   Si el asesor lo deja vacío, se rutea por **monto solicitado** contra `dnivelaprobacion`.
2. **Permisos** → **validar el rol del token JWT** en los endpoints de opinión y resolución.
3. **Origen del rol** → **crear tabla puente `dpersonalcargo`** (`pkpersonal → pkcargopersonal`),
   ya que la BD tiene el catálogo `dcargopersonal` pero NINGÚN vínculo persona↔cargo.
   El login leerá el cargo real desde esta tabla y lo pondrá en el token.
4. **`codsolicitud`** → continuar la serie correlativa `SOL000XXXX`.
5. **"Denegación definitiva"** → pendiente de fuente de datos; por ahora se modela como motivo de
   rechazo manual (sin marca automática de cliente).

### Catálogo de cargos disponible (`dcargopersonal`)
| pk | cod | Cargo | Rol propuesto en token |
|---|---|---|---|
| 1 | G01 | Gerente Central | gerencia |
| 2 | G02 | Gerente de Área | gerencia |
| 3 | F01 | Jefe de Negocios Regional | jefe_regional |
| 4 | F02 | Administrador de Agencia | administrador |
| 5 | F03 | Jefe de Operaciones | operaciones |
| 6 | F04 | Jefe de Riesgos | riesgos |
| 7 | F05 | Funcionario de Créditos | comite |
| 8 | E01 | Asesor de Negocios | asesor |
| 10 | E03 | Analista de Créditos | analista |

### Matriz de permisos por endpoint
| Endpoint | Roles permitidos |
|---|---|
| `POST /creditos/solicitudes` | asesor, administrador |
| `POST .../opinion` (admin) | administrador |
| `POST .../opinion` (jefe reg) | jefe_regional |
| `POST .../opinion` (riesgos) | riesgos, analista |
| `POST .../comite` | asesor, administrador |
| `POST .../resolver` | comite, administrador, gerencia |
```
