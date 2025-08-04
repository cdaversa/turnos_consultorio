from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from datetime import datetime, timedelta
import json, os, smtplib, sqlite3, pytz
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ====== FUNCION DE FECHA CON ZONA HORARIA ======
def fecha_hoy():
    tz = pytz.timezone("America/Argentina/Buenos_Aires")
    return datetime.now(tz).date()

# ====== CONFIGURACION INICIAL ======

EMAIL_USER = "daversa1988@gmail.com"
EMAIL_PASS = "eiiy veto dopc jprm"  # ⚠️ Contraseña de aplicación de Gmail

app = Flask(__name__)
app.secret_key = 'clave_secreta_admin'

DB_FILE = "turnos.db"
CONFIG_FILE = 'config.json'
ADMIN_PASSWORD = 'admin123'

HORARIOS_ATENCION = {
    'lunes': ('10:00', '17:00'),
    'martes': ('10:00', '17:00'),
    'miércoles': ('10:00', '17:00'),
    'jueves': ('10:00', '17:00'),
    'viernes': ('10:00', '17:00'),
    'sábado': ('10:00', '13:00')
}

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

# ====== CREAR CONFIG SI NO EXISTE ======
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(CONFIG_DEFAULT, f, indent=2, ensure_ascii=False)

# ====== INICIALIZAR DB ======
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS turnos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dni TEXT,
        nombre TEXT,
        telefono TEXT,
        email TEXT,
        fecha TEXT,
        hora TEXT,
        estado TEXT
    )""")
    conn.commit()
    conn.close()

init_db()

# ====== FUNCIONES DB ======
def cargar_turnos():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT dni,nombre,telefono,email,fecha,hora,estado FROM turnos")
    datos = [dict(r) for r in c.fetchall()]
    conn.close()
    return datos

def agregar_turno(turno):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""INSERT INTO turnos (dni,nombre,telefono,email,fecha,hora,estado)
                 VALUES (?,?,?,?,?,?,?)""",
              (turno['dni'], turno['nombre'], turno['telefono'], turno['email'],
               turno['fecha'], turno['hora'], turno['estado']))
    conn.commit()
    conn.close()

def borrar_turno_db(dni, fecha, hora):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM turnos WHERE dni=? AND fecha=? AND hora=?", (dni, fecha, hora))
    conn.commit()
    conn.close()

def actualizar_estado_turno(dni, fecha, hora, estado):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE turnos SET estado=? WHERE dni=? AND fecha=? AND hora=?", (estado, dni, fecha, hora))
    conn.commit()
    conn.close()

# ====== CONFIG ======
def cargar_config():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def guardar_config(cfg):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ====== EMAIL ======
def get_smtp_config():
    cfg = cargar_config()
    return cfg.get('smtp_email', EMAIL_USER), cfg.get('smtp_password', EMAIL_PASS)

def enviar_email(destinatario, fecha, hora, nombre, telefono=None, dni=None, copia_admin=False):
    asunto = "✅ Confirmación de Turno - KL Dental" if not copia_admin else "📢 Nuevo Turno Reservado - KL Dental"
    cuerpo = (f"Hola {nombre}, su turno ha sido reservado para el día {fecha} a las {hora}."
              if not copia_admin else
              f"Se reservó un turno para:\n👤 {nombre}\n🆔 {dni}\n📞 {telefono}\n📅 {fecha} ⏰ {hora}")
    smtp_user, smtp_pass = get_smtp_config()
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = destinatario if not copia_admin else smtp_user
    msg["Subject"] = asunto
    msg.attach(MIMEText(cuerpo, "plain"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, msg["To"], msg.as_string())
    except Exception as e:
        print("❌ Error enviando email:", e)

def enviar_email_cancelacion(destinatario, fecha, hora, nombre):
    smtp_user, smtp_pass = get_smtp_config()
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = destinatario
    msg["Subject"] = "❌ Cancelación de Turno - KL Dental"
    msg.attach(MIMEText(f"Hola {nombre}, su turno para {fecha} a las {hora} ha sido cancelado.", "plain"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, destinatario, msg.as_string())
    except Exception as e:
        print("❌ Error email cancelación:", e)

# ====== FUNCIONES DE TURNOS (FERIADOS, VACACIONES, HORARIOS) ======
def es_feriado(fecha):
    return fecha in cargar_config().get("feriados", [])

def es_vacaciones(fecha):
    cfg = cargar_config()
    f = datetime.strptime(fecha, "%Y-%m-%d").date()
    for r in cfg.get("vacaciones", []):
        try:
            i = datetime.strptime(r["inicio"], "%Y-%m-%d").date()
            fn = datetime.strptime(r["fin"], "%Y-%m-%d").date()
            if i <= f <= fn: return True
        except: continue
    return False

def generar_turnos_disponibles(fecha):
    if es_feriado(fecha) or es_vacaciones(fecha): return []
    cfg = cargar_config()
    horarios_cfg = cfg.get('horarios_atencion', {})
    intervalo = cfg.get('intervalo_turnos', 15)
    dia = datetime.strptime(fecha, '%Y-%m-%d').strftime('%A').lower()
    dias_map = {'monday':'lunes','tuesday':'martes','wednesday':'miércoles','thursday':'jueves','friday':'viernes','saturday':'sábado','sunday':'domingo'}
    dia = dias_map.get(dia,'')
    if dia not in horarios_cfg: return []
    h = horarios_cfg[dia]
    if len(h)>2 and not h[2]: return []
    inicio, fin = h[0], h[1]
    hora = datetime.strptime(f"{fecha} {inicio}", "%Y-%m-%d %H:%M")
    hf = datetime.strptime(f"{fecha} {fin}", "%Y-%m-%d %H:%M")
    horarios = []
    while hora < hf:
        horarios.append(hora.strftime('%H:%M'))
        hora += timedelta(minutes=intervalo)
    ocupados = [t['hora'] for t in cargar_turnos() if t['fecha']==fecha]
    return [x for x in horarios if x not in ocupados]

# ====== TODAS LAS RUTAS ORIGINALES ======
@app.route('/')
def index(): return render_template('index.html')

@app.route('/obtener_horarios', methods=['POST'])
def obtener_horarios(): return jsonify(generar_turnos_disponibles(request.form['fecha']))

@app.route('/reservar', methods=['POST'])
def reservar():
    t = dict(dni=request.form['dni'], nombre=request.form['nombre'], telefono=request.form['telefono'],
             email=request.form['email'], fecha=request.form['fecha'], hora=request.form['hora'], estado='reservado')
    if any(x['fecha']==t['fecha'] and x['hora']==t['hora'] for x in cargar_turnos()):
        return 'Turno ya reservado',400
    agregar_turno(t)
    enviar_email(t['email'],t['fecha'],t['hora'],t['nombre'])
    enviar_email(t['email'],t['fecha'],t['hora'],t['nombre'],t['telefono'],t['dni'],copia_admin=True)
    return render_template("confirmacion.html",fecha=t['fecha'],hora=t['hora'])

# ✅ Todas las demás rutas (panel_admin, ver_turnos, borrar_turno, cancelar, configuracion, etc.)  
# funcionan igual, solo reemplazan `guardar_turnos` / `turnos.append` / `turnos = [...]` por las funciones DB.

@app.route('/panel_admin', methods=['GET','POST'])
def panel_admin():
    if request.method=='POST':
        if request.form.get('password')==cargar_config().get('admin_password',ADMIN_PASSWORD):
            session['admin']=True
            return render_template('panel_admin.html',logged=True)
        return render_template('panel_admin_login.html',error='Clave incorrecta')
    return render_template('panel_admin.html',logged=True) if session.get('admin') else render_template('panel_admin_login.html')

@app.route('/logout')
def logout(): session.pop('admin',None); return redirect(url_for('panel_admin'))

@app.route('/ver_turnos')
def ver_turnos():
    if not session.get('admin'): return redirect(url_for('panel_admin'))
    f = request.args.get('fecha')
    ts = cargar_turnos()
    if f is None: f=fecha_hoy().strftime('%Y-%m-%d'); ts=[t for t in ts if t['fecha']==f]
    elif f!="all": ts=[t for t in ts if t['fecha']==f]
    ts = sorted(ts,key=lambda x:(x['fecha'],x['hora']))
    return render_template('admin.html',turnos=ts,fecha_filtro=f)

@app.route('/borrar_turno',methods=['POST'])
def borrar_turno():
    if not session.get('admin'): return 'No autorizado',403
    borrar_turno_db(request.form['dni'],request.form['fecha'],request.form['hora'])
    return redirect(url_for('ver_turnos'))

@app.route('/cancelar',methods=['GET','POST'])
def cancelar():
    ts=[]; dni=''
    if request.method=='POST':
        dni=request.form['dni']; ts=[t for t in cargar_turnos() if t['dni']==dni]
    return render_template('cancelar.html',turnos=ts,dni=dni)

@app.route('/cancelar_turno',methods=['POST'])
def cancelar_turno():
    dni,fecha,hora=request.form['dni'],request.form['fecha'],request.form['hora']
    ts=cargar_turnos(); t=next((x for x in ts if x['dni']==dni and x['fecha']==fecha and x['hora']==hora),None)
    borrar_turno_db(dni,fecha,hora)
    if t and t.get('email'): enviar_email_cancelacion(t['email'],fecha,hora,t['nombre'])
    return redirect(url_for('cancelar'))

@app.route('/configuracion',methods=['GET','POST'])
def configuracion():
    if not session.get('admin'): return redirect(url_for('panel_admin'))
    cfg=cargar_config()
    if request.method=='POST':
        a=request.form.get('accion')
        if a=='cambiar_clave': cfg['admin_password']=request.form['nueva_clave']
        elif a=='cambiar_clave_profesional': cfg['profesional_password']=request.form['nueva_clave_profesional']
        elif a=='guardar_horarios':
            n={}; 
            for d in ['lunes','martes','miércoles','jueves','viernes','sábado','domingo']:
                n[d]=[request.form.get(f'desde_{d}','10:00'),request.form.get(f'hasta_{d}','17:00'),f"activo_{d}" in request.form]
            cfg['horarios_atencion']=n; cfg['intervalo_turnos']=int(request.form.get('intervalo_turnos','15'))
        elif a=='guardar_smtp':
            cfg['smtp_email']=request.form['smtp_email']; cfg['smtp_password']=request.form['smtp_password']
        elif a=='guardar_feriados':
            cfg['feriados']=[f for f in request.form.getlist('feriados') if f]
            ini=request.form.getlist('vacaciones_inicio'); fin=request.form.getlist('vacaciones_fin'); vac=[]
            for i in range(len(ini)):
                if ini[i] and fin[i]: vac.append({"inicio":ini[i],"fin":fin[i]})
            cfg['vacaciones']=vac
        guardar_config(cfg)
    return render_template('configuracion.html',horarios=cfg['horarios_atencion'],intervalo=cfg['intervalo_turnos'],email_smtp=cfg['smtp_email'],pass_smtp=cfg['smtp_password'],cfg=cfg)

@app.route('/dias_disponibles')
def dias_disponibles():
    h=fecha_hoy(); r=365; f=set(); horarios=cargar_config()['horarios_atencion']
    m={'monday':'lunes','tuesday':'martes','wednesday':'miércoles','thursday':'jueves','friday':'viernes','saturday':'sábado','sunday':'domingo'}
    for i in range(r):
        fd=(h+timedelta(days=i)).strftime('%Y-%m-%d'); d=m[(h+timedelta(days=i)).strftime('%A').lower()]
        if d in horarios and generar_turnos_disponibles(fd): f.add(fd)
    return jsonify(sorted(list(f)))

@app.route('/asignar_turno',methods=['POST'])
def asignar_turno():
    if not session.get('admin'): return redirect(url_for('panel_admin'))
    t=dict(dni=request.form['dni'],nombre=request.form['nombre'],telefono=request.form['telefono'],email=request.form['email'],fecha=request.form['fecha'],hora=request.form['hora'],estado='reservado')
    if any(x['fecha']==t['fecha'] and x['hora']==t['hora'] for x in cargar_turnos()): return "⚠️ Ese turno ya está reservado",400
    agregar_turno(t); enviar_email(t['email'],t['fecha'],t['hora'],t['nombre']); enviar_email(t['email'],t['fecha'],t['hora'],t['nombre'],t['telefono'],t['dni'],copia_admin=True)
    return redirect(url_for('ver_turnos'))

@app.route("/marcar_en_sala",methods=["POST"])
def marcar_en_sala(): actualizar_estado_turno(request.form["dni"],request.form["fecha"],request.form["hora"],'en_sala'); return jsonify({"status":"ok"})

@app.route('/marcar_atendido',methods=['POST'])
def marcar_atendido(): actualizar_estado_turno(request.form['dni'],request.form['fecha'],request.form['hora'],'atendido'); return jsonify({"success":True})

@app.route('/api/turnos_dia')
def api_turnos_dia():
    f=request.args.get('fecha'); ts=cargar_turnos()
    for x in ts:
        if x['estado'] not in ['reservado','en_sala','atendido']: actualizar_estado_turno(x['dni'],x['fecha'],x['hora'],'reservado')
    ts=sorted([x for x in ts if not f or x['fecha']==f],key=lambda y:(y['fecha'],y['hora']))
    return jsonify(ts)

@app.route('/profesional',methods=['GET','POST'])
def profesional():
    if not session.get('profesional'): return redirect(url_for('profesional_login'))
    f=request.args.get('fecha',fecha_hoy().strftime('%Y-%m-%d'))
    return render_template('profesional.html',turnos=sorted([t for t in cargar_turnos() if t['fecha']==f],key=lambda x:x['hora']),fecha=f)

@app.route('/profesional_login',methods=['GET','POST'])
def profesional_login():
    if request.method=='POST':
        if request.form.get('password')==cargar_config().get('profesional_password','prof123'):
            session['profesional']=True; return redirect(url_for('profesional'))
        return render_template('profesional_login.html',error='Clave incorrecta')
    if session.get('profesional'): return redirect(url_for('profesional'))
    return render_template('profesional_login.html')

@app.route('/logout_profesional')
def logout_profesional(): session.pop('profesional',None); return redirect(url_for('profesional_login'))

if __name__=='__main__': app.run(debug=True)
