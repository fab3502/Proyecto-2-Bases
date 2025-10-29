from flask import Flask, render_template, request, redirect, url_for, flash, session
from db import reset_db
import pymongo


# Conexion a la base de datos mongo-------------------------------------------------------------
MONGO_URL = "mongodb://localhost:27017/"
MONGO_DB = "Proyecto2"
mongo_client = pymongo.MongoClient(MONGO_URL)
db = mongo_client[MONGO_DB]

# Configuracion de Flask------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = 'dev'

# Rutas de la aplicacion------------------------------------------------------------------------

# Pagina de inicio, renderiza el formulario de login/registro
@app.route('/')
def index():
    session.clear()
    return render_template('login.html')

# Maneja el login, registro y reseteo de la base de datos
@app.route('/login', methods=['POST'])
def login():
    session.clear()

    action = request.form.get('action', '')
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    if action == 'login':
        if not username or not password:
            flash('Username and password are required', 'warning')
            return redirect(url_for('index'))

        user = db['usuarios'].find_one({'username': username})
        if not user:
            flash('Invalid credentials', 'danger')
            return redirect(url_for('index'))

        
        if password != user.get('password', '') :
            flash('Invalid credentials', 'danger')
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
            flash('Username and password are required', 'warning')
            return redirect(url_for('index'))
        if db['usuarios'].find_one({'username': username}):
            flash('Username already exists', 'danger')
            return redirect(url_for('index'))
        
        db['usuarios'].insert_one({'username': username, 'password': password, 'role': 'user'})
        
        session['user_id'] = str(db['usuarios'].find_one({'username': username}).get('_id'))
        session['username'] = username
        session['role'] = 'user'

        return redirect(url_for('user'))
    elif action == 'reset':
        reset_db(db)
        flash('Database has been reset', 'info')
        return redirect(url_for('index'))

    return redirect(url_for('index'))

# Pagina de admin    
@app.route('/admin')
def admin():
    return render_template('admin.html')

# Pagina de usuario normal
@app.route('/user')
def user():
    return render_template('user.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# Ejecuta la aplicacion-----------------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True)

