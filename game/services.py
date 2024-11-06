import redis
from asgiref.sync import sync_to_async

redis_client = redis.StrictRedis(host='localhost', port=6379, db=1)

@sync_to_async
def set_player_connected(username, code):
    
    redis_key = f'room_{code}_player_{username}'
    redis_client.set(redis_key, "connected")
    
@sync_to_async
def set_player_disconnected(username, code):
    redis_key = f'room_{code}_player_{username}'
    redis_client.set(redis_key, "disconnected")
    
@sync_to_async
def get_player_status(username, code):
    redis_key = f'room_{code}_player_{username}'
    return redis_client.get(redis_key)



