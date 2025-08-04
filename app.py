from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from datetime import datetime, timedelta
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

EMAIL_USER = "daversa1988@gmail.com"
EMAIL_PASS = "eiiy veto dopc jprm"  # ⚠️ Contraseña de aplicación de Gmail

app = Flask(__name__)
app.secret_key = 'clave_secreta_admin'

TURNOS_FILE = 'turnos.json'
ADMIN_PASSWORD = 'admin123'

HORARIOS_ATENCION = {
    'lunes': ('10:00', '17:00'),
    'martes': ('10:00', '17:00'),
    'miércoles': ('10:00', '17:00'),
    'jueves': ('10:00', '17:00'),
    'viernes': ('10:00', '17:00'),
    'sábado': ('10:00', '13:00')
}

CONFIG_FILE = 'config.json'
CONFIG_DEFAULT = {
    "admin_password": ADMIN_PASSWORD,
    "profesional_password": "prof123",
    "intervalo_turnos": 15,
    "horarios_atencion": {d: [h[0], h[1], True] for d, h in HORARIOS_ATENCION.items()},
    "smtp_email": EMAIL_USER,
    "smtp_password": EMAIL_PASS,
    "feriados": [],
    "vacaciones": []
}

# ====== CREACIÓN AUTOMÁTICA DE CONFIG.JSON ======
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(CONFIG_DEFAULT, f, indent=2, ensure_ascii=False)
else:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        cfg_temp = json.load(f)
    cambios = False
    for clave, valor in CONFIG_DEFAULT.items():
        if clave not in cfg_temp:
            cfg_temp[clave] = valor
            cambios = True
    if cambios:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg_temp, f, indent=2, ensure_ascii=False)

# ====== FUNCIONES AUXILIARES ======

def cargar_turnos():
    if not os.path.exists(TURNOS_FILE):
        guardar_turnos([])
        return []
    try:
        with open(TURNOS_FILE, 'r', encoding='utf-8') as f:
            contenido = f.read().strip()
            if not contenido:
                guardar_turnos([])
                return []
            return json.loads(contenido)
    except json.JSONDecodeError:
        guardar_turnos([])
        return []

def guardar_turnos(turnos):
    with open(TURNOS_FILE, 'w') as f:
        json.dump(turnos, f, indent=2)

def cargar_config():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def guardar_config(cfg):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def get_smtp_config():
    cfg = cargar_config()
    return cfg.get('smtp_email', EMAIL_USER), cfg.get('smtp_password', EMAIL_PASS)

# ====== VERIFICAR SI UNA FECHA ES FERIADO O VACACIONES ======

def es_feriado(fecha):
    cfg = cargar_config()
    return fecha in cfg.get("feriados", [])

def es_vacaciones(fecha):
    cfg = cargar_config()
    fecha_dt = datetime.strptime(fecha, "%Y-%m-%d").date()
    for rango in cfg.get("vacaciones", []):
        try:
            inicio = datetime.strptime(rango["inicio"], "%Y-%m-%d").date()
            fin = datetime.strptime(rango["fin"], "%Y-%m-%d").date()
            if inicio <= fecha_dt <= fin:
                return True
        except Exception:
            continue
    return False

# ====== GENERAR TURNOS DISPONIBLES ======

def generar_turnos_disponibles(fecha):
    if es_feriado(fecha) or es_vacaciones(fecha):
        return []

    cfg = cargar_config()
    horarios_cfg = cfg.get('horarios_atencion', {})
    intervalo = cfg.get('intervalo_turnos', 15)

    fecha_dt = datetime.strptime(fecha, '%Y-%m-%d')
    dia_nombre = fecha_dt.strftime('%A').lower()
    dias_map = {
        'monday': 'lunes', 'tuesday': 'martes', 'wednesday': 'miércoles',
        'thursday': 'jueves', 'friday': 'viernes', 'saturday': 'sábado', 'sunday': 'domingo'
    }
    dia = dias_map.get(dia_nombre, '')

    if dia not in horarios_cfg and dia in HORARIOS_ATENCION:
        horarios_cfg[dia] = [HORARIOS_ATENCION[dia][0], HORARIOS_ATENCION[dia][1], True]

    if dia in horarios_cfg:
        valores = horarios_cfg[dia]
        if len(valores) > 2 and valores[2] is False:
            return []
        inicio, fin = valores[:2]
    else:
        return []

    hora_inicio = datetime.strptime(f"{fecha} {inicio}", "%Y-%m-%d %H:%M")
    hora_fin = datetime.strptime(f"{fecha} {fin}", "%Y-%m-%d %H:%M")
    horarios = []
    while hora_inicio < hora_fin:
        horarios.append(hora_inicio.strftime('%H:%M'))
        hora_inicio += timedelta(minutes=intervalo)

    turnos_ocupados = [t['hora'] for t in cargar_turnos() if t['fecha'] == fecha]
    return [h for h in horarios if h not in turnos_ocupados]

# ====== FUNCIONES DE EMAIL ======

def enviar_email(destinatario, fecha, hora, nombre, telefono=None, dni=None, copia_admin=False):
    if copia_admin:
        asunto = "📢 Nuevo Turno Reservado - KL Dental"
        cuerpo = (f"Se ha reservado un nuevo turno.\n\n"
                  f"📌 Datos del paciente:\n"
                  f"👤 Nombre: {nombre}\n"
                  f"🆔 DNI: {dni}\n"
                  f"📞 Teléfono: {telefono}\n"
                  f"📧 Email: {destinatario}\n\n"
                  f"📅 Fecha: {fecha}\n⏰ Hora: {hora}")
        destinatario_envio = get_smtp_config()[0]  # ✅ ahora se toma dinámico
    else:
        asunto = "✅ Confirmación de Turno - KL Dental"
        cuerpo = (f"Hola {nombre},\n\n"
                  f"Su turno ha sido reservado para el día {fecha} a las {hora}.\n"
                  f"KL Dental\n"
                  f"Zapiola 1180 - Bernal Oeste\n"
                  f"📞 Tel: 11-2404-9424")
        destinatario_envio = destinatario

    msg = MIMEMultipart()
    smtp_user, smtp_pass = get_smtp_config()  # ✅ ahora lee email y pass del JSON
    msg["From"] = smtp_user
    msg["To"] = destinatario_envio
    msg["Subject"] = asunto
    msg.attach(MIMEText(cuerpo, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, destinatario_envio, msg.as_string())
        print(f"📧 Email enviado a {destinatario_envio}")
    except Exception as e:
        print("❌ Error enviando email:", e)


def enviar_email_cancelacion(destinatario, fecha, hora, nombre):
    smtp_user, smtp_pass = get_smtp_config()
    asunto = "❌ Cancelación de Turno - KL Dental"
    cuerpo = (f"Hola {nombre},\n\nSu turno para el día {fecha} a las {hora} ha sido cancelado correctamente.\n"
              f"Si desea solicitar uno nuevo, puede hacerlo desde nuestra web.\n\n"
              f"KL Dental\nZapiola 1180 - Bernal Oeste\n📞 Tel: 11-2404-9424")

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = destinatario
    msg["Subject"] = asunto
    msg.attach(MIMEText(cuerpo, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, destinatario, msg.as_string())
        print(f"📧 Email de cancelación enviado a {destinatario}")
    except Exception as e:
        print("❌ Error enviando email de cancelación:", e)

# ====== RUTAS PRINCIPALES ======

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/obtener_horarios', methods=['POST'])
def obtener_horarios():
    fecha = request.form['fecha']
    disponibles = generar_turnos_disponibles(fecha)
    return jsonify(disponibles)

@app.route('/reservar', methods=['POST'])
def reservar():
    nuevo_turno = {
    'dni': request.form['dni'],
    'nombre': request.form['nombre'],
    'telefono': request.form['telefono'],
    'email': request.form['email'],
    'fecha': request.form['fecha'],
    'hora': request.form['hora'],
    'estado': 'reservado'   # ✅ agregado
}

    turnos = cargar_turnos()
    if any(t['fecha'] == nuevo_turno['fecha'] and t['hora'] == nuevo_turno['hora'] for t in turnos):
        return 'Turno ya reservado', 400

    turnos.append(nuevo_turno)
    guardar_turnos(turnos)

    # ✅ 1) Email al paciente
    enviar_email(nuevo_turno['email'], nuevo_turno['fecha'], nuevo_turno['hora'], nuevo_turno['nombre'])

    # ✅ 2) Email a vos (administrador) con todos los datos
    enviar_email(
        destinatario=nuevo_turno['email'], 
        fecha=nuevo_turno['fecha'], 
        hora=nuevo_turno['hora'], 
        nombre=nuevo_turno['nombre'], 
        telefono=nuevo_turno['telefono'], 
        dni=nuevo_turno['dni'], 
        copia_admin=True
    )

    # ✅ Mostrar confirmación
    return render_template("confirmacion.html", fecha=nuevo_turno['fecha'], hora=nuevo_turno['hora'])


@app.route('/panel_admin', methods=['GET', 'POST'])
def panel_admin():
    if request.method == 'POST':
        clave_guardada = cargar_config().get('admin_password', ADMIN_PASSWORD)  # ✅ lee desde config.json
        if request.form.get('password') == clave_guardada:
            session['admin'] = True
            return render_template('panel_admin.html', logged=True)
        else:
            return render_template('panel_admin_login.html', error='Clave incorrecta')
    return render_template('panel_admin.html', logged=True) if session.get('admin') else render_template('panel_admin_login.html')

@app.route('/logout')
def logout():
    session.pop('admin', None)
    return redirect(url_for('panel_admin'))

@app.route('/ver_turnos')
def ver_turnos():
    if not session.get('admin'):
        return redirect(url_for('panel_admin'))

    fecha_filtro = request.args.get('fecha')  # Puede ser None, fecha o 'all'
    turnos = cargar_turnos()

    if fecha_filtro is None:
        # ✅ Si no hay parámetro, filtra solo turnos del día actual
        fecha_filtro = datetime.today().strftime('%Y-%m-%d')
        turnos = [t for t in turnos if t['fecha'] == fecha_filtro]
    elif fecha_filtro != "all":
        # ✅ Si hay una fecha específica distinta de 'all', filtra esa fecha
        turnos = [t for t in turnos if t['fecha'] == fecha_filtro]
    # ✅ Si es 'all', no se aplica ningún filtro

    turnos = sorted(turnos, key=lambda x: (x['fecha'], x['hora']))
    return render_template('admin.html', turnos=turnos, fecha_filtro=fecha_filtro)

@app.route('/borrar_turno', methods=['POST'])
def borrar_turno():
    if not session.get('admin'):
        return 'No autorizado', 403

    dni = request.form['dni']
    fecha = request.form['fecha']
    hora = request.form['hora']

    turnos = [t for t in cargar_turnos() if not (t['dni'] == dni and t['fecha'] == fecha and t['hora'] == hora)]
    guardar_turnos(turnos)

    return redirect(url_for('ver_turnos'))

@app.route('/cancelar', methods=['GET', 'POST'])
def cancelar():
    turnos = []
    dni_buscado = ''
    if request.method == 'POST':
        dni_buscado = request.form['dni']
        turnos = [t for t in cargar_turnos() if t['dni'] == dni_buscado]
    return render_template('cancelar.html', turnos=turnos, dni=dni_buscado)

@app.route('/cancelar_turno', methods=['POST'])
def cancelar_turno():
    dni = request.form['dni']
    fecha = request.form['fecha']
    hora = request.form['hora']
    turnos = cargar_turnos()
    turno_a_cancelar = next((t for t in turnos if t['dni'] == dni and t['fecha'] == fecha and t['hora'] == hora), None)
    turnos = [t for t in turnos if not (t['dni'] == dni and t['fecha'] == fecha and t['hora'] == hora)]
    guardar_turnos(turnos)
    if turno_a_cancelar and turno_a_cancelar.get('email'):
        enviar_email_cancelacion(turno_a_cancelar['email'], fecha, hora, turno_a_cancelar.get('nombre', 'Paciente'))
    return redirect(url_for('cancelar'))

# ====== CONFIGURACIÓN ======

@app.route('/configuracion', methods=['GET', 'POST'])
def configuracion():
    if not session.get('admin'):
        return redirect(url_for('panel_admin'))

    cfg = cargar_config()

    if request.method == 'POST':
        accion = request.form.get('accion')
        if accion == 'cambiar_clave':
            cfg['admin_password'] = request.form['nueva_clave']
        elif accion == 'cambiar_clave_profesional':
            cfg['profesional_password'] = request.form['nueva_clave_profesional']
        elif accion == 'guardar_horarios':
            nuevos = {}
            for dia in ['lunes','martes','miércoles','jueves','viernes','sábado','domingo']:
                desde = request.form.get(f'desde_{dia}', '10:00')
                hasta = request.form.get(f'hasta_{dia}', '17:00')
                activo = f"activo_{dia}" in request.form
                nuevos[dia] = [desde, hasta, activo]
            cfg['horarios_atencion'] = nuevos
            cfg['intervalo_turnos'] = int(request.form.get('intervalo_turnos', '15'))
        elif accion == 'guardar_smtp':
            cfg['smtp_email'] = request.form.get('smtp_email')
            cfg['smtp_password'] = request.form.get('smtp_password')
        elif accion == 'guardar_feriados':
            # ✅ Guardar feriados
            feriados = request.form.getlist('feriados')
            feriados = [f for f in feriados if f]
            cfg['feriados'] = feriados

            # ✅ Guardar vacaciones
            inicios = request.form.getlist('vacaciones_inicio')
            fines = request.form.getlist('vacaciones_fin')
            vacaciones = []
            for i in range(len(inicios)):
                if inicios[i] and fines[i]:
                    vacaciones.append({"inicio": inicios[i], "fin": fines[i]})
            cfg['vacaciones'] = vacaciones

        guardar_config(cfg)

    return render_template('configuracion.html',
                           horarios=cfg.get('horarios_atencion', {}),
                           intervalo=cfg.get('intervalo_turnos', 15),
                           email_smtp=cfg.get('smtp_email', ''),
                           pass_smtp=cfg.get('smtp_password', ''),
                           cfg=cfg)

@app.route('/dias_disponibles')
def dias_disponibles():
    turnos = cargar_turnos()
    fechas_disponibles = set()
    cfg = cargar_config()
    horarios_cfg = cfg.get('horarios_atencion', HORARIOS_ATENCION)
    hoy = datetime.today().date()
    for i in range(60):
        fecha = (hoy + timedelta(days=i)).strftime('%Y-%m-%d')
        dia_nombre = (hoy + timedelta(days=i)).strftime('%A').lower()
        dia_map = {
            'monday':'lunes','tuesday':'martes','wednesday':'miércoles','thursday':'jueves',
            'friday':'viernes','saturday':'sábado','sunday':'domingo'
        }
        dia = dia_map.get(dia_nombre, '')
        if dia in horarios_cfg and generar_turnos_disponibles(fecha):
            fechas_disponibles.add(fecha)
    return jsonify(list(fechas_disponibles))

@app.route('/asignar_turno', methods=['POST'])
def asignar_turno():
    if not session.get('admin'):
        return redirect(url_for('panel_admin'))

    nuevo_turno = {
    'dni': request.form['dni'],
    'nombre': request.form['nombre'],
    'telefono': request.form['telefono'],
    'email': request.form['email'],
    'fecha': request.form['fecha'],
    'hora': request.form['hora'],
    'estado': 'reservado'   # ✅ agregado
}

    turnos = cargar_turnos()
    if any(t['fecha'] == nuevo_turno['fecha'] and t['hora'] == nuevo_turno['hora'] for t in turnos):
        return "⚠️ Ese turno ya está reservado", 400

    turnos.append(nuevo_turno)
    guardar_turnos(turnos)

    # ✅ Email al paciente
    enviar_email(nuevo_turno['email'], nuevo_turno['fecha'], nuevo_turno['hora'], nuevo_turno['nombre'])

    # ✅ Copia al administrador
    enviar_email(nuevo_turno['email'], nuevo_turno['fecha'], nuevo_turno['hora'], nuevo_turno['nombre'],
                 telefono=nuevo_turno['telefono'], dni=nuevo_turno['dni'], copia_admin=True)

    return redirect(url_for('ver_turnos'))

@app.route("/marcar_en_sala", methods=["POST"])
def marcar_en_sala():
    dni = request.form["dni"]
    fecha = request.form["fecha"]
    hora = request.form["hora"]

    marcar_turno_en_sala(dni, fecha, hora)

    # ✅ devolver JSON en lugar de redirigir
    return jsonify({"status": "ok"})

def marcar_turno_en_sala(dni, fecha, hora):
    turnos = cargar_turnos()
    for t in turnos:
        if t['dni'] == dni and t['fecha'] == fecha and t['hora'] == hora:
            t['estado'] = 'en_sala'
            break
    guardar_turnos(turnos)

@app.route('/marcar_atendido', methods=['POST'])
def marcar_atendido():
    dni = request.form['dni']
    fecha = request.form['fecha']
    hora = request.form['hora']

    turnos = cargar_turnos()
    for t in turnos:
        if t['dni'] == dni and t['fecha'] == fecha and t['hora'] == hora:
            t['estado'] = 'atendido'
    guardar_turnos(turnos)

    return jsonify({"success": True})

@app.route('/api/turnos_dia')
def api_turnos_dia():
    fecha = request.args.get('fecha')  # 👉 ahora no usa fecha por defecto
    turnos = cargar_turnos()

    # 🔹 Asegura siempre que cada turno tenga estado válido
    for t in turnos:
        if 'estado' not in t or t['estado'] not in ['reservado', 'en_sala', 'atendido']:
            t['estado'] = 'reservado'
    guardar_turnos(turnos)

    # 👉 Si hay filtro de fecha, lo aplica; si no, devuelve todos
    if fecha:
        turnos_filtrados = sorted([t for t in turnos if t['fecha'] == fecha], key=lambda x: x['hora'])
    else:
        turnos_filtrados = sorted(turnos, key=lambda x: (x['fecha'], x['hora']))

    return jsonify(turnos_filtrados)

# ====== PANEL PARA PROFESIONALES ======

@app.route('/profesional', methods=['GET', 'POST'])
def profesional():
    if not session.get('profesional'):
        return redirect(url_for('profesional_login'))

    fecha = request.args.get('fecha', datetime.today().strftime('%Y-%m-%d'))
    turnos = sorted([t for t in cargar_turnos() if t['fecha'] == fecha], key=lambda x: x['hora'])
    return render_template('profesional.html', turnos=turnos, fecha=fecha)

@app.route('/profesional_login', methods=['GET', 'POST'])
def profesional_login():
    if request.method == 'POST':
        clave_guardada = cargar_config().get('profesional_password', 'prof123')
        if request.form.get('password') == clave_guardada:
            session['profesional'] = True
            # ✅ Redirige para aplicar el filtro de fecha
            return redirect(url_for('profesional'))
        else:
            return render_template('profesional_login.html', error='Clave incorrecta')
    
    # ✅ Si ya está logueado, mandalo a la vista de profesional
    if session.get('profesional'):
        return redirect(url_for('profesional'))

    return render_template('profesional_login.html')

@app.route('/logout_profesional')
def logout_profesional():
    session.pop('profesional', None)
    return redirect(url_for('profesional_login'))

if __name__ == '__main__':
    app.run(debug=True)
