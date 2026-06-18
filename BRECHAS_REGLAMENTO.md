# Análisis de brechas — Reglamento de Créditos V33 + Política V14 vs. lo implementado

> Insumos: R_CREDITOS V33 (vigente 29/11/2016) y P_CRÉDITOS V14 (vigente 14/03/2017), Caja Huancayo.
> Objetivo: listar lo que falta para que el backend refleje las REGLAS DE NEGOCIO reales del core,
> no solo el flujo (workflow) del MPR-003-CRE.

---

## 0. Hallazgo crítico: los umbrales que codifiqué NO coinciden con el Reglamento

En la primera etapa usé umbrales tomados del diagrama del procedimiento + la tabla `dnivelaprobacion`
de tu BD. El **Reglamento V33 (Art. 30)** define los niveles de aprobación REALES, y son distintos:

| Nivel | Responsable (Art. 30 V33) | Tope (Saldo capital + monto) |
|---|---|---|
| I  | Asesor de Negocios | Senior I: S/ 7 000 · Senior II: S/ 14 000 |
| II | Administrador | S/ 50 000 |
| III| Jefe de Negocios Regional | S/ 100 000 |
| IV | Jefe de Producto de Créditos | S/ 140 000 |
| V  | Sub Gerencia de Negocios | S/ 170 000 |
| VI | Gerencia de Negocios | S/ 210 000 |
| VII| Gerencia Mancomunada | hasta el límite legal |

> ⚠️ Mi tabla `dnivelaprobacion` actual (N1..N6) tiene rangos diferentes (0-10k, 10-50k, 50-150k,
> 150-500k, 500k-1.5M, >1.5M) y solo 6 niveles. El Reglamento define **7 niveles** con topes finos
> (140k, 170k, 210k) y el nivel I se subdivide en Senior I/II. **Acción:** realinear los datos de
> `dnivelaprobacion` (o una tabla de parámetros) a la tabla del Art. 30.

### Umbral de opinión de Gerencia de Riesgos (Art. 34 V33) — confirma y precisa lo que hice
La regla de ruteo a Riesgos que implementé es correcta en espíritu; el Art. 34 la fija exacta:
- Monto propuesto **≥ S/ 100 000** → opinión de Riesgos.
- Monto propuesto **≥ S/ 50 000** Y endeudamiento en **3+ entidades** (solo ME y Consumo) → Riesgos.
- Endeudamiento global **≥ 100k** (o ≥50k ME/Consumo con 3+ entidades) **y** propuesta **> S/ 15 000** → Riesgos.
- Hipotecario para vivienda **≥ S/ 100 000** → Riesgos.
- Regla dura (Art. 29.k): **opinión desfavorable de Riesgos ⇒ ningún Comité puede aprobar.** ✅ ya implementado.

### Opinión del Administrador / Jefe Regional (alineado a V33)
- **Administrador** emite opinión de viabilidad para propuestas **≥ S/ 100 000** (Art. 29.i). ✅ coincide.
- **Jefe de Negocios Regional** emite opinión (Formato 04) para **≥ S/ 300 000** (Art. 32). ✅ coincide.

---

## 1. Reglas de elegibilidad del cliente (Política V14, 2.3.A) — FALTA

El scoring actual no valida si el cliente es **sujeto de crédito**. La Política define:

**NO son sujetos de crédito (2.3.A.2):**
- Obligaciones vencidas o en cobranza judicial en el sistema financiero (incl. La Caja).
- Sometidos a junta de acreedores.
- Clasificación SBS Deficiente/Dudoso/Pérdida/castigado (titular, cónyuge, fiador, y para PJ:
  representantes y accionistas >5%).
- Quienes dispusieron de bienes dados en garantía antes.
- Insolventes en INDECOPI.

**Admisión excepcional con calificación ≠ Normal (2.3.A.3):**
- CPP → se puede otorgar con justificación, al día en el sistema financiero.
- Deficiente/Dudoso/Pérdida → requiere **opinión favorable de Gerencia de Riesgos** para desembolsar.
- Tope (Art. 36.p V33): no más del **20%** de acreencias en esas categorías, ni **>6 meses** consecutivos.

> **Acción:** función `es_sujeto_de_credito(cliente)` que consulte calificación (`dcalificacioncrediticia`
> ya está en BD: 0 Normal … 4 Pérdida) y bloquee/derive según corresponda.

---

## 2. Tipo de crédito por ENDEUDAMIENTO, no elegido a mano (Reglamento Art. 5) — FALTA

Hoy el `codtipocredito` lo manda el frontend. El Art. 5 define el tipo por **nivel de endeudamiento**
en el sistema financiero (sin hipotecarios):

| Tipo | Endeudamiento total SF |
|---|---|
| Microempresa (ME) | ≤ S/ 20 000 |
| Pequeña Empresa (PE) | > 20 000 y ≤ 300 000 |
| Mediana Empresa (MD) | > 300 000 (o PN > 300k) |
| Gran Empresa (GE) | ventas > 20M |
| Consumo (CO) | persona natural, ≤ 300 000 |
| Hipotecario (HI) | vivienda |

> **Acción:** función `clasificar_tipo_credito(endeudamiento, ventas, es_persona_juridica)` que sugiera
> el tipo correcto y advierta si el enviado no concuerda. Útil porque el ruteo y las coberturas dependen del tipo.

---

## 3. Capacidad de pago / RDS (Reglamento Art. 13 + Política 2.7) — PARCIAL

El scoring actual calcula un ratio cuota/ingreso simple. El Reglamento define **3 ratios formales**
con límites de apetito/tolerancia por tipo de crédito (Art. 13, tablas):

- **Cuota / Ingreso o Ventas** (apetito ME/PE ≤ 90%, Consumo ≤ 70% / hasta 35-40% por convenio).
- **Deuda Total / Excedente** (≤ 75 veces apetito, ≤ 200 tolerancia).
- **Cuota / Excedente** (≤ 85-95% según cliente nuevo/recurrente).
- **N.º de entidades**: apetito 4, tolerancia 6 (incluida La Caja).

Y **límites de número de créditos** (Art. 13): hasta 4 entidades → 2 créditos; 3 entidades → 3; 2 o solo
La Caja → 4 créditos vigentes.

> **Acción:** refactor del scoring a un módulo `svc_rds.py` que calcule los 3 ratios y el semáforo
> apetito/tolerancia. Requiere datos de centrales de riesgo (deuda externa) → entran por el campo
> `endeudamiento_global` que ya añadimos + nuevos campos opcionales (n.º entidades, cuotas SF).

---

## 4. Garantías y cobertura (Reglamento Cap. III, Art. 24-27) — FALTA (modela `dgarantia`)

El Reglamento define decenas de tipos de garantía (RPHIP, RPVEH, NRDOI, NRNOG, PEFIS…) con
**% de cobertura por cliente nuevo/recurrente** y topes. Tu BD ya tiene la tabla `dgarantia`.

- Edad mínima titular 18, máx 75 (nuevo) / 79 (recurrente); fiador máx 80 (Art. 15).
- Monto mínimo de crédito: **S/ 200** (Art. 15).
- Garantía real obligatoria para endeudamiento acumulado **> S/ 100 000** (Art. 27.H).

> **Acción (etapa posterior):** módulo de garantías que valide cobertura por tipo. Es grande; se puede
> diferir hasta tener el flujo central sólido.

---

## 5. Composición y operatividad del Comité (Reglamento Art. 29-30) — PARCIAL

Hoy "resolver" lo hace un usuario con rol `comite`. El Reglamento exige:
- Comité con **mínimo 3 integrantes** (2 en agencias chicas), mayoría simple, **sin abstenciones**.
- Cada integrante registra voto favorable/desfavorable (Art. 29.j) → **votación electrónica**.
- Responsable con voz, voto y **veto**.
- Resolución vigente **1 mes** (60 días si hipotecaria) (Art. 37) → expira y se rechaza.

> **Acción:** tabla de votos por solicitud (`app_voto_comite`) + estado de vigencia de la resolución.

---

## 6. Operaciones derivadas (Reglamento Título IV) — FUERA DE ALCANCE INICIAL

Ampliación (Art. 44), Refinanciación (Art. 46), Reestructuración (Art. 45), Reprogramación (Art. 47-48),
Fusión (Art. 49) — cada una con sus condiciones. Tu `dsolicitudsituacion` ya distingue
Nueva/Renovación/Ampliación/Refinanciamiento/Reestructuración, así que el modelo soporta esto.

---

## 7. Excepciones (Reglamento Título V + Política 2.8) — FALTA

Niveles de autorización de excepciones (Art. 51) y **límites de excepciones** por operación/cliente/
asesor/agencia (Política 2.8): apetito 2, tolerancia 3 por operación y por cliente.

> **Acción (etapa posterior):** tabla de excepciones + validación de límites.

---

## 8. Qué falta para "tener un flujo de core financiero" — PRIORIZACIÓN

| Prioridad | Brecha | Esfuerzo | ¿Datos en BD? |
|---|---|---|---|
| 🔴 Alta | Realinear umbrales `dnivelaprobacion` al Art. 30 V33 | Bajo | Sí (ajustar datos) |
| 🔴 Alta | Elegibilidad del cliente (sujeto de crédito, Política 2.3.A) | Medio | Sí (`dcalificacioncrediticia`) |
| 🔴 Alta | Ruteo de opinión Riesgos exacto (Art. 34) | Bajo | Parcial (falta dato centrales) |
| 🟡 Media | Clasificación tipo de crédito por endeudamiento (Art. 5) | Bajo | Requiere dato externo |
| 🟡 Media | RDS: 3 ratios + apetito/tolerancia (Art. 13) | Alto | Requiere datos centrales |
| 🟡 Media | Votación de Comité (Art. 29-30) + vigencia resolución (Art. 37) | Medio | Crear tabla |
| 🟢 Baja | Garantías y cobertura (Cap. III) | Alto | Sí (`dgarantia`) |
| 🟢 Baja | Excepciones (Título V + Política 2.8) | Medio | Crear tabla |
| 🟢 Baja | Operaciones derivadas (ampliación/refin./reprog.) | Alto | Sí (`dsolicitudsituacion`) |

> El "core mínimo viable" honesto = filas 🔴 (umbrales correctos + elegibilidad + ruteo Riesgos).
> Con eso el flujo ya aplica las reglas duras del Reglamento, no solo el esqueleto del workflow.
