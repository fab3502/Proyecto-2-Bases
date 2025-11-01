# services.py
import pymongo
from typing import Tuple
from storage import (
    votes_user_set, votes_insert, votes_delete,
    concursante_category,
    cache_warm_user_voted, cache_incr_vote_counters, cache_decr_vote_counters,
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
        except Exception:
            pass
        return True
    except Exception:
        return False
