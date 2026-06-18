"""
Repositorio de evaluación y desembolso de solicitudes — MPR-003-CRE (actividades 11, 16, 45-48).

- registrar_ingreso: fuente de ingreso del cliente (fclientefuenteingreso).
- registrar_evaluacion: cabecera (devaluacion) + detalle (fevalconsumo|fevalmicroactivo).
- desembolsar: crea la cuenta de crédito (dcuentacredito) + movimiento de desembolso
  (foperaciones) y marca la solicitud como Desembolsada.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text

PERIODO = 202512


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
    Crea la cuenta de crédito y el movimiento de desembolso para una solicitud APROBADA.
    `sol` es la fila de rep_solicitudes.obtener (debe tener pksolicitud, pkcliente, monto, etc.).
    """
    monto = float(sol.montoaprobadocredito or sol.montosolicitudcredito or 0)

    # genera la cuenta de crédito (codigo derivado del pk por secuencia)
    cc = db.execute(text("""
        INSERT INTO dcuentacredito (pkcuentacredito, codcuentacredito, pkcliente, nrocronograma, fecultactualizacion)
        VALUES (nextval('dcuentacredito_pkcuentacredito_seq'),
                'CRD' || LPAD(currval('dcuentacredito_pkcuentacredito_seq')::text, 7, '0'),
                :pkcli, 1, NOW())
        RETURNING pkcuentacredito, codcuentacredito
    """), {"pkcli": sol.pkcliente}).fetchone()

    # catálogos para el movimiento de desembolso
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
    db.commit()
    return {"codcuentacredito": cc.codcuentacredito, "monto_desembolsado": monto,
            "fecha": hoy.date().isoformat()}
