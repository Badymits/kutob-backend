from django.shortcuts import get_object_or_404
import redis
from asgiref.sync import sync_to_async

from game.models import Player, Game

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


def set_game_turn(code, role_turn): # mangangaso, babaylan, manghuhula, mandurugo, manananggal, berbalang
    
    redis_key = f'room_{code}_turn' 
    redis_client.set(redis_key, role_turn)
    return True

def get_game_turn(code):
    redis_key = f'room_{code}_turn' 
    return redis_client.get(redis_key)
    
# non sync
def set_player_connected_non_sync(username, code):
    
    redis_key = f'room_{code}_player_{username}'
    redis_client.set(redis_key, "connected")
    return True
   
def set_player_disconnected_non_sync(username, code):
    redis_key = f'room_{code}_player_{username}'
    redis_client.set(redis_key, "disconnected")
    return True

def get_player_status_non_sync(username, code):
    redis_key = f'room_{code}_player_{username}'
    return redis_client.get(redis_key)
