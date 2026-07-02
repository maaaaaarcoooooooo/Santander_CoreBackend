"""
Repositorio de evaluación y desembolso de solicitudes — MPR-003-CRE (actividades 11, 16, 45-48).

- registrar_ingreso: fuente de ingreso del cliente (fclientefuenteingreso).
- registrar_evaluacion: cabecera (devaluacion) + detalle (fevalconsumo|fevalmicroactivo).
- desembolsar: crea la cuenta de crédito (dcuentacredito) + movimiento de desembolso
  (foperaciones) + movimiento de ABONO a la cuenta de ahorros del cliente.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from decimal import Decimal

PERIODO = 202512


def obtener_cuenta_ahorros_principal(db: Session, pkcliente: int):
    """
    Obtiene la cuenta de ahorros principal del cliente.
    Prioriza: Cuenta Corriente > Cuenta de Ahorro > Cuenta de Depósito.
    """
    result = db.execute(text("""
        SELECT ca.pkcuentaahorro, ca.codcuentaahorro
        FROM dcuentaahorro ca
        JOIN dtipocuentaahorro tca ON tca.pktipocuentaahorro = ca.pktipocuentaahorro
        WHERE ca.pkcliente = :pkcliente
        ORDER BY 
            CASE tca.codtipocuentaahorro 
                WHEN 'CC' THEN 1  -- Cuenta Corriente
                WHEN 'AH' THEN 2  -- Ahorro
                WHEN 'DP' THEN 3  -- Depósito
                ELSE 4
            END,
            ca.pkcuentaahorro ASC
        LIMIT 1
    """), {"pkcliente": pkcliente}).fetchone()
    return result


def registrar_ingreso(db: Session, pkcliente: int, *, tipo: str, monto: float,
                      nombre_empresa: str = None) -> dict:
    # PK compuesta (pkcliente, periodomes): upsert para que sea idempotente.
    db.execute(text("""
        INSERT INTO fclientefuenteingreso
            (pkcliente, periodomes, tipofuenteingreso, montofuenteingreso,
             codrelacion, nombreempresa, fecultactualizacion)
        VALUES (:pk, :per, :tipo, :monto, 'T', :emp, NOW())
        ON CONFLICT (pkcliente, periodomes) DO UPDATE
            SET tipofuenteingreso = EXCLUDED.tipofuenteingreso,
                montofuenteingreso = EXCLUDED.montofuenteingreso,
                nombreempresa = EXCLUDED.nombreempresa,
                fecultactualizacion = NOW()
    """), {"pk": pkcliente, "per": PERIODO, "tipo": tipo[:2],
           "monto": monto, "emp": nombre_empresa})
    db.commit()
    return {"pkcliente": pkcliente, "tipo": tipo, "monto": monto}


def registrar_evaluacion(db: Session, codsolicitud: str, *, es_microempresa: bool,
                         ingreso: float, gasto_familiar: float,
                         monto_solicitud: float = 0.0,
                         fortaleza: str = "", debilidad: str = "") -> dict:
    """Crea/actualiza la evaluación de la solicitud (cabecera + detalle según tipo)."""
    # evita duplicar: si ya hay evaluación para la solicitud, la retorna
    ya = db.execute(text("SELECT pkevaluacion FROM devaluacion WHERE codsolicitud=:c"),
                    {"c": codsolicitud}).scalar()
    if ya:
        return {"codsolicitud": codsolicitud, "pkevaluacion": ya, "creada": False}

    excedente = round(ingreso - gasto_familiar, 2)
    row = db.execute(text("""
        INSERT INTO devaluacion
            (nroevaluacion, valorexcedentecredito, tipoevaluacion, codsolicitud, fecultactualizacion)
        VALUES ('EV-' || :c, :exc, :tipo, :c, NOW())
        RETURNING pkevaluacion
    """), {"c": codsolicitud, "exc": excedente, "tipo": "ME" if es_microempresa else "CO"}).fetchone()
    pkeval = row.pkevaluacion

    if es_microempresa:
        db.execute(text("""
            INSERT INTO fevalmicroactivo
                (pkevaluacion, nroreg, montoactivodisponible, montoactivoinventario,
                 montoactivofijo, montogastofamiliar, fecultactualizacion)
            VALUES (:pk, 1, :disp, :inv, :fijo, :gf, NOW())
        """), {"pk": pkeval, "disp": round(monto_solicitud*0.20, 2),
               "inv": round(monto_solicitud*0.50, 2), "fijo": round(monto_solicitud*0.80, 2),
               "gf": gasto_familiar})
    else:
        db.execute(text("""
            INSERT INTO fevalconsumo
                (pkevaluacion, monto, montogastofamiliar, codtipoingreso,
                 fortalezaevaluacion, debilidadevaluacion, fecultactualizacion)
            VALUES (:pk, :monto, :gf, 'D', :fz, :db, NOW())
        """), {"pk": pkeval, "monto": ingreso, "gf": gasto_familiar,
               "fz": fortaleza or "Ingreso estable", "db": debilidad or "Sin garantía real"})
    db.commit()
    return {"codsolicitud": codsolicitud, "pkevaluacion": pkeval, "excedente": excedente, "creada": True}


def desembolsar(db: Session, sol) -> dict:
    """
    Desembolsa el crédito aprobado:
    1. Crea la cuenta de crédito (dcuentacredito)
    2. Registra movimiento de desembolso en foperaciones (vinculado a crédito)
    3. Acredita el monto a la cuenta de ahorros del cliente (movimiento DCAP)
    4. Actualiza el saldo de la cuenta de ahorros
    
    `sol` es la fila de rep_solicitudes.obtener (debe tener pksolicitud, pkcliente, monto, etc.).
    """
    monto = float(sol.montoaprobadocredito or sol.montosolicitudcredito or 0)

    # 1) genera la cuenta de crédito (codigo derivado del pk por secuencia)
    cc = db.execute(text("""
        INSERT INTO dcuentacredito (pkcuentacredito, codcuentacredito, pkcliente, nrocronograma, fecultactualizacion)
        VALUES (nextval('dcuentacredito_pkcuentacredito_seq'),
                'CRD' || LPAD(currval('dcuentacredito_pkcuentacredito_seq')::text, 7, '0'),
                :pkcli, 1, NOW())
        RETURNING pkcuentacredito, codcuentacredito
    """), {"pkcli": sol.pkcliente}).fetchone()

    # 2) catálogos para el movimiento de desembolso
    cat = db.execute(text("""
        SELECT (SELECT pkconceptooperacion FROM dconceptooperacion WHERE codconceptooperacion='DCAP') con,
               (SELECT pktipooperacion FROM dtipooperacion WHERE codtipooperacion='CRE') tipo,
               (SELECT pkmediopago FROM dmediopago WHERE codmediopago='WEB') medio,
               (SELECT pkcanaltransaccional FROM dcanaltransaccional WHERE codcanaltransaccional='WEB') canal,
               (SELECT pkcondicioncontable FROM dcondicioncontable WHERE codcondicioncontable='01') cond,
               (SELECT pkmoneda FROM dmoneda ORDER BY pkmoneda LIMIT 1) mon,
               (SELECT MIN(pkproducto) FROM dproducto) prod,
               (SELECT MIN(pkagencia) FROM dagencia) ag
    """)).fetchone()

    hoy = datetime.utcnow()
    pd = int(hoy.strftime("%Y%m%d"))
    
    # 2a) Registra el movimiento de DESEMBOLSO (en la cuenta de crédito)
    db.execute(text("""
        INSERT INTO foperaciones
            (codtipkar, codkardex, pkcuentacredito, pkconceptooperacion, pktipooperacion,
             pkmediopago, pkcanaltransaccional, pkmoneda, pkcondicioncontable, pkproducto,
             pkagenciaorigen, montooperacion, montopagoconcepto, codtipoegresoingreso,
             fechahoraoperacion, periododia, codusuope, fecultactualizacion)
        VALUES ('CR', 'DESEMB-' || :pkcc, :pkcc, :con, :tipo, :medio, :canal, :mon, :cond, :prod,
                :ag, :monto, :monto, 'I', :fh, :pd, 'CORE', NOW())
    """), {"pkcc": cc.pkcuentacredito, "con": cat.con, "tipo": cat.tipo, "medio": cat.medio,
           "canal": cat.canal, "mon": cat.mon, "cond": cat.cond, "prod": cat.prod,
           "ag": cat.ag, "monto": monto, "fh": hoy, "pd": pd})

    # 3) CRUCIAL: Obtiene la cuenta de ahorros del cliente y acredita el dinero
    cta_ahorro = obtener_cuenta_ahorros_principal(db, sol.pkcliente)
    if cta_ahorro:
        pkcta_ahorro = cta_ahorro.pkcuentaahorro
        
        # 3a) Obtiene PKs de catálogos para la operación de abono
        cat_abono = db.execute(text("""
            SELECT (SELECT pkconceptooperacion FROM dconceptooperacion WHERE codconceptooperacion='DCAP') con,
                   (SELECT pktipooperacion FROM dtipooperacion WHERE codtipooperacion='DEB') tipo,
                   (SELECT pkmediopago FROM dmediopago WHERE codmediopago='WEB') medio,
                   (SELECT pkcanaltransaccional FROM dcanaltransaccional WHERE codcanaltransaccional='WEB') canal,
                   (SELECT pkcondicioncontable FROM dcondicioncontable WHERE codcondicioncontable='01') cond,
                   (SELECT pkmoneda FROM dmoneda ORDER BY pkmoneda LIMIT 1) mon,
                   (SELECT MIN(pkproducto) FROM dproducto) prod,
                   (SELECT MIN(pkagencia) FROM dagencia) ag
        """)).fetchone()
        
        # 3b) Registra movimiento de ABONO en la cuenta de ahorros
        db.execute(text("""
            INSERT INTO foperaciones
                (codtipkar, codkardex, pkcuentaahorro, pkconceptooperacion, pktipooperacion,
                 pkmediopago, pkcanaltransaccional, pkmoneda, pkcondicioncontable, pkproducto,
                 pkagenciaorigen, montooperacion, montopagoconcepto, codtipoegresoingreso,
                 fechahoraoperacion, periododia, codusuope, fecultactualizacion)
            VALUES ('CR', 'ABONO-DESEMB-' || :pkcc, :pkcta, :con, :tipo, :medio, :canal, :mon, :cond, :prod,
                    :ag, :monto, :monto, 'I', :fh, :pd, 'CORE', NOW())
        """), {"pkcc": cc.pkcuentacredito, "pkcta": pkcta_ahorro, "con": cat_abono.con, "tipo": cat_abono.tipo, 
               "medio": cat_abono.medio, "canal": cat_abono.canal, "mon": cat_abono.mon, 
               "cond": cat_abono.cond, "prod": cat_abono.prod, "ag": cat_abono.ag, 
               "monto": monto, "fh": hoy, "pd": pd})
        
        # 3c) Actualiza el saldo de la cuenta de ahorros (suma el monto desembolsado)
        db.execute(text("""
            UPDATE fcuentaahorro
            SET montosaldocapitaltotal = montosaldocapitaltotal + :monto,
                fecultactualizacion = NOW()
            WHERE pkcuentaahorro = :pkcta
              AND periododia = (SELECT MAX(periododia) FROM fcuentaahorro 
                                WHERE pkcuentaahorro = :pkcta)
        """), {"monto": Decimal(str(monto)), "pkcta": pkcta_ahorro})
    
    db.commit()
    return {
        "codcuentacredito": cc.codcuentacredito, 
        "monto_desembolsado": monto,
        "cuenta_ahorros_acreditada": cta_ahorro.codcuentaahorro if cta_ahorro else None,
        "fecha": hoy.date().isoformat()
    }
