import json
from django.shortcuts import get_object_or_404
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async, DatabaseSyncToAsync
from asgiref.sync import sync_to_async, async_to_sync

from game.models import Game
from game.serializers import PlayersInLobby


class GameRoomConsumer(AsyncJsonWebsocketConsumer):
    
    async def connect(self):
        
        self.group_code = self.scope.get("url_route").get("kwargs").get("code")  # from routing url parameter
        self.user = self.scope.get("url_route").get("kwargs").get("username") # username is unique
        
        # create unique group
        self.room_code = f'room_{self.group_code}'
        
        # unique group with one player only, used for role reveal and role UI
        self.player_room_code = f'{self.user}_{self.group_code}'
        
        
        await self.channel_layer.group_add(
            self.room_code,
            self.channel_name # this will be created automatically for each user
        )
        
        await self.channel_layer.group_add(
            self.player_room_code,
            self.channel_name    
        )

        await self.accept()
        await self._send_message_on_connect()
    
    async def disconnect(self, code):
        
        await self.channel_layer.group_discard(self.room_code, self.channel_name)
        await self.channel_layer.group_discard(self.player_room_code, self.channel_name)
        
        game = Game.objects.get(room_code=self.group_code)
        
        # end the game when a player leaves the game
        if game.players.count() < game.room_limit and game.has_started == True:
            # send users to 9th phase na. End the damn game
            pass
        
        # send message to frontend notifying users who left and updating player list to change UI
        self.players = await self.getPlayersInLobby(self.group_code)
        data = {
                    "type": "update_player_list",
                    "message": f'{self.user} left the lobby',
                    "sender": "SERVER",
                    "players": self.players
                }
        await self.channel_layer.group_send(
            self.room_code,
            {
                "type": "send_message",
                "data": data
            }
        )
    
    async def send_update_message(self, event):
        await self.send_json(event['data'])
        

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        print(text_data_json)
        message = text_data_json['message']
        sender = text_data_json['sender']
        
        
        event = {
            'type': 'chat_message',
            'message': message,
            'sender': sender
        }
        
        await self.channel_layer.group_send(
            self.room_code,
            event
        )
        
    async def send_message(self, event):
        # Should be called by group_send only
        await self.send_json(event["data"])
        
    async def _send_message_on_connect(self):
        
        try:
            self.players = await self.getPlayersInLobby(self.group_code)
            print(self.players)
        except:
            self.players = []
            
            
        data = {
            "type": "player_list",
            "players": self.players,
            'sender': 'SERVER',
            'message': f'{self.user} has joined the lobby'
        }
        
        await self.channel_layer.group_send(
            self.room_code,
            {
                "type": "send_message",
                "data": data
            }
        )
        
    
    # function name must be the same name as the event type
    async def chat_message(self, event):
        
        await self.send(text_data=json.dumps({
            'type': event['type'],
            'message': event['message'],
            'sender': event['sender']
        }))
        
    @sync_to_async
    def getPlayersInLobby(self, code):
        
        # sana walang error dito
        try:
            game = Game.objects.get(room_code=code)
            playerList = PlayersInLobby(game.players.all(), many=True).data
        except:
           playerList = [] 
        
            
        return playerList 
    
    

    