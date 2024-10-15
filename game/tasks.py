from django.shortcuts import get_object_or_404
from django.db.models import Q

from celery import shared_task
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from time import sleep
from collections import Counter

from .models import Game, Player
from .serializers import PlayersInLobby, PlayerSerializer, WinnersSerializer


channel_layer = get_channel_layer()

@shared_task
def send_role(player,code,role):
    print('aaaa')
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
        
        # increment night and day count on 1st phase
        if int(game.game_phase) == 1:
            countdown = 10
           
        elif int(game.game_phase) == 2:
            game.night_count += 1
            countdown = 5
            game.save()
            game_time = game.night_count
            # send to frontend the day/night count
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
            # send to frontend the day/night count
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
            # start time in frontend
             # 1 minute for players to discuss and decide to vote
            countdown = 60
            
            
        elif int(game.game_phase) == 7:
             # only given 45 secs to cast their vote
            countdown = 45
            
            
            
        else:
            print('no phase')
            countdown = 10
    
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
        
        switchToNextPhase.delay(code)

# changes UI in frontend. Here we sort of "initialize" the phase, what are the things needed in each phase
@shared_task
def switchToNextPhase(code):

    game = Game.objects.get(room_code=code)
    phase = int(game.game_phase) + 1
    
    
        
    # the player select target phase, if mangangaso is not alive, then the aswang will be the first player to select their target
    if phase == 3:
        
        current_players = PlayersInLobby(game.players.filter(Q(alive=True) & Q(eliminated_from_game=False)), many=True).data
        refreshStatePlayers(current_players)
        # send to frontend to update list
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
        
        # this will only show if the aswang type is manananggal
        if mangangaso.skip_turn == True and mangangaso.alive == True and next_role == 'aswang - manananggal':
            data = {
                'type': 'update_roleTurn',
                'role': next_role,
                'message' :'You are rendered ineffective during this night by the aswang, you cannot protect anyone'
            }
            
        
        if mangangaso.alive == False:
            data = {
                'type': 'update_roleTurn',
                'role': next_role,
            }
        else:
            data = {
                'type': 'update_roleTurn',
                'role': 'mangangaso'
            }
        # send to frontend which user will have the first turn, mangangaso (if alive) or aswang (if mangangaso is not alive)
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
        
        # need to save current phase so it won't loop
        game.game_phase = phase
        game.save()
        
        # refresh state at the end of the phase
        if mangangaso.skip_turn == True:
            mangangaso.skip_turn = False
            mangangaso.save()
        
    # day announcement phase
    elif phase == 5:
        # check player count, if there are no more players aside from the aswang, then they win, else, the game continues to dicussion phase
        
        current_players = game.players.filter(Q(alive=True) & Q(eliminated_from_game=False))
        print('current player count: ', current_players.count())
        if int(current_players.count()) == 1 and current_players.filter(
                Q(role='aswang - manduguro') | 
                Q(role='aswang - manananggal') | 
                Q(role='aswang - berbalang')
                ).exists():
            # send to last phase, announcement shit:
            game.winners = 'Mga Aswang'
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'announce_winners',
                        'winners': 'Mga Aswang'
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
            
        
        if eliminated_players > 0:
            
            # get player
            player = game.players.filter(eliminated_on_night=game.night_count).first()
            playerSerialized  = PlayerSerializer(player).data
            if eliminated_players > 1:
                message = f'There were {eliminated_players} vitims during the night'
            else:
                message = f'There was {eliminated_players} victim during the night'
                
            # make announcement to inform users
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
            
        else:
            player = 'none'
            eliminated_players = 0
            message = 'There were no victims during the night'
        
            # make announcement to inform users
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
        # get votes related to game
        players = game.players.filter(alive=True)
        print(players)
        
        vote_list = []
        
        # adding vote list to check most voted player
        for i in players.iterator():
            if i.vote_target is not None: # to ignore players who have not voted during this phase
                vote_list.append(i.vote_target.username)
        
        result = most_common(vote_list)
        print('highest vote is: ', result)

        
        if result != 'tie':
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
                
                game.winners = 'Mga Taumbayan'
                # send to winning phase (which is next phase, phase 9)

            else:
                data = {
                    'type': 'not_aswang',
                    'eliminated': result,
                    'message': 'The player eliminated is NOT the aswang'
                }
                #back to phase 2

        else:
            data = {
                'type': 'vote_tie',
                'message': 'There was a TIE among players, no one will be eliminated'
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
            # initialize data
            data = {
                'type': 'announce_winners',
                'winners': str(game.winners)
            }
            
            # send to frontend the winners of the game
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': data
                }
            )
            
            # next phase
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
        
         # not calling phase countdown since the game is already finished
    
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

#
def most_common(lst):
    
    data = Counter(lst).most_common(2)
    
    first_item = data[0]
    if len(data) > 1:
        second_item = data[1]
    
        # second index is their count
        if first_item[1] == second_item[1]:
            return 'tie'
        elif first_item[1] > second_item[1]:
            return first_item[0] # returns username
    else:
        return first_item[0]
    
    return data.most_common(1)[0][0]


def refreshStatePlayers(players):
    
    for player in players:
        if player.is_protected == True:
            player.is_protected = False
            player.save()
    
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

