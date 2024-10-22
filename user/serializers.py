from rest_framework import serializers
from game.models import Player


class UserSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Player
        fields = ['username']