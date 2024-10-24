from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone

from celery import shared_task
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from time import sleep
from collections import Counter
from datetime import datetime, timedelta

from .models import Game, Player
from .serializers import PlayersInLobby, PlayerSerializer, WinnersSerializer


channel_layer = get_channel_layer()

@shared_task
def send_role(player,code,role):

    # sends message to unqiue channel where user is the only one to receive this message
    
    async_to_sync(channel_layer.group_send)(
        f'{player}_{code}',
        {
            'type': 'send_message',
            'data': {
                'type': 'role_show',
                'role': role,
                'message': f'your role is {role}',
                'sender': 'SERVER'
            }
        }
    )

# alternative solution instead of it being handled by the frontend, this ensures synchronicity of all clients related to the game
@shared_task
def phaseCountdown(code): 
    print('sending')
    try:
        game = get_object_or_404(Game, room_code=code)
    except:
        game = None

    if game:
        print('game countdown current phase: ',game.game_phase)
        
        if int(game.game_phase) == 1:
            countdown = 10
           
        elif int(game.game_phase) == 2:
            game.night_count += 1
            countdown = 5
            game.save()
            game_time = game.night_count

            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data':{
                        'type': 'night_count',
                        'count': int(game_time)
                    }
                }
            )
            
        elif int(game.game_phase) == 4:
            game.day_count += 1
            game.save()
            countdown = 5
            game_time = game.day_count

            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data':{
                        'type': 'day_count',
                        'count': int(game_time)
                    }
                }
            )
            
            
        elif int(game.game_phase) == 5:
            countdown = 5
            
            
        elif int(game.game_phase) == 6:
             # 1 minute for players to discuss and decide to vote
            countdown = 60
            
            
        elif int(game.game_phase) == 7:
             # only given 45 secs to cast their vote
            countdown = 45
            
            
            
        else:
            print('no phase')
            countdown = 10
            
        if int(game.game_phase) > 9:
            return None
    
        # countdown for transition to next phase
        for i in range(countdown):
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'countdown',
                        'countdown': countdown # will be shown in the UI
                    }
                }
            )
            sleep(1)
            countdown -= 1
        
        phaseInitialize.delay(code)
    else:
        return None

# changes UI in frontend. Here we sort of "initialize" the phase, what are the things needed in each phase that is then reflected in the frontend
@shared_task
def phaseInitialize(code):

    game = Game.objects.get(room_code=code)
    phase = int(game.game_phase) + 1

        
    # the player select target phase, if mangangaso is not alive, then the aswang will be the first player to select their target
    if phase == 3:
        
        player_list = game.players.all()
    
        new_players_state_list = refreshPlayerState(player_list)
        
        # serialize the player list then send to frontend
        current_players = PlayersInLobby(new_players_state_list, many=True).data
        
        
        async_to_sync(channel_layer.group_send)(
            f'room_{code}',
            {
                'type': 'send_message',
                'data': {
                    'type': 'alive_players_list',
                    'player_list': current_players
                }
            }
        )
        
        # this happens immediately whereas the view 'selectTarget' only happens when there is a request from the frontend
        mangangaso = game.players.filter(role='mangangaso').first()
        next_role = searchAswangRole(game)
        
        # mangangaso can protect if it has the same night count (since they will be rendered ineffective for a turn by the manananggal)
        if mangangaso.night_skip == game.night_count:
            mangangaso.skip_turn = False
            mangangaso.save()
            
        if game.night_count == 6:
            mangangaso.can_execute = True
            mangangaso.save()
        
        # this will only show if the aswang type is manananggal
        if mangangaso.skip_turn == True and mangangaso.alive == True and mangangaso.eliminated_from_game == False and next_role == 'aswang - manananggal' and int(mangangaso.night_skip) != (game.night_count):
            data = {
                'type': 'update_roleTurn',
                'role': next_role,
                'mangangaso_message' :'You are rendered ineffective during this night by the aswang, you cannot protect anyone'
            }
            
        
        elif mangangaso.alive == False or mangangaso.eliminated_from_game == True:
            data = {
                'type': 'update_roleTurn',
                'role': next_role,
            }
        else:
            data = {
                'type': 'update_roleTurn',
                'role': 'mangangaso'
            }

        async_to_sync(channel_layer.group_send)(
            f'room_{code}',
            {
                'type': 'send_message',
                'data': data
            }
        )
        
        # send update phase to frontend to select target of users
        async_to_sync(channel_layer.group_send)(
            f'room_{code}',
            {
                'type': 'send_message',
                'data': {
                    'type': 'next_phase',
                    'phase': phase
                }
            }
        )
        
        game.game_phase = phase
        game.save()
        
    # day announcement phase
    elif phase == 5:

        # execute night targets if there are any
        for player in game.players.filter(Q(alive=True) & Q(eliminated_from_game=False)):
            
            if player.night_target:
                player_obj = player
                player_obj.alive = False
                player.eliminated_on_night = int(game.night_count)
                player_obj.save()

        current_players = game.players.filter(Q(alive=True) & Q(eliminated_from_game=False))
        
        # the player count should consist of only aswang
        if int(current_players.count()) == 1 and current_players.filter(
                Q(role='aswang - manduguro') | 
                Q(role='aswang - manananggal') | 
                Q(role='aswang - berbalang')
                ).exists():

            game.winners = 'Mga Aswang'
            
            phase = 8
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'announce_winners',
                        'winners': 'Mga Aswang',
                        'message': 'There are no more players left aside from the aswang, Aswang wins!'
                    }
                }
            )
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'next_phase',
                        'phase': phase
                    }
                }
            )
            game.game_phase = phase
            game.has_ended = True
            game.save()
            
        # situations where the aswang selects themselves as the target for the night (bobo puta)
        elif current_players.count() == 1 and current_players.filter(~Q(role='aswang - manduguro') | ~Q(role='aswang - manananggal') | ~Q(role='aswang - berbalang')).exists():
            game.winners = 'Mga Taumbayan'
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'announce_winners',
                        'winners': 'Mga Taumbayan'
                    }
                }
            )
            phase = 9
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'next_phase',
                        'phase': phase
                    }
                }
            )
            game.game_phase = phase
            game.has_ended = True
            game.save()
            
            
        try:
            eliminated_players = game.players.filter(eliminated_on_night=game.night_count).count()
            revived_players = game.players.filter(revived_on_night=game.night_count).count()
            
        except:
            pass
            
        
        if eliminated_players > 0 and revived_players == 0:
            
            player = game.players.filter(eliminated_on_night=game.night_count).first()
            playerSerialized  = PlayerSerializer(player).data
            if eliminated_players > 1:
                message = f'There were {eliminated_players} vitims during the night'
            else:
                message = f'There was {eliminated_players} victim during the night'
                
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'announce',
                        'player_count': eliminated_players,
                        'player': playerSerialized,
                        'message': message
                    }
                }
            )
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'next_phase',
                        'phase': phase
                    }
                }
            )
            
            game.game_phase = phase
            game.save()
            
            phaseCountdown.delay(code)
            
        else:
            player = 'none'
            eliminated_players = 0
            message = 'There were no victims during the night'
        
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'announce',
                        'player_count': eliminated_players,
                        'player': player,
                        'message': message
                    }
                }
            )
            
        
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'next_phase',
                        'phase': phase
                    }
                }
            )
            
            game.game_phase = phase
            game.save()
            
            phaseCountdown.delay(code)
        
    # voting phase, send alive players so users can vote on any of them to be eliminated from the game
    elif phase == 7:
        current_players = PlayersInLobby(game.players.filter(Q(alive=True) & Q(eliminated_from_game=False)), many=True).data
        async_to_sync(channel_layer.group_send)(
            f'room_{code}',
            {
                'type': 'send_message',
                'data': {
                    'type': 'alive_players_list',
                    'player_list': current_players,
                }
            }
        )
        
        async_to_sync(channel_layer.group_send)(
            f'room_{code}',
            {
                'type': 'send_message',
                'data': {
                    'type': 'next_phase',
                    'phase': phase
                }
            }
        )
        
        game.game_phase = phase
        game.save()
        
        phaseCountdown.delay(code)
    
    # voting result phase, players will know if they eliminated the right player
    elif phase == 8:
        
        players = game.players.filter(Q(alive=True) & Q(eliminated_from_game=False))
        
        vote_list = []
        

        for i in players.iterator():
            if i.vote_target is not None: # to ignore players who have not voted during this phase
                vote_list.append(i.vote_target.username)
        
        result = most_common(vote_list)

        
        if result != 'tie':
            
            player_eliminated = Player.objects.get(username=result)
            player_eliminated.eliminated_from_game = True
            player_eliminated.save()
            
            current_players = game.players.filter(Q(alive=True) & Q(eliminated_from_game=False))
            
            # if aswang players are the only players left in the game, send to last phase
            if int(current_players.count()) == 1 and current_players.filter(
                    Q(role='aswang - manduguro') | 
                    Q(role='aswang - manananggal') | 
                    Q(role='aswang - berbalang')
                    ).exists():
                # send to last phase, announcement shit:
                game.winners = 'Mga Aswang'
                
                data = {
                    'type': 'announce_winners',
                    'winners': 'Mga Aswang',
                    'message': 'There are no more players left aside from the aswang, Aswang wins!'
                }
                
                phase = 8
                
            else:
                
                try:
                    player = get_object_or_404(Player, username=result)
                    player.eliminated_from_game = True
                    player.save()
                except:
                    player = ''
                
                if player.role == 'aswang - manduguro' or player.role == 'aswang - manananggal' or player.role == 'aswang - berbalang':
                    data = {
                        'type': 'is_aswang',
                        'eliminated': result,
                        'message': 'The player eliminated IS the aswang'
                    }
                    
                    game.winners = 'Mga Taumbayan' # send to winning phase (which is next phase, phase 9)
                    

                else: 
                    data = {
                        'type': 'not_aswang',
                        'eliminated': result,
                        'message': 'The player eliminated is NOT the aswang' # back to phase 2
                    }

        # in an event of a tie, send appropriate message to users
        else:
            data = {
                'type': 'vote_tie',
                'message': 'the vote is a TIE. no one will be eliminated'
            }
            
        async_to_sync(channel_layer.group_send)(
            f'room_{code}',
            {
                'type': 'send_message',
                'data': data
            }
        )
        async_to_sync(channel_layer.group_send)(
            f'room_{code}',
            {
                'type': 'send_message',
                'data': {
                    'type': 'next_phase',
                    'phase': phase
                }
            }
        )
        game.game_phase = phase
        game.save()
        phaseCountdown.delay(code)
        
        
    elif phase == 9:
        # go back to phase 2 to continue the game
        if game.winners is None:
            phase = 2
            
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'next_phase',
                        'phase': phase
                    }
                }
            )
            game.game_phase = 2
            game.save()
            phaseCountdown.delay(code)
        else:
            data = {
                'type': 'announce_winners',
                'winners': str(game.winners)
            }
            
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': data
                }
            )
            
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'next_phase',
                        'phase': phase
                    }
                }
            )
            game.game_phase = phase
            game.has_ended = True
            #game.completed = date.now
            game.save()
            
            return True
        
        # not calling phase countdown since the game is already finished
    
    # applies to phase 2, 4, and 6 that doesn't require any data
    else:
        async_to_sync(channel_layer.group_send)(
            f'room_{code}',
            {
                'type': 'send_message',
                'data': {
                    'type': 'next_phase',
                    'phase': phase
                }
            }
        )
        
        game.game_phase = phase
        game.save()
        phaseCountdown.delay(code)
        
@shared_task
def delete_inactive_players():
    players  = Player.objects.filter(Q(in_game=False) & Q(in_lobby=False))
    
    for player in players:
        if player.time_since_last_game < (timezone.now() - timedelta(minutes=15)): # if idle time is greater than or equal to 15 mins
            player.delete()
    
    return 'inactive players deleted'

# vote counting function
def most_common(lst):
    
    # returns 2 items stored in a list (it returns the top 2 candidates with highest votes)
    data = Counter(lst).most_common(2)
    
    if len(data) == 0:
        return 'tie'
    
    # if at least 1 vote, continue with vote counting
    elif len(data) >= 1:
        
        first_item = data[0] 
        
        # if more than 2 players are nominated, get the second index of data 
        if len(data) > 1:
            second_item = data[1]
            
            # second index is their count
            if first_item[1] == second_item[1]:
                return 'tie'
            
            elif first_item[1] > second_item[1]:
                return first_item[0] # returns username
            
        else:
            return first_item[0]
        
    else:
        return 'tie'
    

# each night the vote target and the is_protected status 
# of all players that are still alive and not eliminated will be reset
def refreshPlayerState(players):
    
    new_player_list = []
    
    for player in players:
        
        if player.alive == True and player.eliminated_from_game == False:
            if player.is_protected == True:
                player.is_protected = False
                
            player.night_target = None
            player.vote_target = None
            
            player.save()
            new_player_list.append(player)
            
        # this applies to the players who were eliminated from the game to not interfere with the vote count   
        player.vote_target = None
        player.save()
            
    return new_player_list
    
    
    
# couldn't import from views becuase it would be a circular import error
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

