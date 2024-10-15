from django.shortcuts import render, get_object_or_404
from rest_framework.response import Response
from rest_framework.decorators import api_view
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.db.models import Q

from .models import Game, Player
from .serializers import GameSerializer
from game.serializers import PlayersInLobby 
from .tasks import send_role, phaseCountdown, switchToNextPhase
from django.core.cache import cache

import math
import random

# creates a code for the room in FE
def createCode(length):
    
    result = ''
    characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    
    characterLength = len(characters)
    
    counter = 0
    
    while(counter < length):
        result += characters[math.floor(random.randint(0, characterLength - 1))]
        counter += 1
    return result


# only post methods can access this view
@api_view(['POST'])
def createRoom(request):  
    
    context = {}
    # retrieve owner from request to query user obj
    user = Player.objects.get(username=request.data['owner'])
    print(request.data['owner'])
    room_code = createCode(8)
    context['code'] = room_code
    
    
    # check if there is existing lobby
    try:
        game = get_object_or_404(Game, room_code=room_code)
    except: 
        game = None
    
    # create if it doesn't exist
    if game is None:
        game = Game.objects.create(
            owner=user,
            room_code=room_code
        )
        
        game.players.add(user)
        user.game.add(game)
        
        game.save()

        context['message'] = 'Lobby created'
    else:
        context['message'] = 'Lobby already exists'
    
    return Response(context)

@api_view(['POST'])
def joinRoom(request):
    
    context = {}
    
    player = request.data['player']
    code = request.data['code']
    

    # search game obj
    try:
        game = Game.objects.get(room_code=code)
    except:
        game = None
    
    if game is None:
        context['message'] = 'Room does not exist'
        return Response(context, status=404)
    
    try:
        user = Player.objects.get(username=player)
    except:
        user = None
        context['message'] = 'An error ocurred, player does not exist'
        return Response(context, status=400)
    
    
    # users cannot enter if the room is already at the player limit count
    if int(game.room_limit) > game.players.all().count():
        
        if game is not None and user is not None:
            game.players.add(user)
            user.game.add(game)
            # retrieve all players in the room
            players = game.players.all().values_list('username', flat=True)
            
            print(players)
            
            context['players'] = players
            context['message'] = 'Room found'
            return Response(context, status=200)
        
        else:
            context['message'] = 'Error ocurred'
            return Response(context)
    else:
        context['message'] = 'Room is full, cannot join',
        return Response(context, status=400)
    
    
@api_view(['DELETE'])
def leaveRoom(request):
    
    context = {}
    
    player = Player.objects.get(username=request.data['player'])
    code = request.data['code']
    
    try:
        game = Game.objects.get(room_code=code)
        
        # to prevent errors happening, we can just use if statement even though it is a guarantee that 
        # player exists 
        if game.players.filter(username=player).exists():
            game.players.remove(player)
            player.game.remove(game)
            
            #if player.in_game == True: 
            player.role = ''
            player.alive = True
            
            player.is_protected = False
            player.skip_turn = False
            
            player.eliminated_on_night = 0
            player.revived_on_night = 0
            
            player.vote_target = None
            player.eliminated_from_game = False
            
            player.in_game = False
            player.save() 
            
            context['message'] = 'Left the room'
            # send_message_to_lobby_task.delay(code, user)
            
            # delete game room if last player in the room left, if Game has ended, it means it is completed and there is no need to delete it
            if Game.objects.filter(players=None) and Game.has_ended is False:
                game.delete()
            
        else:
            context['message'] = 'Player does not exist'
        return Response(context)
    except:
        context['message'] = 'Game does not exist'
        return Response(context)
    
    
    
@api_view(['PATCH'])
def updateRoomSettings(request):
    
    context = {}
    channel_layer = get_channel_layer()
    code = request.data['code']
    
    if request.method == 'PATCH':
        try:
            game = Game.objects.get(room_code=code)
        except:
            context['message'] = 'Game room does not exist'
            return Response(context)
        
        player_count = game.players.all().count()
        
        if request.data['update'] == 'update_room':
            
            # check first if players in room are more than the requested limit
            # if it is, then return message saying they cannot change, else, proceed with logic
            if player_count > request.data['limit']:
            
                data = {
                    "type": 'send_update_message',
                    'message': 'Cannot remove other players that joined the room',
                    'sender': 'SERVER',
                    'update': 'no_changes',
                    'limit': request.data['limit']
                }
                
                # broadcast message
                async_to_sync(channel_layer.group_send)(
                    f'room_{code}',
                    {
                        'type': 'send_update_message',
                        'data': data
                    }
                )
                context['message'] = 'Cannot remove other players that joined the room'
                return Response(data=data,status=400) 

            # if the aswang limit is set to 3 and owner decides to change room limit, change aswang limit too
            # convert field to int for it to work
            if int(game.aswang_limit) == 3 and  ( 5 <= request.data['limit'] <= 7):
                new_aswang_limit = int(game.aswang_limit) - 2
                payload = {
                    'room_limit' : request.data['limit'],
                    'aswang_limit': new_aswang_limit
                }
                message = 'Game settings saved, changed aswang limit due to player limit'
                
                
                
            elif int(game.aswang_limit) == 3 and ( 8 <= request.data['limit'] <= 9):
                new_aswang_limit = int(game.aswang_limit) - 1
                payload = {
                    'room_limit' : request.data['limit'],
                    'aswang_limit': new_aswang_limit
                }
                message = 'Game settings saved, changed aswang limit due to player limit'
                
                
                
            elif int(game.aswang_limit) == 2 and 5 <= request.data['limit'] <= 7:
                new_aswang_limit = int(game.aswang_limit) - 1
                payload = {
                    'room_limit' : request.data['limit'],
                    'aswang_limit': new_aswang_limit
                }
                message = 'Game settings saved, changed aswang limit due to player limit'
                
                
            elif int(game.aswang_limit) == 2 and 5 <= request.data['limit'] <= 7:
                new_aswang_limit = int(game.aswang_limit) - 1
                payload = {
                    'room_limit' : request.data['limit'],
                    'aswang_limit': new_aswang_limit
                }
                message = 'Game settings saved, changed aswang limit due to player limit'
            
            else:
                payload = {
                    'room_limit' : request.data['limit'],
                }
                message = 'Game settings updated'
                
            serializer = GameSerializer(game, payload, partial=True)
            update = 'room'
            
            
        elif request.data['update'] == 'update_aswang':
            payload = {
                'aswang_limit' : request.data['limit']
            }
            message = 'Game settings updated'
            serializer = GameSerializer(game, data=payload, partial=True)
            update = 'aswang'

        if serializer.is_valid():
            
            serializer.save()
            new_aswang_limit = 1
            
            context['message'] = 'Game settings updated'
            
            if update == 'room':
                limit = serializer.validated_data['room_limit']
                new_aswang_limit = serializer.data['aswang_limit']
                
            elif update == 'aswang':
                limit = serializer.validated_data['aswang_limit']
                
            data = {
                'type': 'send_update_message',
                'message': message,
                'sender': 'SERVER',
                'limit': limit,
                'update': update,
                'new_aswang_limit': new_aswang_limit
            }
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_update_message',
                    'data': data
                }
            )
            return Response(status=200, data=serializer.data)
        
        context['message'] = 'Not saved'
        return Response(status=400)
    
    
    
@api_view(['POST'])
def startGameSession(request):
    
    context = {}
    code = request.data['code']
    channel_layer = get_channel_layer()
    try: 
        game = Game.objects.get(room_code=code)
    except:
        context['message'] = 'Game not found'
        return Response(context, status=400)
    
    # change player and game status
    if game:
        game.has_started = True
        game.room_state = 'IN_GAME'
        players = game.players.all()

        playerDict = assignRole(players=players, aswang_limit=game.aswang_limit)
            
        data = {
            'type': 'game_start',
            'message': 'GAME START',
            'sender': 'SERVER',

        }
        
        # broadcast message to group to redirect users to game view
        async_to_sync(channel_layer.group_send)(
            f'room_{code}',
            {
                'type': 'send_message',
                'data': data
            }
        )
        
        # each player in team will receive their role in the frontend, only visible to them 
        for player, role in playerDict.items():
            print(player, role)
            send_role.delay(player, code, role)
        
        phaseCountdown.delay(code)
        game.save()
        context['message'] = 'OK'
        return Response(context, status=200)
    else:
        context['message'] = 'Game not found'
        return Response(context, status=400)
    
    
    
@api_view(['POST'])
def selectTarget(request):
    
    context = {}
    
    channel_layer = get_channel_layer()
    
    player = request.data['player']
    code = request.data['code']
    role = request.data['role']
    
    
    game = get_object_or_404(Game, room_code=code)
    target = Player.objects.get(username=request.data['target'])
    
    
    if role == 'mangangaso':
        next_role = searchAswangRole(game=game, role='mangangaso')
        target.is_protected = True
        print(next_role)
        role = next_role
        
    
    elif role == 'aswang - manduguro':
        target.alive = False  
        target.eliminated_on_night = int(game.night_count)  
        target.save()
        
        
        # only if there is 1 aswang in the game, immediately set
        # but if there are two aswangs, they will select target simultaneously
        
        # need to check if players with these roles are alive, if true then change role to the corresponding role, 
        # if both are not alive, then skip role and change phase 
        role_babaylan = checkifBabaylanAlive(game=game)
        role_manghuhula = checkifManghuhulaAlive(game=game)
        
        if role_babaylan == True:
            role = 'babaylan'
        elif role_manghuhula == True:
            role = 'manghuhula'
        else:
            role = None
        
    
    elif role == 'aswang - manananggal':
        
        if target.is_protected == False:
            target.eliminated_on_night = int(game.night_count)  
            target.alive = False
        else:
            # target will live but will render mangangaso ineffective next night
            mangangaso = game.players.filter(alive=True, role='mangangaso').first()
            if mangangaso:
                mangangaso.skip_turn = True
                mangangaso.save()
            
        # need to check if players with these roles are alive, if true then change role to the corresponding role, 
        # if both are not alive, then skip role and change phase 
        
        role_babaylan = checkifBabaylanAlive(game=game)
        role_manghuhula = checkifManghuhulaAlive(game=game)
        
        
        if role_babaylan == True:
            role = 'babaylan'
        elif role_manghuhula == True:
            role = 'manghuhula'
        else:
            role = None

        
    elif role == 'aswang - berbalang':
        # can only eliminate unprotected players
        if target.is_protected == False:
            target.eliminated_on_night = int(game.night_count)  
            target.alive = False
        else:
            pass
        target.save()
        
        role_babaylan = checkifBabaylanAlive(game=game)
        role_manghuhula = checkifManghuhulaAlive(game=game)
        
        if role_babaylan == True:
            role = 'babaylan'
        elif role_manghuhula ==True:
            role = 'manghuhula'
        else:
            role = None
        

    elif role == 'babaylan':
        
        if target.alive == False:
            target.revived_on_night = int(game.night_count)
            target.alive = True
        else:
            pass
            
        role_manghuhula = checkifManghuhulaAlive(game=game)
        print('manghuhula alive?', role_manghuhula)
        if role_manghuhula == True:
            role = 'manghuhula'
        else:
            role = None
        
        
    elif role == 'manghuhula':
        role_of_target = target.role
        #context['role_of_target'] = role_of_target
        async_to_sync(channel_layer.group_send)(
            f'{player}_{code}',
            {
                'type': 'send_message',
                'data': {
                    'type': 'guess_picked',
                    'message': f"player's role is {role_of_target}",
                }
            }
        )
        role = None
    
    target.save()
    
    if role is not None:
        # we immediately go to next phase which is dicussion or voting
        data = {
            'type': 'update_roleTurn',
            'role': role,
        }
        
        async_to_sync(channel_layer.group_send)(
            f'room_{code}',
            {
                'type': 'send_message',
                'data': data
            }
        )
        context['message'] = 'OK'
        return Response(context, status=200)
    
    else:
        # change phase
        print('what')
        context['message'] = 'night done'
        switchToNextPhase.delay(code)
        return Response(context, status=200)
    
    
@api_view(['PATCH'])
def votePlayer(request):
    
    context = {}
    
    # retrieve objects from other classes first
    print(request.data['vote_target'])
    try:
        player_that_voted = get_object_or_404(Player, username=request.data['player'])
        vote_target = get_object_or_404(Player, username=request.data['vote_target'])
        game = get_object_or_404(Game, room_code=request.data['code'])
        print(game)
    except:
        
        context['message'] = 'Not found'
        return Response(context, status=400)
    
    # assign vote target
    player_that_voted.vote_target = vote_target
    player_that_voted.save()
            
    context['message'] = 'Nice vote!' # lmao
    return Response(context, status=201)




def assignRole(players, aswang_limit):
    print('players here: ', players)
    max = 4
    count = int(aswang_limit) #parse to int for safety measures (got history with this potangina)
    player_role_dict = {}
    
    # initialize roles
    # there will be race condition issues here so try to come up with another way to assign roles
    roles = ['mangangaso', 'aswang', 'babaylan', 'manghuhula']
    aswang_roles = ['aswang - manduguro', 'aswang - manananggal', 'aswang - berbalang']
    
    for player in players:
        
        player.in_game = True
        if len(roles) != 0:

            num = random.randint(0, max)
            if num == 4:
                player.role = 'taumbayan'
                player.save()
                max -= 1
            #disregard num after that point
            else:
                role = random.choice(roles)

                # this will remove the other roles from the list so taumbayan will be left
                if role != 'taumbayan' and role != 'aswang':
                    player.role = role
                    roles.remove(role)
                
                # aswang role count will depend on aswang limit settings
                if role == 'aswang':
                    role_aswang = random.choice(aswang_roles)
                    player.role = role_aswang
                    count -= 1
                    # when count reaches to zero, this means no more players will be assigned aswang
                    if count == 0:
                        roles.remove(role)
        else:
            player.role = 'taumbayan'
        
        player.save()
        
        # add player and role to dictionary
        player_role_dict[f'{player.username}'] = player.role
    
    return player_role_dict
    

def searchAswangRole(game, role):
    
    players = game.players.all()
    
    # since there are three types of aswang that can be given at random.. we have to search the players in the game if any role exists
    if game.players.filter( Q(role='aswang - manduguro') | Q(role='aswang - manananggal') | Q(role='aswang - berbalang') ).exists():

        for player in players:
            
            if player.role == 'aswang - manduguro':
                return 'aswang - manduguro'
            
            elif player.role == 'aswang - manananggal':
                return 'aswang - manananggal'
            
            elif player.role == 'aswang - berbalang':
                return 'aswang - berbalang'
    else:
        return None
                

# checks the alive players' role, since after aswang its either babaylan or manghuhula, whichever one is alive (can be both)
def checkifBabaylanAlive(game):
    try:
        alive = game.players.filter(
            Q(alive=True) & 
            Q(eliminated_from_game=False) &
            Q(role='babaylan')
        ).first()
        print('babaylan found')
        if alive:
            return True
        else:
            return False
        
    except:
        return None
        
def checkifManghuhulaAlive(game):
    
    try:
        alive = game.players.filter(
            Q(alive=True) & 
            Q(eliminated_from_game=False) &
            Q(role='manghuhula')
        ).first()
        print('manghuhula found')
        if alive:
            return True
        else:
            return False
    except: 
        return None