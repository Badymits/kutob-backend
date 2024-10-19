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
from datetime import datetime

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
    except ValueError: 
        context['message'] = 'Lobby already exists'

        
    return Response(context)



@api_view(['POST'])
def joinRoom(request):
    
    context = {}
    
    player = request.data['player']
    code = request.data['code']
    
    print(request.session)
    # search game obj
    try:
        game = Game.objects.get(room_code=code)
    except ValueError:
        game = None
    
    if game is None:
        context['message'] = 'Room does not exist'
        return Response(context, status=404)
    
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
            if game.has_ended:
                player.time_since_last_game = datetime.now()
            
            #if player.in_game == True: 
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
            
            # delete game room if last player in the room left, 
            # if Game.objects.filter(players=None):
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
    
    
    if role == 'mangangaso':
        next_role = searchAswangRole(game=game)
        target.is_protected = True
        target.save()
        print(next_role)
        role = next_role
        
    
    elif role == 'aswang - manduguro':

        if target.role == 'babaylan' or target.role == 'manghuhula':
            player_obj = target
            player_obj.night_target = True
            player_obj.save()
        else:
            target.alive = False
            target.eliminated_on_night = int(game.night_count)
            target.save()
        
        """
        only if there is 1 aswang in the game, immediately set
        but if there are two aswangs, they will select target simultaneously
        
        need to check if players with these roles are alive, if true then change role to the corresponding role, 
        if both are not alive, then skip role and change phase 
        
        """
        
        role_babaylan = checkRoleStatus(game=game, role='babaylan')
        role_manghuhula = checkRoleStatus(game=game, role='manghuhula')
        
        if role_babaylan == True:
            role = 'babaylan'
        elif role_manghuhula == True:
            role = 'manghuhula'
        else:    
            role = None
        
    
    elif role == 'aswang - manananggal':
        
        
        if target.is_protected == False:
            # for reference in phase 5/ day announcement phase
            if target.role == 'babaylan' or target.role == 'manghuhula':
                player_obj = target
                player_obj.night_target = True
                player_obj.save()
                
            # if its a different role, eliminate player
            else:
                target.alive = False
                target.eliminated_on_night = int(game.night_count)
                target.save()
            
        elif target.is_protected == True:
            # target will live but will render mangangaso ineffective next night
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
        
        role_babaylan = checkRoleStatus(game=game, role='babaylan')
        role_manghuhula = checkRoleStatus(game=game, role='manghuhula')
        
        
        if role_babaylan == True:
            role = 'babaylan'
        elif role_manghuhula == True:
            role = 'manghuhula'
        else:
            role = None

        
    elif role == 'aswang - berbalang':
        # can only eliminate unprotected players
        if target.is_protected == False:
            if target.role == 'babaylan' or target.role == 'manghuhula':
                player_obj = target
                player_obj.night_target = True
                player_obj.save()
            else:
                target.eliminated_on_night = int(game.night_count)  
                target.alive = False
        else:
            pass
        target.save()
        role_babaylan = checkRoleStatus(game=game, role='babaylan')
        role_manghuhula = checkRoleStatus(game=game, role='manghuhula')
        
        if role_babaylan == True:
            role = 'babaylan'
        elif role_manghuhula ==True:
            role = 'manghuhula'
        else:
            role = None
        

    elif role == 'babaylan':
        
        # check if self or manghuhula is targeted for the night
        if player.night_target or target.night_target:
            player_obj = target
            player_obj.night_target = False
            #player_obj.revived_on_night = int(game.night_count)
            player_obj.save()
        
        
        # refers to the target they selected, can be themselves
        if target.alive == False:
            target.revived_on_night = int(game.night_count)
            target.alive = True
            target.save()
        else:
            pass
            
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
        phaseInitialize.delay(code)
        return Response(context, status=200)
    
    
@api_view(['PATCH'])
def votePlayer(request):
    
    context = {}
    
   
    try:
        player_that_voted = get_object_or_404(Player, username=request.data['player'])
        vote_target = get_object_or_404(Player, username=request.data['vote_target'])
        
        game = get_object_or_404(Game, room_code=request.data['code'])
        #vote_target = game.players.filter(Q(game=game) & Q(username=request.data['vote_target'])).first()
        
    except:
        
        context['message'] = 'Not found'
        return Response(context, status=400)
    
    # assign vote target
    player_that_voted.vote_target = vote_target
    player_that_voted.save()
            
    context['message'] = 'Nice vote!' # lmao
    return Response(context, status=201)



def assignRole(players, aswang_limit):

    count = int(aswang_limit) #parse to int for safety measures (got history with this potangina)
    player_role_dict = {}
    
    # initialize roles
    # there will be race condition issues here so try to come up with another way to assign roles
    roles = ['mangangaso', 'aswang', 'babaylan', 'manghuhula']
    aswang_roles = ['aswang - manduguro', 'aswang - manananggal'] # remove aswang berbalang for the mean time
    
    # temp aswang arrays
    #aswang_roles = ['aswang - berbalang']
    
    for player in players:
        player.in_lobby = False
        player.in_game = True
        
        while True:
            role = random.choice(roles)
            
            if role not in player_role_dict.values():
                if role == 'aswang':
                    aswang_role = random.choice(aswang_roles)
                    count -= 1
                    player.role = aswang_role
                    player.save()
                    
                    if count == 0:
                        roles.remove('aswang')
                else:
                    player.role = role
                    player.save()
                    
                player_role_dict[f'{player.username}'] = player.role
                
                break
            
            elif (role == 'aswang') and (role=='aswang' not in  player_role_dict.values()):

                aswang_role = random.choice(aswang_roles)
                count -= 1
                player.role = aswang_role
                player.save()
                
                if count == 0:
                    role = random.choice(roles)
                    player.role = role
                    player.save()
    
                # add player and role to dictionary
                player_role_dict[f'{player.username}'] = player.role
                
                break
            else:
                player.role = 'taumbayan'
                player.save()
                
                # add player and role to dictionary
                player_role_dict[f'{player.username}'] = player.role
                
                break
    player.save()
    
    return player_role_dict
    

def searchAswangRole(game):
    
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
    except:
        return None
