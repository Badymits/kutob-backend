from rest_framework import serializers

from .models import Game, Player
from user.models import User

class GameSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Game
        fields = '__all__'
        
        
class PlayersInLobby(serializers.ModelSerializer):
    
    class Meta:
        model = User
        fields = ('username',)
        
        
class PlayerSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Player
        fields = ('username', )
        

class WinnersSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Game
        fields = ('winners', )

