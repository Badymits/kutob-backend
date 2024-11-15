from django.shortcuts import render, get_object_or_404
from rest_framework.response import Response
from rest_framework.decorators import api_view
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.db.models import Q

from .models import Game, Player
from .serializers import GameSerializer
from game.serializers import PlayersInLobby, PlayerVoteSerializer, PlayerSerializer
from game.services import set_player_connected_non_sync, set_player_disconnected_non_sync, set_game_turn
from .tasks import send_role, phaseCountdown, phaseInitialize
from django.core.cache import cache

import math
import random
from datetime import datetime, timedelta
from itertools import chain


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
            
            # add user to redis to keep track of player status: Connected or Disconnected
            #set_player_connected_non_sync(username=user.username, code=room_code)
            
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
            
            if game.has_ended == True:
                context['message'] = 'Cannot join room that has already ended'
                return Response(context, status=400)
            
            if game is not None and user is not None:
                game.players.add(user)
                user.game.add(game)
                user.in_lobby = True
                user.save()
                
                # add user to redis to keep track of player status: Connected or Disconnected
                #set_player_connected_non_sync(username=user.username, code=code)

                players = PlayersInLobby(game.players.all(), many=True).data
                
                
                context['players'] = players
                context['player_count'] = game.room_limit
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
    
    channel_layer = get_channel_layer()
    
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
            player.can_execute = False
            player.night_target = False
            player.turn_done = False
            
            player.eliminated_on_night = 0
            player.revived_on_night = 0
            
            player.vote_target = None
            player.eliminated_from_game = False
            
            player.in_game = False
            player.in_lobby = False
            player.save() 
            
            if game.owner == player:
                random_player = getRandomPlayerInRoom(game=game)
                #set_player_disconnected_non_sync(username=random_player.username, code=code)
                if random_player is not None:
                    player = PlayerSerializer(random_player).data
                    print(player.get('username'))
                    async_to_sync(channel_layer.group_send)(
                        f'room_{code}',
                        {
                            'type': 'send_message',
                            'data': {
                                'type': 'update_room_owner',
                                'player': player,
                                "message": f'{player.get("username")} is the new Room Owner',
                                "sender": "SERVER",
                            }
                        }
                    )
                else:
                    pass
            
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
    

def getRandomPlayerInRoom(game):
    

    player_list = list(game.players.all())
    print(player_list)
    if len(player_list) != 0:
        player = random.choice(player_list)
        
        game.owner = player
        game.save()
        
        return player
    else:
        return None

    
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
    
    # set turn to mangangaso
    set_game_turn(code=code, role_turn='mangangaso')
    
    try: 
        game = Game.objects.get(room_code=code)
        
    except Game.DoesNotExist:
        
        context['message'] = 'Game not found'
        return Response(context, status=400)
    
    
    #ready_players = checkIfPlayersReady(game)
    
    # if not ready_players:
    #     context['message'] = 'Players not yet ready'
    #     return Response(context, status=400)    
    
    
    # change player and game status
    if game:
        game.has_started = True
        game.room_state = 'IN_GAME'
        players = game.players.all().order_by('?')
        

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


def checkIfPlayersReady(game):
    
    for player in game.players.all():
        if not player.is_ready:
            return False
    
    return True
    
    
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
    
    if role == 'No role':
        context['aswang_message'] = 'Cannot select fellow aswang as target'
        return Response(context, status=400)
    
    elif role == 'No role mangangaso':
        context['mangangaso_message'] = 'Cannot select yourself as target'
        return Response(context, status=400)
    
    elif role == 'None': # a different none
        context['message'] = 'No aswang detected. Must be a connection problem'
        return Response(context, status=400)
        
    elif role is not None:
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
    channel_layer = get_channel_layer()
    code = request.data.get('code')
    
    try:
        player_that_voted = get_object_or_404(Player, username=request.data['player'])
        vote_target = get_object_or_404(Player, username=request.data['vote_target'])
        game = get_object_or_404(Game, room_code=code)
        
    except Exception as e:
        print(f'error {e}')
        context['message'] = 'Not found'
        return Response(context, status=400)
    
    # assign vote target
    player_that_voted.vote_target = vote_target
    player_that_voted.save()
    
    # only get players that have voted
    votes = PlayerVoteSerializer(game.players.filter(
        Q(alive=True) & Q(eliminated_from_game=False) & ~Q(vote_target=None)
    ), many=True).data
    
    # send votes to frontend for icons of who voted for which user
    async_to_sync(channel_layer.group_send)(
        f'room_{code}',
        {
            'type': 'send_message',
            'data': {
                'type': 'update_votes',
                'votes': votes
            }
        }
    )
    
            
    context['message'] = 'Nice vote!'
    return Response(context, status=201)


def roleTargetProcess(role, player, game, target, code):
    
    channel_layer = get_channel_layer()
    
    if role == 'mangangaso':
        
        next_role = searchAswang(game=game)
        aswang_players = getAswangPlayers(game=game)
        
        
        if not player.can_execute: # player refers to self

            target.is_protected = True
            target.save()
            role = next_role.role
        else:
            if target.username == player.username:
                role = 'No role mangangaso'
                return role   
            
            target.night_target = True
            target.save()
            role = next_role.role
            
        # end the game since there is no point in continuing the game when there is no aswang left
        if next_role is None and not aswang_players:
            game.game_phase = 4
            game.save()
            set_game_turn(code=code, role_turn='mangangaso')
            phaseInitialize.apply_async(args=[code])
            
            # a different None type since the keyword None
            role = 'None' 
            return role

        set_game_turn(code=code, role_turn=next_role.role)
        async_to_sync(channel_layer.group_send)(
            f'{next_role.username}_{code}',
            {
                'type': 'send_message',
                'data': {
                    'type': 'player_select_target', # helps with multiple aswang during target select
                    'player': next_role.username,
                    'aswang_players': aswang_players
                }
            }
        )
        
    
    elif role == 'aswang - mandurugo':
        
        # mark the player to eliminate
        player_obj = target
        if player_obj.role in ['aswang - mandurugo', 'aswang - manananggal', 'aswang - berbalang']:
            
            role = 'No role'
            return role
        
        player_obj.night_target = True
        player_obj.save()
        
        """
        need to check if players with these roles are alive, if true then change role to the corresponding role, 
        if both are not alive, then skip role and change phase 
        
        """
        
        player.turn_done = True
        player.save()
        
        aswang_role = searchAswang(game=game)
        aswang_players = getAswangPlayers(game=game)

        if aswang_role:
            role = aswang_role.role
            next_player = aswang_role.username
        else: 
            get_role = searchBabaylanOrManghuhula(game=game) # returns player obj
            if get_role:
                role = get_role.role
                next_player = get_role.username
                
            else:
                role = None
        
        if role is not None:
            set_game_turn(code=code, role_turn=role)
            async_to_sync(channel_layer.group_send)(
                f'{next_player}_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'player_select_target', # helps with multiple aswang during target select
                        'player': next_player,
                        'aswang_players': aswang_players if role == 'aswang - mandurugo' or role == 'aswang - manananggal' or role == 'aswang - berbalang' else None
                    }
                }
            )
        
    
    elif role == 'aswang - manananggal':
        
        if target.role == 'aswang - mandurugo' or target.role == 'aswang - manananggal' or target.role == 'aswang - berbalang':
            
            role = 'No role'
            return role

        
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
        
        player.turn_done = True
        player.save()

        """
        need to check if players with these roles are alive, if true then change role to the corresponding role, 
        if both are not alive, then skip role and change phase 
        """
        
        aswang_role = searchAswang(game=game)
        aswang_players = getAswangPlayers(game=game)
        
        if aswang_role:
            
            role = aswang_role.role
            next_player = aswang_role.username
            
        else: 
            get_role = searchBabaylanOrManghuhula(game=game) # returns player obj
            if get_role:
                role = get_role.role
                next_player = get_role.username
            else:
                role = None
        
        if role is not None:    
            set_game_turn(code=code, role_turn=role)
            async_to_sync(channel_layer.group_send)(
                f'{next_player}_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'player_select_target', # helps with multiple aswang during target select
                        'player': next_player,
                        'aswang_players': aswang_players if role == 'aswang - mandurugo' or role == 'aswang - manananggal' or role == 'aswang - berbalang' else None
                    }
                }
            )
        #redis_client.set
        
    elif role == 'aswang - berbalang':
        
        if target.role == 'aswang - mandurugo' or target.role == 'aswang - manananggal' or target.role == 'aswang - berbalang':
            
            role = 'No role'
            return role
        #redis_client.set
        
        # can only eliminate unprotected players
        if target.is_protected == False:
            player_obj = target
            player_obj.night_target = True
            player_obj.save()

        player.turn_done = True
        player.save()
        
        aswang_role = searchAswang(game=game)
        aswang_players = getAswangPlayers(game=game)
        
        if aswang_role:
            
            role = aswang_role.role
            next_player = aswang_role.username
            set_game_turn(code=code, role_turn=role)
        else: 
            get_role = searchBabaylanOrManghuhula(game=game) # returns player obj
            if get_role:
                role = get_role.role
                next_player = get_role.username
            else:
                role = None
            
        if role is not None:
            async_to_sync(channel_layer.group_send)(
                f'{next_player}_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'player_select_target', # helps with multiple aswang during target select
                        'player': next_player,
                        'aswang_players':aswang_players if role == 'aswang - mandurugo' or role == 'aswang - manananggal' or role == 'aswang - berbalang' else None
                    }
                }
            )
        

    elif role == 'babaylan':
        
        # check if self or any other player is targeted for the night
        if player.night_target or target.night_target:
            player_obj = target
            player_obj.night_target = False
            player_obj.save()
            
        role_manghuhula = checkRoleStatus(game=game, role='manghuhula') # returns player obj
        #redis_client.set
        if role_manghuhula:
            role = role_manghuhula.role
            next_player = role_manghuhula.username
            
            set_game_turn(code=code, role_turn=role)
            
            async_to_sync(channel_layer.group_send)(
            f'{next_player}_{code}',
            {
                'type': 'send_message',
                'data': {
                    'type': 'player_select_target', 
                    'player': next_player,
                }
            }
        )
        else:
            role = None

    elif role == 'manghuhula':
        role_of_target = target.role
        
        set_game_turn(code=code, role_turn=role)
        
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
        #redis_client.set
    return role


def assignRole(players, aswang_limit): # order of players are shuffled
    
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
    aswang_roles = ['aswang - mandurugo', 'aswang - manananggal', 'aswang - berbalang'] 
    #'aswang - mandurugo'
    
    for player in players:
        player.in_lobby = False
        player.in_game = True
        
        while True:
            role = random.choice(roles)
            
            # we must populate dictionary with the most important roles first before assigning taumbayan
            if len(player_role_dict) >= (len(roles) + (aswang_limit - 1)):
                player.role = 'taumbayan'
                player.save()
                player_role_dict[f'{player.username}'] = player.role
                break
            
            # if important role is not yet in dictionary, add it
            # this will catch the chances where the role is aswang, if its not yet in the role dictionary, then the
            # aswang assign logic will happen here
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
            
            # if the aswang role is already in the dictionary and the role given is aswang
            # as long as the count is not zero, this will run.
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


def getAswangPlayers(game):
    
    aswang_players = PlayersInLobby(game.players.filter(
        Q(role__startswith='aswang') & Q(alive=True) & Q(eliminated_from_game=False) 
    ), many=True).data
    
    if not aswang_players:
        return None
    
    return aswang_players



def searchAswang(game):
    
    aswang_player = game.players.filter(Q(role__startswith='aswang') & Q(turn_done=False) & Q(eliminated_from_game=False) & Q(alive=True)).first()
    if not aswang_player:
        return None
    else:
        return aswang_player


def searchBabaylanOrManghuhula(game):
    
    role_babaylan = checkRoleStatus(game=game, role='babaylan')
    role_manghuhula = checkRoleStatus(game=game, role='manghuhula')
    
    if role_babaylan:
        role = role_babaylan
    elif role_manghuhula:
        role = role_manghuhula
    else:    
        role = None
        
    return role


# checks the alive players' role, since after aswang its either 
# babaylan or manghuhula, whichever one is alive (can be both)
def checkRoleStatus(game, role):
    try: 
        player = game.players.filter(
            Q(alive=True) & 
            Q(eliminated_from_game=False) &
            Q(role=role)
        ).first()
        
        if role == 'babaylan':
            if player:
                return player
            else:
                return None
            
        elif role == 'manghuhula':
            if player:
                return player
            else:
                return None
            
        else:
            return None
    except Exception as e:
        print(f'error {e}')
        return None
