from django.shortcuts import render, get_object_or_404
from django.core.cache import cache

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
        
        print(serializer.data['username'])
        
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


@api_view(['PATCH'])
def updateUserSettings(request):
    
    context = {}
    print('request made')
    username = request.data.get('username')
    new_username = request.data.get('new_username')
    avatar = request.data.get('avatar')
    print(username, avatar)
    
    if request.method == 'PATCH':
        try:
            player = get_object_or_404(Player, username=username)
            
            
            payload = {
                'username': new_username,
                'avatar' : avatar
            }
            serializer = UserSerializer(player, data=payload, partial=True)
            
            if serializer.is_valid():
                serializer.save()
                player.username = serializer.validated_data['username']
            
            if avatar is not None:
                context['avatar'] = avatar
                player.avatar = serializer.validated_data['avatar']
            
            player.save()
            
            context['new_username'] = player.username
            context['message'] = 'Changes Saved!'
            return Response(context, status=200)
            
            
        except Player.DoesNotExist:
            context['message'] = 'Player does not exist'
            return Response(context, status=400)
        


@api_view(['GET'])
def returnUserData(request):
    
    username = cache.get(request.data.get('username'))
    
    
    return Response({'username': username}, status=200)