# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
import os, json

from config import SECRET_KEY
from storage import (
    redis_db, ensure_indexes, reset_all,
    user_find_by_username, user_insert,
    concursantes_all, concursantes_insert,
    concursantes_insert_many_sanitized
)
from services import warm_user_voted, add_vote, remove_vote

# --- Flask setup ----------------------------------------------------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY

# --- Htmx util -----------------------------------------------------------------
def is_hx() -> bool:
    return request.headers.get('HX-Request', '').lower() == 'true'

# --- Routes ---------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    action = request.form.get('action')
    username = request.form.get('username')
    password = request.form.get('password')

    if action == 'login':
        if not username or not password:
            flash('Nombre de usuario y contraseña son requeridos', 'error')
            return redirect(url_for('index'))

        user = user_find_by_username(username)
        if not user or password != user.get('password', ''):
            flash('Credenciales inválidas', 'error')
            return redirect(url_for('index'))

        session['user_id'] = str(user.get('_id'))
        session['username'] = user.get('username')
        session['role'] = user.get('role', 'user')
        return redirect(url_for('admin' if session['role'] == 'admin' else 'user'))

    elif action == 'register':
        if not username or not password:
            flash('Nombre de usuario y contraseña son requeridos', 'error')
            return redirect(url_for('index'))
        if user_find_by_username(username):
            flash('Nombre de usuario ya existe', 'error')
            return redirect(url_for('index'))

        user_insert(username, password, 'user')
        user = user_find_by_username(username)
        session['user_id'] = str(user.get('_id'))
        session['username'] = username
        session['role'] = 'user'
        return redirect(url_for('user'))

    elif action == 'reset':
        current_dir = os.path.dirname(os.path.abspath(__file__))
        usuarios_path = os.path.join(current_dir, 'usuarios.json')
        if not os.path.exists(usuarios_path):
            usuarios_data = [{"username": "admin", "password": "password", "role": "admin"}]
        else:
            with open(usuarios_path, 'r') as f:
                usuarios_data = json.load(f)
        
        reset_all(usuarios_data)
        flash('La base de datos ha sido restablecida', 'info')
        return redirect(url_for('index'))

    return redirect(url_for('index'))

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/load_json', methods=['POST'])
def load_json():
    file = request.files.get('concursantes_json')
    if not file:
        flash('No se ha seleccionado ningún archivo', 'error')
        return redirect(url_for('admin'))

    try:
        data = json.load(file)
        if not isinstance(data, list):
            data = data.get("concursantes", [])
    except Exception:
        flash('JSON inválido', 'error')
        return redirect(url_for('admin'))

    if not data:
        flash('El archivo JSON está vacío', 'error')
        return redirect(url_for('admin'))
 
    result = concursantes_insert_many_sanitized(data)
    msg = f"Cargados: {result['inserted']}. IDs remapeados: {result['remapped']}. Errores: {result['errors']}."
    flash(msg, 'success' if result['inserted'] else 'error')
    return redirect(url_for('admin'))


@app.route('/add_concursante', methods=['POST'])
def add_concursante():
    nombre = request.form.get('nombre')
    categoria = request.form.get('categoria')
    foto = request.files.get('foto')

    if not (nombre and categoria and foto):
        flash('Datos incompletos', 'error')
        return redirect(url_for('admin'))

    filename = secure_filename(foto.filename)
    fotos_folder = os.path.join(app.static_folder, 'fotos')
    os.makedirs(fotos_folder, exist_ok=True)
    foto.save(os.path.join(fotos_folder, filename))

    concursantes_insert(nombre, categoria, filename)
    flash('Concursante agregado exitosamente', 'success')
    return redirect(url_for('admin'))

@app.route('/user')
def user():
    user_id = session.get('user_id')
    if not user_id:
        flash('Debe iniciar sesión para acceder al panel de votación', 'error')
        return redirect(url_for('index'))

    concursantes = concursantes_all()
    votos_usuario = warm_user_voted(user_id)  
    return render_template('user.html', concursantes=concursantes, votos_usuario=votos_usuario)

@app.route('/user/add_vote/<int:concursante_id>', methods=['POST'])
def add_vote_route(concursante_id):
    user_id = session.get('user_id')
    if not user_id:
        if is_hx():
            return render_template('_vote_button.html', cid=concursante_id, has_voted=False), 401
        flash('Debe iniciar sesión para votar', 'error')
        return redirect(url_for('index'))

    ok, duplicate = add_vote(user_id, concursante_id)

    if is_hx():
        return render_template('_vote_button.html', cid=concursante_id, has_voted=True), (200 if ok else 500)

    if not ok and not duplicate:
        flash('Error al registrar el voto', 'error')
    elif duplicate:
        flash('Ya ha votado por este concursante', 'error')
    return redirect(url_for('user'))

@app.route('/user/remove_vote/<int:concursante_id>', methods=['POST'])
def remove_vote_route(concursante_id):
    user_id = session.get('user_id')
    if not user_id:
        if is_hx():
            return render_template('_vote_button.html', cid=concursante_id, has_voted=False), 401
        flash('Debe iniciar sesión para votar', 'error')
        return redirect(url_for('index'))

    ok = remove_vote(user_id, concursante_id)

    if is_hx():
        return render_template('_vote_button.html', cid=concursante_id, has_voted=False), (200 if ok else 500)

    if not ok:
        flash('Error al eliminar el voto', 'error')
    return redirect(url_for('user'))

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    #usuarios_data = [{"username": "admin", "password": "password", "role": "admin"}]
    #reset_all(usuarios_data)
    ensure_indexes()
    try:
        from storage import redis_db
        redis_db.ping()
        print("Redis OK")
    except Exception as e:
        print("Redis connection failed:", e)

    app.run(debug=True)
