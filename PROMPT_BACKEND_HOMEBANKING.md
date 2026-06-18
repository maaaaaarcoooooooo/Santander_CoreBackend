# Insumos + Prompt para construir el Backend del Homebanking (Caja Virtual)

> Objetivo: backend FastAPI separado (o módulo) que sirva al portal del cliente
> (Caja Virtual), conectado a la MISMA base de datos `bd_core_financiero`.
> Validado contra las tablas reales (no asumido).

---

## 1. ¿El Homebanking está ligado a las tablas? — SÍ, parcialmente

Mapeo de cada opción del portal (según las capturas) contra las tablas reales:

| Opción del portal (captura) | ¿Tablas existen? | Estado de datos |
|---|---|---|
| **Login / usuario** (usuarios_homebanking) | ✅ Sí | 1.100 usuarios poblados |
| **Consultas › Cuentas de Ahorro** | ✅ `dcuentaahorro`+`fcuentaahorro` | 730 cuentas |
| **Consultas › Movimientos de ahorro** | ✅ `foperaciones` | 3.094 movimientos |
| **Consultas › Cuentas de Crédito** | ✅ `dcuentacredito`+`fagcuentacredito` | 1.100 |
| **Consultas › Detalle/cuotas de crédito** | ✅ `fplanpagomes` | 1.993 cuotas |
| **Operaciones › Plazo Fijo / Ahorro Prog.** | ✅ `fcuentaahorroprogramado`+`dproductoahorro` | 170 / 9 |
| **Operaciones › Transferencias** | ✅ `foperaciones`+`dtipooperacion` (TRF) | catálogo listo |
| **Operaciones › Pago Cuotas Crédito** | ✅ `fplanpagomes`+`foperaciones` | implementado |
| **Pago de Servicios** | ⚠️ `dconceptooperacion` (PSER) existe; falta tabla de servicios/recibos |
| **Transf. Interbancarias** | ✅ `dentidadfinanciera`+`foperaciones` | catálogo bancos listo |
| **Giros (Envío de Giro Efectivo)** | ⚠️ `dgiro`/`fgiro`/`dcanalgiro` existen pero VACÍAS (excepto canal) |
| **Débito Automático** | ⚠️ `ddebitoautomatico`(4)+`fdebitoafiliacion`(0) |
| **Convenios** | ⚠️ `dconvenio`/`fconvenio` existen pero VACÍAS |
| **Créditos › Producto Digital (solicitar)** | ✅ flujo de solicitud ya implementado en el core |
| **Tarjetas de crédito/débito** | ❌ NO existen tablas |
| **Seguros / Microseguros** | ❌ NO existen tablas |
| **Zona Colaboradores** (viáticos, boletas) | ❌ fuera del core de cliente; NO modelado |

### Conclusión
- **Núcleo del portal (consultas + operaciones de crédito/ahorro): 100% soportado** por tablas
  reales y ya con datos.
- **Funciones secundarias** (giros, débito automático, convenios): tablas existen pero VACÍAS →
  requieren seed o quedan como "sin movimientos".
- **Tarjetas, seguros, zona colaboradores: NO modeladas** → fuera de alcance o requieren tablas nuevas.

> Alcance recomendado para el backend HB: **Consultas (ahorro, crédito, movimientos) +
> Operaciones de crédito (solicitar, pagar cuota, prepago) + Transferencias propias.**
> Eso cubre el 90% del valor con datos reales y sin inventar tablas.

---

## 2. Endpoints HB que YA existen en el core actual (reutilizables)

El backend actual ya expone (prefijo `/hb`, token de cliente):
- `POST /hb/login` — login del cliente (bcrypt sobre usuarios_homebanking).
- `GET  /hb/mis-creditos` — créditos del cliente con saldo.
- `GET  /hb/movimientos` — historial de operaciones.
- `POST /hb/solicitar` — solicita crédito (entra al flujo del core).
- `POST /hb/pagar` — paga la próxima cuota.

> El nuevo backend puede ABSORBER estos o consumirlos. Recomendado: un backend HB
> independiente que comparta la BD y replique el patrón.

---

## 3. Catálogos clave (ya poblados, NO inventar)

- `dtipooperacion`: CRE, DEB, TRF, PAG, GIR, AJU
- `dconceptooperacion`: DCAP, PCAP, PINT, PMOR, PGAS, DAHO, RAHO, PSER, TRAN, GIRO, COMI, AJUS
- `dmediopago`: EFE, CHQ, TRF, APP, WEB, CAJ, AGE, CCI
- `dcanaltransaccional`: VEN, CAJ, **WEB (Portal HomeB)**, **APP (App Móvil)**, AGT, TEL, USR
- `dentidadfinanciera`: 17 entidades (para interbancarias)
- `dtiempo`/`dtiempomes`: calendario 2015-2027 (FK obligatoria en foperaciones.periododia)

---

## 4. Reglas técnicas de la BD (aprendidas, evitan errores)

1. **`foperaciones`**: NOT NULL en `codtipkar`(2), `codkardex`(20, único por mov),
   `codtipoegresoingreso`(1: I/E), `periododia` (FK a `dtiempo`). PK por secuencia.
2. **`fclientefuenteingreso`**: PK compuesta `(pkcliente, periodomes)` → usar UPSERT.
3. **Integridad referencial estricta**: poblar `dtiempomes` antes que `dtiempo`; calendario
   debe cubrir las fechas usadas.
4. **bcrypt directo** (no passlib) por incompatibilidad de versión en este venv.
5. **dpersonal ≠ dasesor ≠ dcliente**: son universos distintos; el cliente del portal sale de
   `dcliente` vía `usuarios_homebanking`.
6. Conexión: `postgresql://postgres:123456789@localhost:5432/bd_core_financiero` (.env).

---

## 5. PROMPT para Claude (pegar en el nuevo proyecto)

```
Construye un backend en FastAPI para el HOMEBANKING (Caja Virtual) de una caja municipal,
en Python, que se conecta a una base PostgreSQL EXISTENTE llamada bd_core_financiero
(no crear tablas nuevas salvo que se indique; reutilizar las existentes).

CONEXIÓN
- DATABASE_URL = postgresql://postgres:123456789@localhost:5432/bd_core_financiero
- Usar SQLAlchemy (engine + text()), pydantic-settings para .env, JWT con python-jose,
  bcrypt DIRECTO para passwords (NO passlib, por incompatibilidad de versión).

ARQUITECTURA (igual que el core, en capas)
- app/core/      cfg_config, cfg_database, cfg_security (JWT), cfg_auth (dependencia de cliente)
- app/repositories/  consultas SQL crudas con text()
- app/controllers/   orquestación / reglas
- app/routes/        routers FastAPI
- app/schemas/       modelos pydantic
- main.py con CORS para http://localhost:5173

AUTENTICACIÓN DEL CLIENTE (no es personal del banco)
- Tabla usuarios_homebanking (pkusuario, pkcliente, username, password_hash, activo, bloqueado,
  intentos_fallidos, ultimo_acceso). El cliente sale de dcliente vía pkcliente.
- POST /auth/login → valida username + bcrypt(password); emite JWT con
  {sub: codcliente, tipo:"cliente", pkcliente, nombre}. Manejar bloqueo e intentos fallidos.
- Dependencia get_cliente que exige tipo=="cliente" en el token.

ENDPOINTS (alcance: consultas + operaciones de crédito/ahorro)
Consultas:
- GET /cuentas/ahorro            → cuentas de ahorro del cliente (dcuentaahorro+fcuentaahorro):
                                    nro, tipo, saldo, estado, moneda.
- GET /cuentas/ahorro/{cod}/movimientos → movimientos (foperaciones por pkcuentaahorro).
- GET /cuentas/credito           → créditos del cliente (dcuentacredito+fagcuentacredito):
                                    cuenta, fecha desembolso, saldo, pago pendiente.
- GET /cuentas/credito/{cod}/cuotas → cronograma/cuotas (fplanpagomes): nro, vencimiento,
                                    monto, días mora.
Operaciones:
- POST /operaciones/pago-cuota   → paga la próxima cuota pendiente de un crédito:
                                    UPDATE fplanpagomes.montocapitalpagado + INSERT foperaciones
                                    (concepto PCAP, canal APP/WEB).
- POST /operaciones/transferencia → transferencia entre cuentas propias del cliente:
                                    INSERT foperaciones (tipo TRF) débito y crédito.
- POST /creditos/solicitar       → registra una solicitud de crédito (dsolicitud) que será
                                    evaluada por el core (estado inicial En Evaluación = 1).

REGLAS TÉCNICAS DE LA BD (OBLIGATORIO respetar, ya verificadas)
1. foperaciones NOT NULL: codtipkar(char2 'CR'/'DB'), codkardex(varchar20 ÚNICO por
   movimiento, ej 'PAG-<pkcc>-<nro>-<periododia>'), codtipoegresoingreso(char1 'I' ingreso /
   'E' egreso), periododia (FK a dtiempo, formato yyyymmdd), pkconceptooperacion, pktipooperacion,
   pkmoneda, pkagenciaorigen, montooperacion, montopagoconcepto. PK pkoperacion por secuencia
   foperaciones_pkoperacion_seq (usar nextval).
2. periododia DEBE existir en dtiempo (calendario). Si falta una fecha, error de FK.
3. fclientefuenteingreso tiene PK compuesta (pkcliente, periodomes) → UPSERT.
4. Catálogos por código (NO hardcodear PKs): dtipooperacion (TRF/DEB/CRE/PAG),
   dconceptooperacion (PCAP/DCAP/TRAN/PSER), dmediopago (APP/WEB), dcanaltransaccional (APP/WEB),
   dcondicioncontable ('01' Vigente Normal).
5. Catálogo de bancos: dentidadfinanciera (para interbancarias, opcional).

DATOS DE PRUEBA
- Login: username = codcliente en minúscula (ej. cli000001), password = demo1234.
- Hay 1.100 clientes con homebanking, 730 cuentas de ahorro, 1.100 créditos, 3.094 operaciones.

ENTREGABLES
- Estructura de carpetas creada, main.py ejecutable con uvicorn en puerto 8002
  (para no chocar con el core en 8001).
- Verifica cada endpoint con datos reales antes de darlo por hecho (no asumir).
- README con los comandos para levantar (Git Bash) y ejemplos de cada endpoint.
```

---

## 6. Lo que el nuevo asistente NECESITARÁ que le pases
1. El **.env** con DATABASE_URL (o las credenciales).
2. Confirmar el **puerto** (sugerido 8002 para no chocar con el core 8001).
3. Si quieres **giros/convenios/débito automático**: avisar que sus tablas están VACÍAS
   (habría que poblarlas o dejar esas pantallas "sin movimientos").
4. Si quieres **tarjetas/seguros**: requieren CREAR tablas nuevas (no existen).
