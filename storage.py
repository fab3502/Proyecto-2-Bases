# storage.py
import pymongo, redis
from datetime import datetime, timezone
from typing import Iterable

# --- Config -------------------------------------------------------------------
MONGO_URI  = "mongodb://localhost:27017/"
MONGO_DB   = "Proyecto2"

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB   = 0
REDIS_CHANNEL_NAME = "votes_channel"

# --- Clients ----------------------------------------------------------------
mongo_client = pymongo.MongoClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB]

redis_db = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=True,
)

# --- Collections -------------------------------------------------------------
USUARIOS     = mongo_db["usuarios"]
CONCURSANTES = mongo_db["concursantes"]
VOTOS        = mongo_db["votos_log"]

# --- Indexes -----------------------------------------------------------------
def ensure_indexes() -> None:
    # votes unique (you already had this somewhere)
    VOTOS.create_index(
        [("user_id", pymongo.ASCENDING), ("concursante_id", pymongo.ASCENDING)],
        unique=True,
        name="uniq_user_concursante",
    )
    # NEW: unique index for concursantes.id
    CONCURSANTES.create_index(
        [("id", pymongo.ASCENDING)],
        unique=True,
        name="uniq_concursante_id",
    )

# --- Users repo --------------------------------------------------------------
def user_find_by_username(username: str):
    return USUARIOS.find_one({"username": username})

def user_insert(username: str, password: str, role: str = "user") -> None:
    USUARIOS.insert_one({"username": username, "password": password, "role": role})

# --- Concursantes repo --------------------------------------------------------
def concursantes_all():
    return list(CONCURSANTES.find({}))

def concursantes_next_id() -> int:
    last = list(CONCURSANTES.find().sort("id", -1).limit(1))
    return (last[0]["id"] + 1) if last else 1

def concursantes_insert(nombre: str, categoria: str, foto: str) -> None:
    CONCURSANTES.insert_one({
        "id": concursantes_next_id(),
        "nombre": nombre,
        "categoria": categoria,
        "foto": foto,
        "votos_acumulados": 0,
    })

def concursante_category(cid: int) -> str | None:
    doc = CONCURSANTES.find_one({"id": int(cid)}, {"categoria": 1, "_id": 0})
    return (doc or {}).get("categoria")

def concursantes_insert_many_sanitized(raw_list: list[dict]) -> dict:
    inserted, remapped, errors = 0, 0, 0

    existing_ids = set(
        d["id"] for d in CONCURSANTES.find({}, {"_id": 0, "id": 1})
        if "id" in d
    )
    current_next = concursantes_next_id()

    docs = []
    for item in raw_list:
        try:
            nombre = item.get("nombre") or item.get("name") or "Sin nombre"
            categoria = item.get("categoria") or item.get("category") or "Sin categoría"
            foto = item.get("foto") or item.get("photo") or "default.png"

            provided = item.get("id")
            use_id = None
            if isinstance(provided, int) and provided > 0 and provided not in existing_ids:
                use_id = provided
            else:
                use_id = current_next
                while use_id in existing_ids:
                    use_id += 1
                current_next = use_id + 1
                remapped += 1

            existing_ids.add(use_id)

            docs.append({
                "id": use_id,
                "nombre": nombre,
                "categoria": categoria,
                "foto": foto,
                "votos_acumulados": 0,
            })
        except Exception:
            errors += 1

    if docs:
        CONCURSANTES.insert_many(docs)
        inserted = len(docs)

    return {"inserted": inserted, "remapped": remapped, "errors": errors}

def concursantes_get_top_3() -> list[dict]:
    try:
        top3_redis = redis_db.zrange("votes:rank", 0, 2, withscores=True, desc=True)
        top3= []
        for concursante_id, votos in top3_redis: # type: ignore
            concursante = CONCURSANTES.find_one({"id":int(concursante_id)})
            if concursante:
                top3.append({
                    "nombre": concursante["nombre"],
                    "categoria": concursante["categoria"],
                    "foto": concursante["foto"],
                    "votos": int(votos)
                })
        return top3
    except Exception:
        return []

def concursantes_no_votes() -> list[dict]:
    try:
        todos = list(concursantes_all())
        con_votos = {
            int(key.split(":")[1])
            for key in redis_db.keys("votes:[0-9]*") # type: ignore
            if key != "votes:total"
        }
        return [
            concursante for concursante in todos
            if concursante["id"] not in con_votos
        ]
    except Exception:
        return []


# --- Votes repo --------------------------------------------------------------
def votes_user_set(user_id: str) -> set[int]:
    cur = VOTOS.find({"user_id": user_id}, {"_id": 0, "concursante_id": 1})
    return {int(d["concursante_id"]) for d in cur}

def votes_insert(user_id: str, cid: int) -> None:
    VOTOS.insert_one({
        "user_id": user_id,
        "concursante_id": int(cid),
        "timestamp": datetime.now(timezone.utc), 
    })
    
def votes_delete(user_id: str, cid: int) -> None:
    VOTOS.delete_one({"user_id": user_id, "concursante_id": int(cid)})

def votes_has(user_id: str, cid: int) -> bool:
    return VOTOS.count_documents({"user_id": user_id, "concursante_id": int(cid)}, limit=1) == 1

def votes_count(concursantes):
    concursantes_ids = [str(d['id']) for d in concursantes]
    counts_by_id: dict[int, int] = {}
    try:
        with redis_db.pipeline() as pipe:
            for cid in concursantes_ids:
                pipe.get(f"votes:{cid}")
            results = pipe.execute()
            for cid, val in zip(concursantes_ids, results):
                try:
                    counts_by_id[int(cid)] = int(val) if val is not None else 0
                except (TypeError, ValueError):
                    counts_by_id[int(cid)] = 0
    except Exception:
        counts_by_id = {int(cid): 0 for cid in concursantes_ids}
    return counts_by_id

def votes_by_categoria() -> dict[str, int]:
    try:
        return redis_db.hgetall("votes:bycat") or {} # type: ignore
    except Exception:
        return {}
    

# --- Redis cache helpers --------------------------------
def cache_warm_user_voted(user_id: str, cids: Iterable[int]) -> None:
    key = f"voted:{user_id}"
    cids = list(cids)
    with redis_db.pipeline() as p:
        p.delete(key)
        if cids:
            p.sadd(key, *[str(x) for x in cids])
        p.execute()

def cache_incr_vote_counters(cid: int, category: str, user_id: str) -> None:
    s = str(cid)
    with redis_db.pipeline() as p:
        p.incr(f"votes:{s}")
        p.incr("votes:total")
        p.zincrby("votes:rank", 1, s)
        p.hincrby("votes:bycat", category or "Desconocida", 1)
        p.sadd(f"voted:{user_id}", s)
        p.execute()
    print("DEBUG votes:total =", redis_db.get("votes:total"))

def cache_decr_vote_counters(cid: int, category: str, user_id: str) -> None:
    s = str(cid)
    with redis_db.pipeline() as p:
        p.decr(f"votes:{s}")
        p.decr("votes:total")
        p.zincrby("votes:rank", -1, s)
        p.hincrby("votes:bycat", category or "Desconocida", -1)
        p.srem(f"voted:{user_id}", s)
        p.execute()

# --- Helpers -----------------------------------------------
def reset_all(seed_users: list[dict]) -> None:
    USUARIOS.delete_many({})
    CONCURSANTES.delete_many({})
    VOTOS.delete_many({})
    redis_db.flushdb()
    if seed_users:
        USUARIOS.insert_many(seed_users)
    ensure_indexes()

def create_pubsub():
    return redis_db.pubsub()

def subscribe_pubsub(pubsub):
    pubsub.subscribe(REDIS_CHANNEL_NAME)

def publish_vote_event():
    redis_db.publish(REDIS_CHANNEL_NAME, "changed")
