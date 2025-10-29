import json
import os


def reset_db(db):
    db['usuarios'].delete_many({}) 
    db['concursantes'].delete_many({})

    current_dir = os.path.dirname(os.path.abspath(__file__))
    usuarios_path = os.path.join(current_dir, 'usuarios.json')
    concursantes_path = os.path.join(current_dir, 'concursantes.json')
    
    if not os.path.exists(usuarios_path):
        usuarios_data = [{"username": "admin", "password": "password", "role": "admin"}, {"username": "user1", "password": "password", "role": "user"}]
    else:
        with open(usuarios_path, 'r') as f:
            usuarios_data = json.load(f)
        
    with open(concursantes_path, 'r') as f:
        concursantes_data = json.load(f)


    db['usuarios'].insert_many(usuarios_data)
    db['concursantes'].insert_many(concursantes_data)

