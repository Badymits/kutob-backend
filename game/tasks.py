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

import redis

redis_client = redis.StrictRedis(host='localhost', port=6379, db=1)


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

@shared_task
def checkDisconnectedRole(user, code):
    
    try:
        player = get_object_or_404(Player, username=user)
        game = get_object_or_404(Game, room_code=code)
    except Exception as e:
        
        print(f'Error: {e}')
        return None
    
    if game.game_phase == 3:
        
        if player.role == 'mangangaso':
            next_role = searchAswangRole(game=game) # returns obj
            
            aswang_players = PlayersInLobby(game.players.filter(
                Q(role__startswith='aswang') & Q(alive=True) & Q(eliminated_from_game=False)
            ), many=True).data
            
            async_to_sync(channel_layer.group_send)(
                f'{next_role.username}_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'player_select_target',
                        'player': next_role.username,
                        'aswang_players': aswang_players
                    }
                }
            )
            
        elif player.role == 'aswang - mandurugo':
            aswang_role = searchAswangRole(game=game)
            aswang_players = getAswangPlayers(game=game, player=player)
            
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
                #return True
        else:
            return None # ?? tama ba toh ??  
    

@shared_task
def countdown_timer(code, duration):
    
    #redis_timer = redis_client.get(f'game_{code}_timer')
    
    redis_key = f'game_{code}_timer'
    
    # Store the countdown value in Redis
    redis_client.set(redis_key, duration)
    
    # Send update to the channel layer
    async_to_sync(channel_layer.group_send)(f'room_{code}', {
        'type': 'send_message',
        'data': {
            'type': 'countdown',
            'countdown': duration
        }
    })
    
    # Check if there is more time left
    if duration > 1:
        # Schedule the next update after 1 second
        countdown_timer.apply_async(args=[code, duration - 1], countdown=1)
    else:
        # Call the next phase or action
        phaseInitialize.apply_async(args=[code], countdown=1)
        
    
# alternative solution instead of it being handled by the frontend, this ensures synchronicity of all clients related to the game
@shared_task
def phaseCountdown(code): 
    print('sending')
    try:
        game = get_object_or_404(Game, room_code=code)
    except Exception as e:
        print(f'Error: {e}')
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
            game.cycle += 1
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

        countdown_timer.apply_async(args=[code, countdown]) 
        
    else:
        return None

# changes UI in frontend. Here we sort of "initialize" the phase, what are the things needed in each phase that is then reflected in the frontend
@shared_task
def phaseInitialize(code):

    game = Game.objects.get(room_code=code)
    phase = int(game.game_phase) + 1

        
    # the player select target phase, if mangangaso is not alive, then the aswang will be the first player to select their target
    if phase == 3:
        
        player_list = game.players.filter(Q(alive=True) & Q(eliminated_from_game=False))
    
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
        next_role = searchAswangRole(game) # returns obj
        
        
        aswang_players = PlayersInLobby(game.players.filter(
            Q(role__startswith='aswang') & Q(alive=True) & Q(eliminated_from_game=False)
        ), many=True).data
        
        
        
        # mangangaso can protect if it has the same night count (since they will be rendered ineffective for a turn by the manananggal)
        if mangangaso.night_skip == game.night_count:
            mangangaso.skip_turn = False
            mangangaso.save()
            
        
        
        # every cycle divisible by 5 (except 1st cycle which is 0), mangangaso can execute a player
        if game.cycle % 5 == 0 and game.cycle != 0:
            mangangaso.can_execute = True
            mangangaso.save()
        
        
        
        # this will only show if the game has aswang type is manananggal
        if mangangaso.skip_turn == True and mangangaso.alive == True and mangangaso.eliminated_from_game == False and int(mangangaso.night_skip) != (game.night_count):
            
            data = {
                'type': 'update_roleTurn',
                'role': next_role.role,
                'mangangaso_message_skip' : 'You are rendered ineffective during this night by the aswang, you cannot eliminate anyone' if mangangaso.can_execute else 'You are rendered ineffective during this night by the aswang, you cannot protect anyone' 
            }
            
            async_to_sync(channel_layer.group_send)(
                f'{next_role.username}_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'player_select_target',
                        'player': next_role.username,
                        'aswang_players': aswang_players
                    }
                }
            )
            
            
        
        elif mangangaso.alive == False or mangangaso.eliminated_from_game == True:
            
            data = {
                'type': 'update_roleTurn',
                'role': next_role.role,
            }
            
            async_to_sync(channel_layer.group_send)(
                f'{next_role.username}_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'player_select_target',
                        'player': next_role.username,
                        'aswang_players': aswang_players
                    }
                }
            )
        else:
            data = {
                    'type': 'update_roleTurn',
                    'role': 'mangangaso',
                    'mangangaso_message': "Choose who you'll EXECUTE" if mangangaso.can_execute else "Choose who you'll PROTECT"
                }

        async_to_sync(channel_layer.group_send)(
            f'room_{code}',
            {
                'type': 'send_message',
                'data': data
            }
        )
        
        async_to_sync(channel_layer.group_send)(
            f'{mangangaso.username}_{code}',
            {
                'type': 'send_message',
                'data': {
                    'type': 'player_select_target',
                    'player': mangangaso.username,
                }
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
        
        aswang_player_count = game.players.filter(Q(role__startswith='aswang') & Q(alive=True) & Q(eliminated_from_game=False)).count()
        
        # when aswang/s eliminate the last non aswang player during the night
        if aswang_player_count != 0 and current_players.filter(~Q(role__startswith='aswang')).count() == 0:
            game.winners = 'Mga Aswang'
            
            phase = 8
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'announce_winners',
                        'winners': 'Mga Aswang',
                        'message': 'There are no more players left aside from the aswang. Aswang wins!'
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
            phaseCountdown.apply_async(args=[code])
            
        # situations where the aswang is killed my the mangangaso
        elif aswang_player_count == 0  and current_players.filter(~Q(role__startswith='aswang')).count() >= 1:
            game.winners = 'Mga Taumbayan'
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'announce_winners',
                        'winners': 'Mga Taumbayan',
                        'message': 'The aswang were eliminated by the mangangaso. Taumbayan wins!'
                    }
                }
            )
            phase = 8
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
            phaseCountdown.apply_async(args=[code])
        
        # rare cases where aswang and mangangaso eliminate each other during the night
        elif aswang_player_count == 0  and current_players.filter(~Q(role__startswith='aswang')).count() == 0:
            game.winners = 'TIE'
            async_to_sync(channel_layer.group_send)(
                f'room_{code}',
                {
                    'type': 'send_message',
                    'data': {
                        'type': 'announce_winners',
                        'winners': 'TIE',
                        'message': 'There are no more players left in the game. the result is a TIE'
                    }
                }
            )
            phase = 8
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
            phaseCountdown.apply_async(args=[code])
            
        else:   
            try:
                eliminated_players = game.players.filter(eliminated_on_night=game.night_count).count()
                revived_players = game.players.filter(revived_on_night=game.night_count).count()
            except:
                pass
                            
            if eliminated_players > 0 and revived_players == 0:
                
                players = game.players.filter(eliminated_on_night=game.night_count)
                playersSerialized  = PlayersInLobby(players, many=True).data
                
                if eliminated_players > 1:
                    message = f'There were {eliminated_players} victims during the night'
                else:
                    message = f'There was {eliminated_players} victim during the night'
                    
                async_to_sync(channel_layer.group_send)(
                    f'room_{code}',
                    {
                        'type': 'send_message',
                        'data': {
                            'type': 'announce',
                            'player_count': eliminated_players,
                            'players': playersSerialized,
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
            
            aswang_player_count = game.players.filter(
                Q(role__startswith='aswang') & Q(eliminated_from_game=False) & Q(alive=True)
            ).count()
            
            # if aswang players are the only players left in the game, send to last phase
            if aswang_player_count != 0 and current_players.filter(~Q(role__startswith='aswang')).count() == 0:
                
                game.winners = 'Mga Aswang'
                
                data = {
                    'type': 'announce_winners',
                    'winners': 'Mga Aswang',
                    'message': 'There are no more players left aside from the aswang. Aswang wins!'
                }
                
                phase = 8
                
            else:
                
                
                if player_eliminated.role == 'aswang - mandurugo' or player_eliminated.role == 'aswang - manananggal' or player_eliminated.role == 'aswang - berbalang':
                
                    if aswang_player_count >=1:
                        message = f"The player eliminated IS the aswang. there's {aswang_player_count} remaining. the game continues..."
                        
                    else:
                        message = f"The player eliminated IS the aswang. there's {aswang_player_count} remaining. taumbayan wins!"
                        game.winners = 'Mga Taumbayan' # send to winning phase (which is next phase, phase 9)
                        
                    data = {
                        'type': 'is_aswang',
                        'eliminated': result,
                        'message': message
                    }

                else: 
                    data = {
                        'type': 'not_aswang',
                        'eliminated': result,
                        'message': 'The player eliminated is NOT the aswang. the game continues...' # back to phase 2
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
            game.game_phase = phase
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
        if phase == 4 and (game.day_count % 4 == 0 and game.cycle != 0):
            mangangaso = game.players.filter(Q(role='mangangaso') & Q(alive=True) & Q(eliminated_from_game=False)).first()
            if mangangaso:
                async_to_sync(channel_layer.group_send)(
                    f'{mangangaso.username}_{code}',
                    {
                        'type': 'send_message',
                        'data':{
                            'type': 'mangangaso_skill_change',
                            'message': 'For the next night, you can eliminate a player'
                        }
                    }
                )
        if phase == 6:
            current_players = PlayersInLobby(game.players.filter(Q(alive=True) & Q(eliminated_from_game=False)), many=True).data
        
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
    
    """returns 2 items stored in a list 
    (it returns the top 2 candidates with highest votes)
    
    if at least 1 vote, continue with vote counting
    if more than 2 players are nominated, get the second index of data 
    
    this function returns either 'tie' or the username of the player
    
    """
    
    data = Counter(lst).most_common(2)
    
    if len(data) == 0:
        return 'tie'
    

    elif len(data) >= 1:
        
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
            player.turn_done = False
            if player.can_execute:
                player.can_execute = False
            
            player.save()
            new_player_list.append(player)
            
        # this applies to the players who were eliminated from the game to not interfere with the vote count   
        player.vote_target = None
        player.save()
            
    return new_player_list
    
    
    
# couldn't import from views becuase it would be a circular import error
def searchAswangRole(game):
    
    aswang_player = game.players.filter(Q(role__startswith='aswang') & Q(turn_done=False) & Q(eliminated_from_game=False) & Q(alive=True)).first()
    
    if not aswang_player:
        return None
    else:
        return aswang_player


def getAswangPlayers(game):
    
    aswang_players = PlayersInLobby(game.players.filter(
        Q(role__startswith='aswang') & Q(alive=True) & Q(eliminated_from_game=False) 
    ), many=True).data
    
    if not aswang_players:
        return None
    
    return aswang_players

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
