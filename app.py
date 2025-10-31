from flask import Flask, render_template, request, redirect, url_for, flash, session
import pymongo
import redis
import json
import os
from datetime import datetime

# Conexion a la base de datos mongo-------------------------------------------------------------
MONGO_URL = "mongodb://localhost:27017/"
MONGO_DB = "Proyecto2"
mongo_client = pymongo.MongoClient(MONGO_URL)
mongo_db = mongo_client[MONGO_DB]

# Conexion a Redis-----------------------------------------------------------------------------
redis_db = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
try:
    redis_db.ping()
    print("Redis OK")
except redis.exceptions.ConnectionError as e:
    print("Redis connection failed:", e)

# Configuracion de Flask------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = 'dev'

# Rutas de la aplicacion------------------------------------------------------------------------

# Pagina de inicio, renderiza el formulario de login/registro
@app.route('/')
def index():
    return render_template('login.html')

# Maneja el login, registro y reseteo de la base de datos
@app.route('/login', methods=['POST'])
def login():
    
    action = request.form.get('action')
    username = request.form.get('username')
    password = request.form.get('password')

    if action == 'login':
        if not username or not password:
            flash('Nombre de usuario y contraseña son requeridos', 'error')
            return redirect(url_for('index'))

        user = mongo_db['usuarios'].find_one({'username': username})
        if not user:
            flash('Credenciales inválidas', 'error')
            return redirect(url_for('index'))

        if password != user.get('password', ''):
            flash('Credenciales inválidas', 'error')
            return redirect(url_for('index'))

        
        session['user_id'] = str(user.get('_id'))
        session['username'] = user.get('username')
        session['role'] = user.get('role', 'user')

        if session['role'] == 'admin':
            return redirect(url_for('admin'))
        else:
            return redirect(url_for('user'))

    elif action == 'register':
        if not username or not password:
            flash('Nombre de usuario y contraseña son requeridos', 'error')
            return redirect(url_for('index'))
        if mongo_db['usuarios'].find_one({'username': username}):
            flash('Nombre de usuario ya existe', 'error')
            return redirect(url_for('index'))

        mongo_db['usuarios'].insert_one({'username': username, 'password': password, 'role': 'user'})

        session['user_id'] = str(mongo_db['usuarios'].find_one({'username': username}).get('_id'))
        session['username'] = username
        session['role'] = 'user'

        return redirect(url_for('user'))
    elif action == 'reset':
        mongo_db['usuarios'].delete_many({}) 
        mongo_db['concursantes'].delete_many({})
        mongo_db['votos_log'].delete_many({})
        redis_db.flushdb()

        current_dir = os.path.dirname(os.path.abspath(__file__))
        usuarios_path = os.path.join(current_dir, 'usuarios.json')
                
        if not os.path.exists(usuarios_path):
            usuarios_data = [{"username": "admin", "password": "password", "role": "admin"}]
        else:
            with open(usuarios_path, 'r') as f:
                usuarios_data = json.load(f)

        mongo_db['usuarios'].insert_many(usuarios_data)
        flash('La base de datos ha sido restablecida', 'info')
        return redirect(url_for('index'))

    return redirect(url_for('index'))

# Pagina de admin    
@app.route('/admin')
def admin():
    return render_template('admin.html')

# Ruta de cargar json de concursantes
@app.route('/load_json', methods=['POST'])
def load_json():
    file = request.files.get('concursantes_json')
    if not file:
        flash('No se ha seleccionado ningún archivo', 'error')
        return redirect(url_for('admin'))
    
    data = json.load(file)

    if not data:
        flash('El archivo JSON está vacío', 'error')
        return redirect(url_for('admin'))

    mongo_db['concursantes'].insert_many(data)
    flash('Concursantes cargados exitosamente', 'success')

    return redirect(url_for('admin'))

#Ruta de agregar concursante
@app.route('/add_concursante', methods=['POST'])
def add_concursante():
    nombre = request.form.get('nombre')
    categoria = request.form.get('categoria')
    foto = request.files.get('foto')
    
    if foto:
        filename = foto.filename
        fotos_folder = os.path.join(os.path.dirname(__file__), 'static\\fotos')
        try:            
            save_path = os.path.join(fotos_folder, filename)
            foto.save(save_path)
            most_recent = list(mongo_db['concursantes'].find().sort('id', -1).limit(1))
            mongo_db['concursantes'].insert_one({
                'id': (most_recent[0]['id'] + 1) if len(most_recent) > 0 else 1,
                'nombre': nombre,
                'categoria': categoria,
                'foto': filename,
                'votos_acumulados': 0
            })
        except Exception as e:
            print("Error al guardar la foto: ", e)
    flash('Concursante agregado exitosamente', 'success')
    return redirect(url_for('admin'))

# Pagina de usuario normal
@app.route('/user')
def user():
    user_id = session.get('user_id')
    concursantes = mongo_db['concursantes'].find({})
    cache_votos_usuario = {int(x) for x in redis_db.smembers(f"voted:{user_id}")}
    if cache_votos_usuario:
        return render_template('user.html', concursantes=concursantes, votos_usuario=cache_votos_usuario)
    else:
        
        historial_votos_usuario_cursor = mongo_db['votos_log'].find({'user_id':user_id},{'_id':0, 'concursante_id':1})
        historial_votos_usuario = {int(doc['concursante_id']) for doc in historial_votos_usuario_cursor}
        
        return render_template('user.html', concursantes=concursantes, votos_usuario=historial_votos_usuario)

@app.route('/user/add_vote/<int:concursante_id>', methods=['POST'])
def add_vote(concursante_id):
    user_id = session.get('user_id')
    if not user_id:
        flash('Debe iniciar sesión para votar', 'error')
        return redirect(url_for('index'))

    mongo_db['votos_log'].insert_one({'user_id':user_id,'concursante_id':concursante_id, 'timestamp': datetime.now()})

    return redirect(url_for('user'))


@app.route('/user/remove_vote/<int:concursante_id>', methods=['POST'])
def remove_vote(concursante_id):
    user_id = session.get('user_id')
    if not user_id:
        flash('Debe iniciar sesión para votar', 'error')
        return redirect(url_for('index'))

    mongo_db['votos_log'].delete_one({'user_id':user_id,'concursante_id':concursante_id})

    return redirect(url_for('user'))
    

# Maneja el logout
@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('index'))

# Ejecuta la aplicacion-----------------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True)

