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

        # create player object 
        player = Player.objects.create(username=serializer.data['username'])
        
        player.save()
        
        context['username'] = serializer.data['username']
        context['message'] = 'User created'
        
        return Response(context, status=200)
    
    context['message'] = 'Username already taken'
    return Response(context, status=400)

@api_view(['DELETE'])
def deleteUser(request, username):
    context = {}

    player = get_object_or_404(Player, username=username)
    player.delete()
    
    context['message'] = 'Delete Successful'
    return Response(context, status=204)