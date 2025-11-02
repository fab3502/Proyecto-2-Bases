# services.py
import pymongo
import time
from typing import Tuple, Iterator
from storage import (
    votes_user_set, votes_insert, votes_delete,
    concursante_category, cache_warm_user_voted, cache_incr_vote_counters, 
    cache_decr_vote_counters, create_pubsub, subscribe_pubsub, publish_vote_event
)

def warm_user_voted(user_id: str) -> set[int]:
    cids = votes_user_set(user_id)
    try:
        cache_warm_user_voted(user_id, cids)
    except Exception:
        pass
    return cids

def add_vote(user_id: str, cid: int) -> Tuple[bool, bool]:
    try:
        votes_insert(user_id, cid)  
        cat = concursante_category(cid) or "Desconocida"
        try:
            cache_incr_vote_counters(cid, cat, user_id)
            publish_vote_event()
        except Exception:
            pass
        return True, False
    except pymongo.errors.DuplicateKeyError:  # type: ignore
        return True, True
    except Exception:
        return False, False

def remove_vote(user_id: str, cid: int) -> bool:
    try:
        votes_delete(user_id, cid)
        cat = concursante_category(cid) or "Desconocida"
        try:
            cache_decr_vote_counters(cid, cat, user_id)
            publish_vote_event()
        except Exception:
            pass
        return True
    except Exception:
        return False

def make_vote_event_stream() -> Iterator[str]: 
    KEEPALIVE_EVERY = 10 # seconds 
    pubsub = create_pubsub()
    subscribe_pubsub(pubsub)
    last_keepalive = time.time() 
    try: 
        yield "event: message\ndata: init\n\n" 
        while True: 
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0) 
            if msg and msg.get("type") == "message": 
                data = msg.get("data") 
                if isinstance(data, bytes): 
                    data = data.decode("utf-8", errors="ignore") 
                yield f"event: message\ndata: {data}\n\n" 
            now = time.time() 
            if now - last_keepalive >= KEEPALIVE_EVERY: 
                yield ": keepalive\n\n" 
                last_keepalive = now 
    except GeneratorExit: 
        pass 
    finally: 
        try: 
            pubsub.close() 
        except Exception: 
            pass