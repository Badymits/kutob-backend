from django.shortcuts import render, get_object_or_404

from rest_framework.response import Response
from rest_framework.decorators import api_view

from .serializers import UserSerializer
from .models import User
from game.models import Player

# Create your views here.

@api_view(['POST'])
def createUser(request):
    
    context = {}
    serializer = UserSerializer(data=request.data)
    
    if serializer.is_valid():
        user = User.objects.create(username=serializer.data['username'])
        
        # create player object 
        player = Player.objects.create(username=serializer.data['username'])
        
        # save to DB
        user.save()
        player.save()
        
        context['username'] = user.username
        context['message'] = 'User created'
        
        return Response(context, status=200)
    
    context['message'] = 'Username already taken'
    return Response(context, status=400)

@api_view(['DELETE'])
def deleteUser(request, username):
    context = {}

    user = get_object_or_404(User, username=username)
    player = get_object_or_404(Player, username=username)

    user.delete()
    # delete player if they have no game code, else, ignore delete
    if not player.game:
        player.delete()
    
    context['message'] = 'Delete Successful'
    return Response(context, status=204)