from flask import Flask, render_template, request, redirect, url_for, flash, session
import pymongo
import redis
import json
import os
from datetime import datetime,timezone

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
        mongo_db['votos_log'].create_index(
            [("user_id", pymongo.ASCENDING), ("concursante_id", pymongo.ASCENDING)],
            unique=True,
            name="uniq_user_concursante"
        )

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
    if not user_id:
        flash('Debe iniciar sesión para acceder al panel de votación', 'error')
        return redirect(url_for('index'))

    concursantes = mongo_db['concursantes'].find({})

    cursor = mongo_db['votos_log'].find(
        {'user_id': user_id},
        {'_id': 0, 'concursante_id': 1}
    )
    votos_usuario = {int(doc['concursante_id']) for doc in cursor}

    try:
        key = f"voted:{user_id}"
        with redis_db.pipeline() as pipe:
            pipe.delete(key)
            if votos_usuario:
                pipe.sadd(key, *[str(cid) for cid in votos_usuario]) 
            pipe.execute()
    except Exception:
        print("Error al sincronizar votos del usuario en Redis")
        pass

    return render_template('user.html', concursantes=concursantes, votos_usuario=votos_usuario)


# Ruta para agregar voto
@app.route('/user/add_vote/<int:concursante_id>', methods=['POST'])
def add_vote(concursante_id):
    user_id = session.get('user_id')
    if not user_id:
        if is_hx():
            return render_template('_vote_button.html', cid=concursante_id, has_voted=False), 401
        flash('Debe iniciar sesión para votar', 'error')
        return redirect(url_for('index'))
    
    try:
        mongo_db['votos_log'].insert_one({
            'user_id': user_id,
            'concursante_id': int(concursante_id),
            'timestamp': datetime.now(timezone.utc)  # UTC-aware
        })
        mongo_ok = True
    except pymongo.errors.DuplicateKeyError:
        mongo_ok = False
    except Exception:
        if is_hx():
            current = has_user_voted(user_id, concursante_id)
            return render_template('_vote_button.html', cid=concursante_id, has_voted=current), 500
        flash('Error al registrar el voto', 'error')
        return redirect(url_for('user'))

    if mongo_ok:
        try:
            cid_str = str(concursante_id)
            categoria = get_categoria_for_cid(concursante_id)
            with redis_db.pipeline() as pipe:
                pipe.incr(f"votes:{cid_str}")
                pipe.incr("votes:total")
                pipe.zincrby("votes:rank", 1, cid_str)
                pipe.hincrby("votes:bycat", categoria, 1)
                pipe.sadd(f"voted:{user_id}", cid_str)
                pipe.execute()
        except Exception:
            pass

    if is_hx():
        return render_template('_vote_button.html', cid=concursante_id, has_voted=True)
    else:
        if not mongo_ok:
            flash('Ya ha votado por este concursante', 'error')
        return redirect(url_for('user'))


@app.route('/user/remove_vote/<int:concursante_id>', methods=['POST'])
def remove_vote(concursante_id):
    user_id = session.get('user_id')
    if not user_id:
        if is_hx():
            return render_template('_vote_button.html', cid=concursante_id, has_voted=False), 401
        flash('Debe iniciar sesión para votar', 'error')
        return redirect(url_for('index'))

    try:
        mongo_db['votos_log'].delete_one({'user_id': user_id, 'concursante_id': int(concursante_id)})
        mongo_ok = True
    except Exception:
        mongo_ok = False

    if mongo_ok:
        try:
            cid_str = str(concursante_id)
            categoria = get_categoria_for_cid(concursante_id)
            with redis_db.pipeline() as pipe:
                pipe.decr(f"votes:{cid_str}")
                pipe.decr("votes:total")
                pipe.zincrby("votes:rank", -1, cid_str)
                pipe.hincrby("votes:bycat", categoria, -1)
                pipe.srem(f"voted:{user_id}", cid_str)
                pipe.execute()
        except Exception:
            pass

    if is_hx():
        current = has_user_voted(user_id, concursante_id) if not mongo_ok else False
        return render_template('_vote_button.html', cid=concursante_id, has_voted=current)
    else:
        if not mongo_ok:
            flash('Error al eliminar el voto', 'error')
        return redirect(url_for('user'))

    

# Maneja el logout
@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('index'))

# Funciones auxiliares-------------------------------------------------------------------------
def is_hx() -> bool:
    return request.headers.get('HX-Request') == 'true'

def get_categoria_for_cid(cid: int) -> str:
    doc = mongo_db['concursantes'].find_one({'id': int(cid)}, {'categoria': 1, '_id': 0})
    return (doc or {}).get('categoria', 'Desconocida')

def has_user_voted(user_id: str, cid: int) -> bool:
    return mongo_db['votos_log'].count_documents({'user_id': user_id, 'concursante_id': int(cid)}, limit=1) == 1

# Ejecuta la aplicacion-----------------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True)

