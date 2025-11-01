# services.py
import pymongo
import time
from typing import Tuple, Iterator
from storage import (
    redis_db,REDIS_CHANNEL_NAME,
    votes_user_set, votes_insert, votes_delete,
    concursante_category, cache_warm_user_voted, cache_incr_vote_counters, 
    cache_decr_vote_counters, publish_vote_event
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
    yield "retry: 5000\n\n"
    yield ": stream-start\n\n"
    KEEPALIVE_EVERY = 10  # seconds
    
    last_keepalive = time.time()

    pubsub = None
    try:
        pubsub = redis_db.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(REDIS_CHANNEL_NAME)

        subscribe_deadline = time.time() + 1.0

        while time.time() < subscribe_deadline:
            msg = pubsub.get_message(timeout=0.1)
            if not msg:
                continue
            if msg.get("type") == "message":
                break
        yield "event: message\ndata: init\n\n"
        print(f"{time.strftime('%H:%M:%S')} DEBUG Started vote event stream")
        while True:
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)

            if msg and msg.get("type") == "message":
                data = msg.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="ignore")
                yield f"event: message\ndata: {data}\n\n"
                print(f"{time.strftime('%H:%M:%S')} DEBUG Published vote event:", data)

            now = time.time()
            if now - last_keepalive >= KEEPALIVE_EVERY:
                yield ": keepalive\n\n"
                last_keepalive = now
                print(f"{time.strftime('%H:%M:%S')} DEBUG Sent keepalive")

    except Exception as e:
        # Surface the error to the client for easier debugging from DevTools
        yield f"event: error\ndata: {type(e).__name__}: {str(e)}\n\n"
        print(f"{time.strftime('%H:%M:%S')} DEBUG ERROR in vote event stream:", str(e))
    finally:
        try:
            if pubsub is not None:
                pubsub.close()
                print(f"{time.strftime('%H:%M:%S')} DEBUG Closing PubSub")
        except Exception:
            print(f"{time.strftime('%H:%M:%S')} DEBUG Error closing PubSub")
            pass