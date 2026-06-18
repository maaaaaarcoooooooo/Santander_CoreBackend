# Análisis — Simulación del flujo Homebanking ⇄ Core (Otorgamiento de Créditos)

> Objetivo: cliente solicita crédito desde Homebanking → asesor evalúa en el Core
> (recolecta ingresos / EE.FF. / boletas según tipo) → manual de niveles → comité →
> aprobación → desembolso al Homebanking → cliente paga desde Homebanking.
> **Alcance: solo MICROEMPRESA (ME) y CONSUMO (CO).** Nada más.

---

## 1. Hallazgo clave: NO hay que llenar 77 tablas

Las 77 tablas se dividen en 3 grupos. Solo el grupo C necesita generación nueva:

- **A) Catálogos (ya poblados, no se tocan):** dtipocredito, dproducto, dcalificacioncrediticia,
  dnivelaprobacion, dagencia, dasesor, dmoneda, dsectoreconomico, dactividadeconomica,
  destadocredito, dsolicitudestado, etc. → **~45 tablas, YA listas.**
- **B) Datos transaccionales existentes (coherentes, se reutilizan):** dcliente, dcuentacredito,
  fagcuentacredito, dcuentaahorro, etc. → ya auditados y consistentes.
- **C) Tablas del flujo que están VACÍAS y hay que poblar (el verdadero trabajo):**
  - `usuarios_homebanking` — credenciales del cliente para el portal
  - `foperaciones` — movimientos del homebanking (pagos, transferencias, desembolso)
  - `fclientefuenteingreso` — ingresos del cliente (boletas/RxH/negocio)
  - `devaluacion` — cabecera de la evaluación crediticia
  - `fevalconsumo` — detalle de evaluación para crédito de CONSUMO
  - `fevalmicroactivo` — detalle de evaluación para crédito MICROEMPRESA (activos)
  - `fevalempresarial` — (opcional, fuera de alcance ME/CO básico)

> **Conclusión: el trabajo real son ~6 tablas, no 77.** El resto ya existe.

---

## 2. La BD YA tiene las estructuras correctas para tu flujo

Verificado columna por columna:

### Homebanking
- `usuarios_homebanking (pkcliente, username, password_hash, activo, bloqueado, ...)`
  → login del cliente al portal. **Estructura lista, tabla vacía.**
- `foperaciones (pkcuentacredito, pkcuentaahorro, pktipooperacion, pkmediopago,
   pkcanaltransaccional, montooperacion, fechahoraoperacion, ...)`
  → registra pagos, transferencias y el desembolso. Tiene `pkcanaltransaccional`
  (para marcar "Homebanking" vs "ventanilla") y enlaza a cuenta crédito y ahorro.
  **Es exactamente el "estado de cuenta / movimientos" que el asesor vería.**

### Evaluación crediticia (lo que el asesor recolecta y registra)
- `fclientefuenteingreso (pkcliente, tipofuenteingreso, montofuenteingreso,
   codempleador, nombreempresa, condicioncontrato, ...)`
  → **fuentes de ingreso del cliente** (dependiente=boleta, independiente=RxH, negocio).
- `devaluacion (codsolicitud, nroevaluacion, valorexcedentecredito, tipoevaluacion)`
  → **cabecera** de la evaluación, ligada a la solicitud (`codsolicitud`). ¡Ya tiene el
  vínculo con dsolicitud que necesitábamos!
- `fevalconsumo (..., monto, montogastofamiliar, fortaleza/debilidad/gestion, ...)`
  → detalle para CONSUMO (ingresos vs gastos familiares → capacidad de pago).
- `fevalmicroactivo (montoactivodisponible, montoactivoinventario, montoactivofijo,
   montogastofamiliar)`
  → detalle para MICROEMPRESA (balance simplificado del negocio).

> Esto confirma que el modelo fue diseñado para el flujo MPR-003-CRE. Solo está vacío.

---

## 3. Mapeo del flujo → tablas (qué se inserta en cada paso)

| Paso del flujo | Acción | Tabla(s) que se escribe(n) |
|---|---|---|
| **0. Cliente tiene portal** | usuario homebanking creado | `usuarios_homebanking` |
| **1. Cliente ve sus movimientos** | historial de pagos/transferencias | lee `foperaciones` |
| **2. Cliente solicita crédito (HB)** | crea solicitud En Evaluación | `dsolicitud` (ya implementado) |
| **3. Asesor recolecta ingresos** | registra fuentes de ingreso | `fclientefuenteingreso` |
| **4. Asesor evalúa** | cabecera + detalle según tipo | `devaluacion` + (`fevalconsumo` \| `fevalmicroactivo`) |
| **5. Manual de niveles** | ruta por monto (Art. 30/34) | ya implementado (`determinar_ruta`) |
| **6. Comité aprueba** | resolución | `dsolicitud` estado→Aprobado (ya implementado) |
| **7. Desembolso** | crea cuenta crédito + movimiento | `dcuentacredito`, `fagcuentacredito`, `foperaciones` (tipo desembolso) |
| **8. Cliente paga (HB)** | registra pago de cuota | `foperaciones` (tipo pago) + actualiza saldo |

---

## 4. Estrategia recomendada (NO scripts gigantes)

En vez de "scripts de INSERT para 77 tablas" (frágil, enorme), propongo **2 generadores
Python parametrizados** que ya conocen las FKs y catálogos:

1. **`seed_homebanking.py`** — crea usuarios de portal para N clientes existentes +
   genera `foperaciones` histórico (pagos de cuotas, transferencias) del 2025 para esos clientes.
2. **`seed_evaluaciones.py`** — para las solicitudes existentes (o nuevas), genera
   `fclientefuenteingreso` + `devaluacion` + detalle ME/CO coherente con el monto y el scoring.

Cada generador:
- Lee los catálogos reales (no hardcodea PKs).
- Respeta la lógica: ingresos ≥ cuota×ratio, activos coherentes con el monto, etc.
- Es idempotente (no duplica si se corre dos veces).

> Ventaja: ~2 scripts mantenibles vs. miles de líneas de INSERT manual. Y los datos
> quedan **conversando** entre homebanking ↔ core (mismas cuentas, mismos clientes).

---

## 5. Lo que falta DECIDIR antes de generar

1. **¿Cuántos clientes con homebanking?** (ej. 50 clientes con portal + movimientos).
2. **¿Nuevas solicitudes de demo o evaluar las existentes?** (recomiendo crear ~10
   solicitudes nuevas ME/CO desde "cero" para mostrar el flujo completo paso a paso).
3. **¿El backend necesita endpoints nuevos?** El flujo de evaluación (paso 3-4) y
   homebanking (paso 1, 7, 8) NO tienen endpoints aún. Hoy existe: solicitud, opinión,
   comité, resolver, cronograma. Faltarían: login homebanking, movimientos, registrar
   ingresos, registrar evaluación, desembolso, pago.

---

## 6. Brecha de endpoints (para que el flujo sea ejecutable, no solo datos)

| Necesidad | ¿Existe endpoint? |
|---|---|
| Cliente login portal | ❌ falta `POST /hb/login` |
| Cliente ver movimientos | ❌ falta `GET /hb/movimientos` |
| Cliente solicitar crédito | ✅ `POST /creditos/solicitudes` |
| Asesor registrar ingresos | ❌ falta `POST /creditos/solicitudes/{cod}/ingresos` |
| Asesor registrar evaluación | ❌ falta `POST /creditos/solicitudes/{cod}/evaluacion` |
| Comité/resolución | ✅ ya existe |
| Desembolsar | ❌ falta `POST /creditos/solicitudes/{cod}/desembolsar` |
| Cliente pagar cuota | ❌ falta `POST /hb/pagar` |

> Decisión: ¿generamos **solo datos** (para que el dashboard/bandeja se vean llenos) o
> también los **endpoints** que faltan (para que el flujo sea interactivo de verdad)?
