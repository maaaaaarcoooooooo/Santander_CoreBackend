"""
Repositorio de evaluación y desembolso de solicitudes — MPR-003-CRE (actividades 11, 16, 45-48).
"""
from datetime import datetime
import calendar
from datetime import date as date_
from sqlalchemy.orm import Session
from sqlalchemy import text

PERIODO = 202512


def registrar_ingreso(db: Session, pkcliente: int, *, tipo: str, monto: float,
                      nombre_empresa: str = None) -> dict:
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
    Desembolsa un crédito aprobado:
    1. Crea la cuenta de crédito (dcuentacredito)
    2. Registra el movimiento de desembolso en foperaciones
    3. Crea/obtiene la cuenta de ahorros del cliente
    4. Acredita el dinero en la cuenta de ahorros (movimiento + saldo)
    5. Genera el cronograma de cuotas (fplanpagomes)
    """
    if not sol or sol.montoaprobadocredito is None and sol.montosolicitudcredito is None:
        return {"error": "Solicitud inválida o sin monto"}
    
    monto = float(sol.montoaprobadocredito or sol.montosolicitudcredito or 0)
    if monto <= 0:
        return {"error": "Monto inválido"}
    
    plazo = int(sol.plazosolicitudcredito or sol.nrocuotasolicitud or 12)
    nrodias = plazo * 30

    # 1. CREAR CUENTA DE CRÉDITO
    try:
        cc = db.execute(text("""
            INSERT INTO dcuentacredito (pkcuentacredito, codcuentacredito, pkcliente, nrocronograma, fecultactualizacion)
            VALUES (nextval('dcuentacredito_pkcuentacredito_seq'),
                    'CRD' || LPAD(currval('dcuentacredito_pkcuentacredito_seq')::text, 7, '0'),
                    :pkcli, 1, NOW())
            RETURNING pkcuentacredito, codcuentacredito
        """), {"pkcli": sol.pkcliente}).fetchone()
        if not cc:
            db.rollback()
            return {"error": "No se pudo crear la cuenta de crédito"}
    except Exception as e:
        db.rollback()
        return {"error": f"Error creando cuenta de crédito: {str(e)}"}

    # 2. OBTENER CATÁLOGOS NECESARIOS
    try:
        cat = db.execute(text("""
            SELECT 
                (SELECT pkconceptooperacion FROM dconceptooperacion WHERE codconceptooperacion='DCAP' LIMIT 1) AS con_dcap,
                (SELECT pkconceptooperacion FROM dconceptooperacion WHERE codconceptooperacion='DEP' LIMIT 1) AS con_dep,
                (SELECT pktipooperacion FROM dtipooperacion WHERE codtipooperacion='CRE' LIMIT 1) AS tipo_cre,
                (SELECT pkmediopago FROM dmediopago WHERE codmediopago='WEB' LIMIT 1) AS medio_web,
                (SELECT pkcanaltransaccional FROM dcanaltransaccional WHERE codcanaltransaccional='WEB' LIMIT 1) AS canal_web,
                (SELECT pkcondicioncontable FROM dcondicioncontable WHERE codcondicioncontable='01' LIMIT 1) AS cond_vigente,
                (SELECT pkmoneda FROM dmoneda ORDER BY pkmoneda LIMIT 1) AS mon,
                (SELECT pkproducto FROM dproducto ORDER BY pkproducto LIMIT 1) AS prod,
                (SELECT pkagencia FROM dagencia ORDER BY pkagencia LIMIT 1) AS ag,
                (SELECT pkestadocredito FROM destadocredito WHERE codestadocredito='01' LIMIT 1) AS est,
                (SELECT pkactividadeconomica FROM dactividadeconomica ORDER BY pkactividadeconomica LIMIT 1) AS act
        """)).fetchone()
        
        if not cat or not cat.con_dcap:
            db.rollback()
            return {"error": "Faltan catálogos requeridos en la BD"}
    except Exception as e:
        db.rollback()
        return {"error": f"Error obteniendo catálogos: {str(e)}"}

    hoy = datetime.utcnow()
    pd_val = int(hoy.strftime("%Y%m%d"))
    periodomes = int(hoy.strftime("%Y%m"))

    # Obtener pkasesor de referencia
    pkasesor = db.execute(text("""
        SELECT pkasesor FROM fplanpagomes WHERE pkagencia = :ag AND pkasesor IS NOT NULL LIMIT 1
    """), {"ag": cat.ag}).scalar() or 1

    # 3. REGISTRAR MOVIMIENTO DE DESEMBOLSO EN FOPERACIONES (vinculado a crédito)
    try:
        db.execute(text("""
            INSERT INTO foperaciones
                (codtipkar, codkardex, pkcuentacredito, pkconceptooperacion, pktipooperacion,
                 pkmediopago, pkcanaltransaccional, pkmoneda, pkcondicioncontable, pkproducto,
                 pkagenciaorigen, montooperacion, montopagoconcepto, codtipoegresoingreso,
                 fechahoraoperacion, periododia, codusuope, fecultactualizacion)
            VALUES ('CR', 'DESEMB-' || :pkcc, :pkcc, :con_dcap, :tipo_cre, :medio_web, :canal_web, :mon, :cond_vigente, :prod,
                    :ag, :monto, :monto, 'I', :fh, :pd, 'CORE', NOW())
        """), {
            "pkcc": cc.pkcuentacredito, "con_dcap": cat.con_dcap, "tipo_cre": cat.tipo_cre, 
            "medio_web": cat.medio_web, "canal_web": cat.canal_web, "mon": cat.mon, 
            "cond_vigente": cat.cond_vigente, "prod": cat.prod, "ag": cat.ag, 
            "monto": monto, "fh": hoy, "pd": pd_val
        })
    except Exception as e:
        db.rollback()
        return {"error": f"Error registrando desembolso: {str(e)}"}

    # 4. Insertar en fagcuentacredito
    cal = 1  # Calificación por defecto
    try:
        db.execute(text("""
            INSERT INTO fagcuentacredito (
                periodomes, pkcuentacredito, pksolicitud, pkestadocredito, nrocuotas, nrodias,
                nrodiasgracias, diafechafija, codtipocuota, codtipoperiodo, flaglibreamortizacion,
                montoaprobadocredito, montocapitaldesembolsado, montocapitalpagado,
                montointeresprogramado, montointeresalafecha, montointerespagado,
                montomoraprogramada, montomorapagada, montogastoprogramado, montogastopagado,
                pkproducto, pkrecurso, pksubrecurso, pkmoneda, pkmodalidad,
                codplazo, codlineacredito, nrotasacompensatoria, tasainterescompensatoria,
                nrotasamoratoria, tasainteresmoratoria, diasatrasocredito,
                fechaculminacioncredito, fechageneracioncredito, fechadesembolsocredito,
                tipocambiodesembolso, pkgrupocredito, flagrefinanciado, flagreestructurado,
                flagreprogramado, flagjudicial, flagcastigado, pkactividadeconomica,
                montosaldonormal, montosaldovencido, flagnuevorecurrente,
                montocostoefectivo, pktipotasacompensatoria, pktipotasamoratoria,
                pkcliente, nrocronograma, pkcondicioncontable, flagclientenuevobancoandino,
                flagclientenuevo, flagclientecartera, pkcalificacioncrediticiainterna,
                pkcalificacioncrediticiaexterna, fechaingresojudicial, montocapitalinicio,
                montointeresinicio, montomorainicio, montogastoinicio, nrodiasatrasoinicio,
                montosaldocapital, montosaldointeres, montosaldomoratorio, montosaldogasto,
                car_vig_capital, car_vig_int_compensatorio, car_vig_int_moratorio, car_vig_gastos,
                car_ven_capital, car_ven_int_compensatorio, car_ven_int_moratorio, car_ven_gastos,
                car_ref_capital, car_ref_int_compensatorio, car_ref_int_moratorio, car_ref_gastos,
                car_rep_capital, car_rep_int_compensatorio, car_rep_int_moratorio, car_rep_gastos,
                car_jud_capital, car_jud_int_compensatorio, car_jud_int_moratorio, car_jud_gastos,
                car_cas_capital, car_cas_int_compensatorio, car_cas_int_moratorio, car_cas_gastos,
                car_con_capital, car_con_int_compensatorio, car_con_int_moratorio, car_con_gastos,
                saldodiferido, saldodevengado, saldoprovisiones, montosaldocliente,
                pkagencia, pkjeferegional, pkadministrador, pkasesor, pkasesornivel, fecultactualizacion
            ) VALUES (
                :periodomes, :pkcc, :pksol, :est, :plazo, :nrodias, 0,
                15, 'FIJA', 'MEN', 'N',
                :monto, :monto, 0, 0, 0, 0, 0, 0, 0, 0, :prod,
                1, 1, :mon, 1,
                'MEN', 'LIN',
                0, 0, 0, 0,
                0, (NOW() + INTERVAL '1 year')::date, NOW()::date, NOW()::date,
                1.0, 1,
                'N', 'N', 'N', 'N', 'N', :act, :monto, 0, 'N',
                0, 1, 1,
                :pkcli, 1, :cond_vigente, 'N', 'N', 'S', :cal, :cal, NULL,
                :monto, 0, 0, 0, 0, :monto, 0, 0, 0,
                :monto, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, :monto, :ag, NULL, NULL, :pkasesor, NULL, NOW()
            )
        """), {
            "periodomes": periodomes, "pkcc": cc.pkcuentacredito, "pksol": sol.pksolicitud,
            "est": cat.est, "plazo": plazo, "nrodias": nrodias, "monto": monto,
            "prod": cat.prod, "mon": cat.mon, "act": cat.act, "pkcli": sol.pkcliente,
            "cond_vigente": cat.cond_vigente, "ag": cat.ag, "pkasesor": pkasesor, "cal": cal
        })
    except Exception as e:
        db.rollback()
        return {"error": f"Error insertando en fagcuentacredito: {str(e)}"}


    # 5. Generar cronograma de cuotas en fplanpagomes
    try:
        cuota_base = round(monto / plazo, 2)
        cuota_ultima = round(monto - cuota_base * (plazo - 1), 2)
        codplanpago = "PLAN" + str(cc.pkcuentacredito).zfill(7)

        for n in range(1, plazo + 1):
            monto_cuota = cuota_base if n < plazo else cuota_ultima
            monto_saldo = round(monto - cuota_base * (n - 1), 2) if n < plazo else 0.0
            mes = hoy.month + n
            anio = hoy.year + (mes - 1) // 12
            mes = ((mes - 1) % 12) + 1
            ultimo_dia = calendar.monthrange(anio, mes)[1]
            dia = min(hoy.day, ultimo_dia)
            fecha_venc = date_(anio, mes, dia)
            periodo_cuota = int(fecha_venc.strftime("%Y%m"))

            db.execute(text("""
                INSERT INTO fplanpagomes (
                    periodomes, pkcuentacredito, codplanpago, nrocuota,
                    pksolicitud, pkestadocredito, pkproducto, pkmoneda,
                    pkmodalidad, pkgrupocredito, pkactividadeconomica,
                    pktipotasacompensatoria, pktipotasamoratoria,
                    pkcliente, pkcondicioncontable, pkcalificacioncrediticiainterna,
                    pkagencia, pkjeferegional, pkadministrador, pkasesor, pkasesornivel,
                    pkestadodesembolso, pkmodalidadpago,
                    codestadocuota, codestadoplan,
                    fechavencimientopagocuota, fechapagocuota,
                    montocuota, montosaldo, montomora,
                    montocuotavencida, montocuotaatrasada,
                    montointeresprogramado, montointerespagado, montointeresalafecha,
                    montomoraprogramado, montomorapagada,
                    montogasto, montogastoprogramado, montogastopagado,
                    montosaldocapital, montocapitalpagado, montocapitalprogramado,
                    montocapitaldesembolsado,
                    diasatrasocuota, diasvencidocuota,
                    interesdevengadocuota, montopagoanticipado, montopagoparcial,
                    fecultactualizacion
                ) VALUES (
                    :periodomes, :pkcc, :codplan, :nrocuota,
                    :pksol, :est, :prod, :mon,
                    NULL, NULL, :act,
                    NULL, NULL,
                    :pkcli, :cond, NULL,
                    :ag, NULL, NULL, :asesor, NULL,
                    NULL, NULL,
                    '01', NULL,
                    :fecha_venc, NULL,
                    :montocuota, :montosaldo, 0,
                    0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                    :montosaldo, 0, :montocuota,
                    :monto_total,
                    0, 0, 0, 0, 0,
                    NOW()
                )
            """), {
                "periodomes": periodo_cuota,
                "pkcc": cc.pkcuentacredito,
                "codplan": codplanpago,
                "nrocuota": n,
                "pksol": sol.pksolicitud,
                "est": cat.est,
                "prod": cat.prod,
                "mon": cat.mon,
                "act": cat.act,
                "pkcli": sol.pkcliente,
                "cond": cat.cond_vigente,
                "ag": cat.ag,
                "asesor": pkasesor,
                "fecha_venc": fecha_venc,
                "montocuota": monto_cuota,
                "montosaldo": monto_saldo,
                "monto_total": monto,
            })
    except Exception as e:
        db.rollback()
        return {"error": f"Error generando cronograma: {str(e)}"}


    # 6. OBTENER O CREAR CUENTA DE AHORROS Y ACREDITAR DINERO
    try:
        # Obtener cuenta de ahorros existente
        ca = db.execute(text("""
            SELECT pkcuentaahorro FROM dcuentaahorro WHERE pkcliente = :pkcli LIMIT 1
        """), {"pkcli": sol.pkcliente}).fetchone()

        if not ca:
            # Crear nueva cuenta de ahorros
            ca = db.execute(text("""
                INSERT INTO dcuentaahorro (
                    codcuentaahorro, pkcliente, pktipocuentaahorro, fecultactualizacion
                ) VALUES (
                    'AHO' || LPAD((SELECT COALESCE(MAX(pkcuentaahorro), 0) + 1 FROM dcuentaahorro)::text, 7, '0'),
                    :pkcli, 
                    (SELECT pktipocuentaahorro FROM dtipocuentaahorro WHERE codtipocuentaahorro='AH' LIMIT 1),
                    NOW()
                ) RETURNING pkcuentaahorro, codcuentaahorro
            """), {"pkcli": sol.pkcliente}).fetchone()

            # Crear snapshot en fcuentaahorro
            db.execute(text("""
                INSERT INTO fcuentaahorro (
                    periododia, pkcuentaahorro, pkproductoahorro, pkmoneda,
                    pktipocuentaahorro, pktipotasaahorro, pkcliente,
                    pkauxiliar, pkoperador, pkadministrador, pkagencia,
                    pkestadocuenta, montosaldocapitaltotal, montosaldointerestotal,
                    montosaldopromediototal, fechaaperturacuenta, montodepositoapertura,
                    tasainterescuenta, tasaefectivaanual, nrotitulares, nrofirmas,
                    flagexoneracionimpuesto, flagexoneracioncomision, flagcuentapromocion,
                    nrooperacioneslibres, fechaultimaconsulta, flag_ac, flag_pf, flag_cts, flag_ap,
                    montosaldodisponible_ac, montosaldominimo_ac, montosaldocontable_ac,
                    fecultactualizacion
                ) VALUES (
                    :pd, :pkca, 
                    COALESCE((SELECT pkproductoahorro FROM dproductoahorro LIMIT 1), 1),
                    :mon,
                    COALESCE((SELECT pktipocuentaahorro FROM dtipocuentaahorro WHERE codtipocuentaahorro='AH' LIMIT 1), 1),
                    COALESCE((SELECT pktipotasaahorro FROM dtipotasaahorro LIMIT 1), 1),
                    :pkcli,
                    COALESCE((SELECT pkauxiliar FROM fcuentaahorro LIMIT 1), 1),
                    COALESCE((SELECT pkoperador FROM fcuentaahorro LIMIT 1), 1),
                    COALESCE((SELECT pkadministrador FROM fcuentaahorro LIMIT 1), 1),
                    :ag,
                    COALESCE((SELECT pkestadocuenta FROM destadocuenta WHERE codestadocuenta='01' LIMIT 1), 1),
                    0, 0, 0, NOW()::date, 0, 0, 0, 1, 1,
                    'N', 'N', 'N', 0, NOW()::date, 'S', 'N', 'N', 'N', 0, 0, 0, NOW()
                )
            """), {
                "pd": pd_val, "pkca": ca.pkcuentaahorro, "mon": cat.mon, 
                "pkcli": sol.pkcliente, "ag": cat.ag
            })

        pkcuentaahorro = ca.pkcuentaahorro

        # 6a. REGISTRAR MOVIMIENTO DE ABONO EN FOPERACIONES (vinculado a cuenta de ahorros)
        db.execute(text("""
            INSERT INTO foperaciones
                (codtipkar, codkardex, pkcuentaahorro, pkconceptooperacion, pktipooperacion,
                 pkmediopago, pkcanaltransaccional, pkmoneda, pkcondicioncontable, pkproducto,
                 pkagenciaorigen, montooperacion, montopagoconcepto, codtipoegresoingreso,
                 fechahoraoperacion, periododia, codusuope, fecultactualizacion)
            VALUES ('CR', 'ABONO-DESEMB-' || :pkcc, :pkca, :con_dep, :tipo_cre, :medio_web, :canal_web, :mon, :cond_vigente, :prod,
                    :ag, :monto, :monto, 'I', :fh, :pd, 'CORE', NOW())
        """), {
            "pkcc": cc.pkcuentacredito, "pkca": pkcuentaahorro, "con_dep": cat.con_dep, "tipo_cre": cat.tipo_cre,
            "medio_web": cat.medio_web, "canal_web": cat.canal_web, "mon": cat.mon,
            "cond_vigente": cat.cond_vigente, "prod": cat.prod, "ag": cat.ag,
            "monto": monto, "fh": hoy, "pd": pd_val
        })

        # 6b. ACTUALIZAR SALDO EN FCUENTAAHORRO
        # Primero intenta actualizar; si no encuentra fila, crea una nueva
        result = db.execute(text("""
            UPDATE fcuentaahorro
            SET montosaldocapitaltotal   = montosaldocapitaltotal + :monto,
                montosaldodisponible_ac  = COALESCE(montosaldodisponible_ac, 0) + :monto,
                montosaldocontable_ac    = COALESCE(montosaldocontable_ac, 0) + :monto,
                fecultactualizacion      = NOW()
            WHERE pkcuentaahorro = :pkca
            RETURNING pkcuentaahorro
        """), {"pkca": pkcuentaahorro, "monto": monto})
        
        if result.fetchone() is None:
            # Si no encontró fila, insertar un nuevo snapshot
            db.execute(text("""
                INSERT INTO fcuentaahorro (
                    periododia, pkcuentaahorro, pkproductoahorro, pkmoneda,
                    pktipocuentaahorro, pktipotasaahorro, pkcliente,
                    pkauxiliar, pkoperador, pkadministrador, pkagencia,
                    pkestadocuenta, montosaldocapitaltotal, montosaldointerestotal,
                    montosaldopromediototal, fechaaperturacuenta, montodepositoapertura,
                    tasainterescuenta, tasaefectivaanual, nrotitulares, nrofirmas,
                    flagexoneracionimpuesto, flagexoneracioncomision, flagcuentapromocion,
                    nrooperacioneslibres, fechaultimaconsulta, flag_ac, flag_pf, flag_cts, flag_ap,
                    montosaldodisponible_ac, montosaldominimo_ac, montosaldocontable_ac,
                    fecultactualizacion
                ) VALUES (
                    :pd, :pkca, 
                    COALESCE((SELECT pkproductoahorro FROM dproductoahorro LIMIT 1), 1),
                    :mon,
                    COALESCE((SELECT pktipocuentaahorro FROM dtipocuentaahorro WHERE codtipocuentaahorro='AH' LIMIT 1), 1),
                    COALESCE((SELECT pktipotasaahorro FROM dtipotasaahorro LIMIT 1), 1),
                    :pkcli,
                    COALESCE((SELECT pkauxiliar FROM fcuentaahorro LIMIT 1), 1),
                    COALESCE((SELECT pkoperador FROM fcuentaahorro LIMIT 1), 1),
                    COALESCE((SELECT pkadministrador FROM fcuentaahorro LIMIT 1), 1),
                    :ag,
                    COALESCE((SELECT pkestadocuenta FROM destadocuenta WHERE codestadocuenta='01' LIMIT 1), 1),
                    :monto, 0, 0, NOW()::date, 0, 0, 0, 1, 1,
                    'N', 'N', 'N', 0, NOW()::date, 'S', 'N', 'N', 'N', :monto, 0, :monto, NOW()
                )
            """), {
                "pd": pd_val, "pkca": pkcuentaahorro, "mon": cat.mon, 
                "pkcli": sol.pkcliente, "ag": cat.ag, "monto": monto
            })
    except Exception as e:
        db.rollback()
        return {"error": f"Error acreditando a cuenta de ahorros: {str(e)}"}
    
    # 7. COMMIT Y RETORNO
    try:
        db.commit()
        return {
            "success": True,
            "codcuentacredito": cc.codcuentacredito,
            "monto_desembolsado": monto,
            "cuenta_ahorros_acreditada": ca.codcuentaahorro if ca else None,
            "plazo_meses": plazo,
            "fecha_desembolso": hoy.date().isoformat()
        }
    except Exception as e:
        db.rollback()
        return {"error": f"Error finalizando desembolso: {str(e)}"}
