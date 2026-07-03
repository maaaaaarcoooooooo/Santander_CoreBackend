"""
Repositorio de evaluación y desembolso de solicitudes — MPR-003-CRE (actividades 11, 16, 45-48).

- registrar_ingreso: fuente de ingreso del cliente (fclientefuenteingreso).
- registrar_evaluacion: cabecera (devaluacion) + detalle (fevalconsumo|fevalmicroactivo).
- desembolsar: 6-paso completo:
  1. Crear cuenta de crédito (dcuentacredito)
  2. Obtener catálogos
  3. Registrar movimiento DESEMBOLSO en foperaciones (crédito)
  4. Insertar en fagcuentacredito (cartera - CREA EL PRÉSTAMO VISIBLE)
  5. Generar cronograma de cuotas (fplanpagomes)
  6. Acreditar dinero a cuenta de ahorros del cliente
"""
from datetime import datetime, date as date_
import calendar
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
    Desembolsa un crédito aprobado en 6 pasos (CRÍTICO: todos en una transacción).
    
    PASO 1: Crear cuenta de crédito (dcuentacredito)
    PASO 2: Obtener catálogos necesarios
    PASO 3: Registrar movimiento DESEMBOLSO en foperaciones (vinculado a crédito)
    PASO 4: Insertar en fagcuentacredito (cartera - AQUÍ APARECE EL PRÉSTAMO)
    PASO 5: Generar cronograma de cuotas (fplanpagomes)
    PASO 6: Acreditar dinero a cuenta de ahorros del cliente
    """
    if not sol or not sol.montoaprobadocredito and not sol.montosolicitudcredito:
        return {"error": "Solicitud inválida o sin monto"}
    
    monto = float(sol.montoaprobadocredito or sol.montosolicitudcredito or 0)
    if monto <= 0:
        return {"error": "Monto debe ser > 0"}
    
    plazo = int(sol.plazosolicitudcredito or sol.nrocuotasolicitud or 12)
    nrodias = plazo * 30
    hoy = datetime.utcnow()
    pd_val = int(hoy.strftime("%Y%m%d"))
    periodomes = int(hoy.strftime("%Y%m"))

    # ===== PASO 1: CREAR CUENTA DE CRÉDITO =====
    try:
        cc = db.execute(text("""
            INSERT INTO dcuentacredito 
                (pkcuentacredito, codcuentacredito, pkcliente, nrocronograma, fecultactualizacion)
            VALUES (nextval('dcuentacredito_pkcuentacredito_seq'),
                    'CRD' || LPAD(currval('dcuentacredito_pkcuentacredito_seq')::text, 7, '0'),
                    :pkcli, 1, NOW())
            RETURNING pkcuentacredito, codcuentacredito
        """), {"pkcli": sol.pkcliente}).fetchone()
        if not cc:
            db.rollback()
            return {"error": "Error: No se creó la cuenta de crédito"}
        pkcc = cc.pkcuentacredito
    except Exception as e:
        db.rollback()
        return {"error": f"PASO 1 - Crear cuenta: {str(e)}"}

    # ===== PASO 2: OBTENER CATÁLOGOS =====
    try:
        cat = db.execute(text("""
            SELECT 
                (SELECT pkconceptooperacion FROM dconceptooperacion WHERE codconceptooperacion='DCAP' LIMIT 1) as con_dcap,
                (SELECT pkconceptooperacion FROM dconceptooperacion WHERE codconceptooperacion='DEP' LIMIT 1) as con_dep,
                (SELECT pktipooperacion FROM dtipooperacion WHERE codtipooperacion='CRE' LIMIT 1) as tipo_cre,
                (SELECT pkmediopago FROM dmediopago WHERE codmediopago='WEB' LIMIT 1) as medio,
                (SELECT pkcanaltransaccional FROM dcanaltransaccional WHERE codcanaltransaccional='WEB' LIMIT 1) as canal,
                (SELECT pkcondicioncontable FROM dcondicioncontable WHERE codcondicioncontable='01' LIMIT 1) as cond,
                (SELECT pkmoneda FROM dmoneda LIMIT 1) as mon,
                (SELECT MIN(pkproducto) FROM dproducto) as prod,
                (SELECT MIN(pkagencia) FROM dagencia) as ag,
                (SELECT pkestadocredito FROM destadocredito WHERE codestadocredito='01' LIMIT 1) as est,
                (SELECT MIN(pkactividadeconomica) FROM dactividadeconomica) as act
        """)).fetchone()
        
        if not cat or not cat.con_dcap:
            db.rollback()
            return {"error": "PASO 2 - Faltan catálogos en BD"}
    except Exception as e:
        db.rollback()
        return {"error": f"PASO 2 - Obtener catálogos: {str(e)}"}

    # ===== PASO 3: REGISTRAR MOVIMIENTO DESEMBOLSO EN FOPERACIONES =====
    try:
        db.execute(text("""
            INSERT INTO foperaciones
                (codtipkar, codkardex, pkcuentacredito, pkconceptooperacion, pktipooperacion,
                 pkmediopago, pkcanaltransaccional, pkmoneda, pkcondicioncontable, pkproducto,
                 pkagenciaorigen, montooperacion, montopagoconcepto, codtipoegresoingreso,
                 fechahoraoperacion, periododia, codusuope, fecultactualizacion)
            VALUES ('CR', 'DESEMB-' || :pkcc, :pkcc, :con_dcap, :tipo_cre, :medio, :canal, :mon, :cond, :prod,
                    :ag, :monto, :monto, 'I', :fh, :pd, 'CORE', NOW())
        """), {"pkcc": pkcc, "con_dcap": cat.con_dcap, "tipo_cre": cat.tipo_cre,
               "medio": cat.medio, "canal": cat.canal, "mon": cat.mon, "cond": cat.cond,
               "prod": cat.prod, "ag": cat.ag, "monto": monto, "fh": hoy, "pd": pd_val})
    except Exception as e:
        db.rollback()
        return {"error": f"PASO 3 - Movimiento desembolso: {str(e)}"}

    # ===== PASO 4: INSERTAR EN FAGCUENTACREDITO (AQUÍ APARECE EL PRÉSTAMO) =====
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
                'MEN', 'LIN', 0, 0, 0, 0,
                0, (NOW() + INTERVAL '1 year')::date, NOW()::date, NOW()::date,
                1.0, 1, 'N', 'N', 'N', 'N', 'N', :act, :monto, 0, 'N',
                0, 1, 1, :pkcli, 1, :cond, 'N', 'N', 'S', 1, 1, NULL,
                :monto, 0, 0, 0, 0, :monto, 0, 0, 0,
                :monto, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, :monto, :ag, NULL, NULL, 1, NULL, NOW()
            )
        """), {
            "periodomes": periodomes, "pkcc": pkcc, "pksol": sol.pksolicitud, "est": cat.est,
            "plazo": plazo, "nrodias": nrodias, "monto": monto, "prod": cat.prod,
            "mon": cat.mon, "act": cat.act, "pkcli": sol.pkcliente, "cond": cat.cond, "ag": cat.ag
        })
    except Exception as e:
        db.rollback()
        return {"error": f"PASO 4 - Insert fagcuentacredito: {str(e)}"}

    # ===== PASO 5: GENERAR CRONOGRAMA DE CUOTAS =====
    try:
        cuota_base = round(monto / plazo, 2)
        cuota_ultima = round(monto - cuota_base * (plazo - 1), 2)
        codplanpago = "PLAN" + str(pkcc).zfill(7)

        for n in range(1, plazo + 1):
            monto_cuota = cuota_base if n < plazo else cuota_ultima
            monto_saldo = round(monto - cuota_base * (n - 1), 2) if n < plazo else 0.0
            
            # Calcular fecha de vencimiento
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
                    NULL, NULL, :pkcli, :cond, NULL,
                    :ag, NULL, NULL, 1, NULL,
                    NULL, NULL,
                    '01', NULL,
                    :fecha_venc, NULL,
                    :montocuota, :montosaldo, 0,
                    0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                    :montosaldo, 0, :montocuota, :monto_total,
                    0, 0, 0, 0, 0, NOW()
                )
            """), {
                "periodomes": periodo_cuota, "pkcc": pkcc, "codplan": codplanpago, "nrocuota": n,
                "pksol": sol.pksolicitud, "est": cat.est, "prod": cat.prod, "mon": cat.mon,
                "act": cat.act, "pkcli": sol.pkcliente, "cond": cat.cond, "ag": cat.ag,
                "fecha_venc": fecha_venc, "montocuota": monto_cuota, "montosaldo": monto_saldo,
                "monto_total": monto
            })
    except Exception as e:
        db.rollback()
        return {"error": f"PASO 5 - Cronograma: {str(e)}"}

    # ===== PASO 6: ACREDITAR A CUENTA DE AHORROS =====
    try:
        # Obtener o crear cuenta de ahorros
        ca = db.execute(text("""
            SELECT pkcuentaahorro, codcuentaahorro FROM dcuentaahorro WHERE pkcliente = :pkcli LIMIT 1
        """), {"pkcli": sol.pkcliente}).fetchone()

        if not ca:
            # Crear nueva cuenta
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

        pkca = ca.pkcuentaahorro
        
        # 6a. Registrar movimiento de ABONO en foperaciones
        db.execute(text("""
            INSERT INTO foperaciones
                (codtipkar, codkardex, pkcuentaahorro, pkconceptooperacion, pktipooperacion,
                 pkmediopago, pkcanaltransaccional, pkmoneda, pkcondicioncontable, pkproducto,
                 pkagenciaorigen, montooperacion, montopagoconcepto, codtipoegresoingreso,
                 fechahoraoperacion, periododia, codusuope, fecultactualizacion)
            VALUES ('CR', 'ABONO-DESEMB-' || :pkcc, :pkca, :con_dep, :tipo_cre, :medio, :canal, :mon, :cond, :prod,
                    :ag, :monto, :monto, 'I', :fh, :pd, 'CORE', NOW())
        """), {"pkcc": pkcc, "pkca": pkca, "con_dep": cat.con_dep, "tipo_cre": cat.tipo_cre,
               "medio": cat.medio, "canal": cat.canal, "mon": cat.mon, "cond": cat.cond,
               "prod": cat.prod, "ag": cat.ag, "monto": monto, "fh": hoy, "pd": pd_val})

        # 6b. Actualizar o crear balance en fcuentaahorro
        result = db.execute(text("""
            UPDATE fcuentaahorro
            SET montosaldocapitaltotal = montosaldocapitaltotal + :monto,
                montosaldodisponible_ac = COALESCE(montosaldodisponible_ac, 0) + :monto,
                montosaldocontable_ac = COALESCE(montosaldocontable_ac, 0) + :monto,
                fecultactualizacion = NOW()
            WHERE pkcuentaahorro = :pkca
            RETURNING pkcuentaahorro
        """), {"pkca": pkca, "monto": monto})

        if result.fetchone() is None:
            # Si no hay fila, crear snapshot inicial
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
                    (SELECT MIN(pkproductoahorro) FROM dproductoahorro),
                    :mon,
                    (SELECT pktipocuentaahorro FROM dtipocuentaahorro WHERE codtipocuentaahorro='AH' LIMIT 1),
                    (SELECT MIN(pktipotasaahorro) FROM dtipotasaahorro),
                    :pkcli, 1, 1, 1, :ag, 1,
                    :monto, 0, 0, NOW()::date, 0, 0, 0, 1, 1,
                    'N', 'N', 'N', 0, NOW()::date, 'S', 'N', 'N', 'N',
                    :monto, 0, :monto, NOW()
                )
            """), {"pd": pd_val, "pkca": pkca, "mon": cat.mon, "pkcli": sol.pkcliente, "ag": cat.ag, "monto": monto})

    except Exception as e:
        db.rollback()
        return {"error": f"PASO 6 - Acreditar ahorros: {str(e)}"}

    # ===== COMMIT Y RETORNO EXITOSO =====
    try:
        db.commit()
        return {
            "success": True,
            "codcuentacredito": cc.codcuentacredito,
            "monto_desembolsado": monto,
            "cuenta_ahorros_acreditada": ca.codcuentaahorro,
            "plazo_meses": plazo,
            "fecha_desembolso": hoy.date().isoformat()
        }
    except Exception as e:
        db.rollback()
        return {"error": f"Commit final: {str(e)}"}
