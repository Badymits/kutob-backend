from django.shortcuts import render, get_object_or_404
from rest_framework.response import Response
from rest_framework.decorators import api_view
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.db.models import Q

from .models import Game, Player
from .serializers import GameSerializer
from game.serializers import PlayersInLobby 
from .tasks import send_role, phaseCountdown, phaseInitialize
from django.core.cache import cache

import math
import random
from datetime import datetime, timedelta

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
    try:
        user = Player.objects.get(username=request.data['owner'])
        
        room_code = createCode(8)
        context['code'] = room_code
        
        # check if there is existing lobby
        try:
            #game = get_object_or_404(Game, room_code=room_code)
            
            game = Game.objects.create(
                owner=user,
                room_code=room_code
            )
            
            game.players.add(user)
            user.game.add(game)
            
            user.in_game = False
            user.in_lobby = True
            user.save()
            
            game.save()

            context['message'] = 'Lobby created'
            return Response(context, status=200)
        except ValueError: 
            context['message'] = 'Lobby already exists'
            
            return Response(context, status=400)
            
            
    except Player.DoesNotExist:
        context['message'] = 'Inactivity detected, redirecting to register'
        return Response(context, status=400)
    



@api_view(['POST'])
def joinRoom(request):
    
    context = {}
    
    player = request.data['player']
    code = request.data['code']
    
    print(request.session)
    # search game obj
    try:
        game = Game.objects.get(room_code=code.upper())
        
        try:
            user = Player.objects.get(username=player)
        except Player.DoesNotExist:
            user = None
            context['message'] = 'An error ocurred, player does not exist'
            return Response(context, status=400)
        
        # users cannot enter if the room is already at the player limit count
        if int(game.room_limit) > game.players.all().count():
            
            if game is not None and user is not None:
                game.players.add(user)
                user.game.add(game)
                user.in_lobby = True
                user.save()
                # retrieve all players in the room
                players = game.players.all().values_list('username', flat=True)
                
                
                context['players'] = players
                context['message'] = 'Room found'
                return Response(context, status=200)
            
            else:
                context['message'] = 'Error ocurred'
                return Response(context)
        else:
            context['message'] = 'Room is full, cannot join',
            return Response(context, status=400)
            
    except Game.DoesNotExist:
        game = None
        context['message'] = 'Room does not exist'
        return Response(context, status=404)

    
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
            
            # to track the last time since user played, will be used to check if user is inactive 
            if game.has_ended or not player.in_lobby and not player.in_game:
                player.time_since_last_game = datetime.now()
            
            # reset player state
            player.role = ''
            player.alive = True
            
            player.is_protected = False
            player.skip_turn = False
            player.night_skip = 0
            player.night_target = False
            
            player.eliminated_on_night = 0
            player.revived_on_night = 0
            
            player.vote_target = None
            player.eliminated_from_game = False
            
            player.in_game = False
            player.in_lobby = False
            player.save() 
            
            
            context['message'] = 'Left the room'
            
            # delete game room if last player in the room left, MOVE THIS TO CELERY BEAT SCHEDULED TASK
            # if Game.objects.filter(players=None) and game.has_ended:
            #     game.delete()
            
        else:
            context['message'] = 'Player does not exist'
        return Response(context)
    except Game.DoesNotExist:
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
        except Game.DoesNotExist:
            context['message'] = 'Game room does not exist'
            return Response(context)
        
        player_count = game.players.all().count()
        
        if request.data['update'] == 'update_room':
            
            """ 
            
            check first if players in room are more than the requested limit
            if it is, then return message saying they cannot change, else, proceed with logic
            
            5-7 players == 1 aswang limit
            8-9 players == 2 aswang limit
            10 players == 3 aswang limit
            
            """
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
    except Game.DoesNotExist:
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
        
        # each player in team will receive their respective role in the frontend
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


    code = request.data['code']
    role = request.data['role']
    
    
    game = get_object_or_404(Game, room_code=code)
    target = Player.objects.get(username=request.data['target'])
    player = Player.objects.get(username=request.data['player']) # refers to self
    
    
    role = roleTargetProcess(role=role, player=player, game=game, target=target, code=code)
    
    
    if role is not None:
        # next player with major role to select target
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
        context['message'] = 'night done'
        phaseInitialize.delay(code)
        return Response(context, status=200)
    
    
@api_view(['PATCH'])
def votePlayer(request):
    
    context = {}
    
    try:
        player_that_voted = get_object_or_404(Player, username=request.data['player'])
        vote_target = get_object_or_404(Player, username=request.data['vote_target'])
        
    except Exception as e:
        print(f'error {e}')
        context['message'] = 'Not found'
        return Response(context, status=400)
    
    # assign vote target
    player_that_voted.vote_target = vote_target
    player_that_voted.save()
            
    context['message'] = 'Nice vote!'
    return Response(context, status=201)


def roleTargetProcess(role, player, game, target, code):
    
    channel_layer = get_channel_layer()
    
    if role == 'mangangaso':
        next_role = searchAswang(game=game)
        target.is_protected = True
        target.save()
        role = next_role
        
    
    elif role == 'aswang - manduguro':
        
        # mark the player to eliminate
        player_obj = target
        player_obj.night_target = True
        player_obj.save()
        
        """
        need to check if players with these roles are alive, if true then change role to the corresponding role, 
        if both are not alive, then skip role and change phase 
        
        """
        aswang_role = searchAswang(game=game)
        
        if aswang_role:
            role = aswang_role
        else: 
            role = searchBabaylanOrManghuhula(game=game)
        
    
    elif role == 'aswang - manananggal':
        
        
        if target.is_protected == False:

            # mark the player to eliminate
            player_obj = target
            player_obj.night_target = True
            player_obj.save()

            
        # target will live but will render mangangaso ineffective next night
        elif target.is_protected == True:
            mangangaso = game.players.filter(Q(alive=True) & Q(role='mangangaso')).first()
            
            if mangangaso: 
                player_obj = mangangaso
                player_obj.skip_turn = True
                player_obj.night_skip = int(game.night_count) + 2
                player_obj.save()

        """
        need to check if players with these roles are alive, if true then change role to the corresponding role, 
        if both are not alive, then skip role and change phase 
        """
        
        aswang_role = searchAswang(game=game)
        
        if aswang_role:
            role = aswang_role
        else: 
            role = searchBabaylanOrManghuhula(game=game)

        
    elif role == 'aswang - berbalang':
        # can only eliminate unprotected players
        if target.is_protected == False:
            player_obj = target
            player_obj.night_target = True
            player_obj.save()

        
        aswang_role = searchAswang(game=game)
        
        if aswang_role:
            role = aswang_role
        else: 
            role = searchBabaylanOrManghuhula(game=game)
        

    elif role == 'babaylan':
        
        # check if self or any other player is targeted for the night
        if player.night_target or target.night_target:
            player_obj = target
            player_obj.night_target = False
            player_obj.save()
            
        role_manghuhula = checkRoleStatus(game=game, role='manghuhula')
        
        if role_manghuhula == True:
            role = 'manghuhula'
        else:
            role = None
        
        
    elif role == 'manghuhula':
        role_of_target = target.role
        async_to_sync(channel_layer.group_send)(
            f'{player.username}_{code}',
            {
                'type': 'send_message',
                'data': {
                    'type': 'guess_picked',
                    'message': f"player's role is {role_of_target}",
                }
            }
        )
        role = None
        
    return role


def assignRole(players, aswang_limit):
    
    """
    :10 players and 3 aswang == 6 important figures (mangangaso, babaylan, manghuhula, 3 aswang) 
    9-8 players and 2 aswang == 5 important figures (3 roles above and 2 aswang) 
    7-5 players and 1 aswang == 4 important figures (3 roles above and 1 aswang) 
    
    remaining players in the group will be the taumbayan
    """

    count = int(aswang_limit)
    player_role_dict = {}
    
    # initialize roles
    roles = ['mangangaso', 'aswang', 'babaylan', 'manghuhula']
    aswang_roles = ['aswang - manduguro', 'aswang - manananggal'] # remove aswang berbalang for the mean time

    
    for player in players:
        player.in_lobby = False
        player.in_game = True
        
        while True:
            role = random.choice(roles)
            
            # we must populate dictionary with the most important roles first before assigning taumbayan
            if len(player_role_dict) == (len(roles) + (aswang_limit - 1)):
                player.role = 'taumbayan'
                player.save()
                player_role_dict[f'{player.username}'] = player.role
                break
            
            # if important role is not yet in dictionary, add it
            if role not in player_role_dict.values() :
                
                if role != 'aswang':
                    player.role = role
                    player.save()
                    player_role_dict[f'{player.username}'] = player.role
                    
                    break
                
                if role == 'aswang' and count != 0:
                    aswang_role = random.choice(aswang_roles)
                    count -= 1
                    player.role = aswang_role
                    player.save()
                    
                    player_role_dict[f'{player.username}'] = player.role
                    break
            
            elif (role == 'aswang') and count != 0:

                aswang_role = random.choice(aswang_roles)
                count -= 1
                player.role = aswang_role
                player.save()
    
                # add player and role to dictionary
                player_role_dict[f'{player.username}'] = player.role
                
                break       
    player.save()
    
    return player_role_dict
    

def searchAswang(game):
    
    aswang_player = game.players.filter(
        (Q(role='aswang - manduguro') | Q(role='aswang - manananggal') | Q(role='aswang - berbalang')) 
        & Q(night_target=None)
    ).first()
    
    if not aswang_player:
        return None
    else:
        return aswang_player.role


def searchBabaylanOrManghuhula(game):
    
    role_babaylan = checkRoleStatus(game=game, role='babaylan')
    role_manghuhula = checkRoleStatus(game=game, role='manghuhula')
    
    if role_babaylan == True:
        role = 'babaylan'
    elif role_manghuhula == True:
        role = 'manghuhula'
    else:    
        role = None
        
    return role


# checks the alive players' role, since after aswang its either 
# babaylan or manghuhula, whichever one is alive (can be both)
def checkRoleStatus(game, role):
    try: 
        alive = game.players.filter(
            Q(alive=True) & 
            Q(eliminated_from_game=False) &
            Q(role=role)
        ).first()
        
        if role == 'babaylan':
            if alive:
                return True
            else:
                return False
            
        elif role == 'manghuhula':
            if alive:
                return True
            else:
                return False
            
        else:
            return None
    except Exception as e:
        print(f'error {e}')
        return None
