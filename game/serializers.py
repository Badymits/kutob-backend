from rest_framework import serializers

from .models import Game, Player
from user.models import User

class GameSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Game
        fields = '__all__'
        
        
class PlayersInLobby(serializers.ModelSerializer):
    
    class Meta:
        model = Player
        fields = ('username', 'avatar',)
        
     
class PlayerSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Player
        fields = ('username', 'avatar', )
        
class PlayerVoteSerializer(serializers.ModelSerializer):
    
    vote_target = PlayerSerializer(read_only=True)
    
    class Meta:
        model = Player
        fields = ('username', 'avatar', 'vote_target', )
        

class WinnersSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Game
        fields = ('winners', )

