from django.db import models


class Game(models.Model):
    # MINIMUM_PLAYERS = 5
    # MAXIMUM_PLAYERS = 10
    ROOM_STATE = [('LOBBY', 'lobby'), ('IN GAME', 'IN GAME')]
    
    owner                   = models.ForeignKey('game.Player', on_delete=models.CASCADE, related_name='owner')
    players                 = models.ManyToManyField('game.Player', related_name='players')
    room_limit              = models.CharField(max_length=55, default=5)
    aswang_limit            = models.CharField(max_length=10,default=1)
    room_code               = models.CharField(unique=True, max_length=8)
    room_state              = models.CharField(choices=ROOM_STATE, null=True, max_length=255, default=ROOM_STATE[0])
    winners                 = models.CharField(max_length=255,null=True, blank=True)
    has_started             = models.BooleanField(default=False, null=False)
    has_ended               = models.BooleanField(default=False, null=False)
    
    # game states
    # must parse to int before saving to DB
    day_count               = models.IntegerField(default=0, null=True, blank=True)
    night_count             = models.IntegerField(default=0, null=True, blank=True)
    cycle                   = models.IntegerField(default=1, null=True, blank=True)
    game_phase              = models.IntegerField(default=1, null=True, blank=True)
    
    # dates
    completed               = models.DateField(null=True, blank=True)
    date_created            = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f'room {self.room_code}'
    
    @staticmethod
    def get_past_games(self):
        pass
    

class Player(models.Model):
    
    username                 = models.CharField(max_length=255, null=True, blank=True)
    alive                    = models.BooleanField(default=True)
    game                     = models.ManyToManyField(Game, related_name='games', blank=True) # switch to many to many field
    role                     = models.CharField(max_length=255, null=True, blank=True)
    in_game                  = models.CharField(max_length=255, null=True, blank=True)
    
    # fields related to mangangaso
    is_protected             = models.BooleanField(default=False, null=True, blank=True)
    skip_turn                = models.BooleanField(default=False, null=True, blank=True)
    night_skip               = models.IntegerField(default=0, null=True, blank=True) # instances where the manananggal renders mangangaso ineffective
    execute                  = models.CharField(max_length=255, null=True, blank=True) # 
    
    # for aswang roles
    night_target             = models.ForeignKey('self', null=True, blank=True, related_name='target_of_the_night' ,on_delete=models.SET_NULL)
    
    # to track player status for announcements
    eliminated_on_night      = models.IntegerField(default=0, null=True, blank=True)
    revived_on_night         = models.IntegerField(default=0, null=True, blank=True)
    
    # voting related fields
    vote_target              = models.ForeignKey('self', null=True, blank=True, related_name='voted_player', on_delete=models.SET_NULL) 
    eliminated_from_game     = models.BooleanField(default=False, null=True, blank=True)
    
    
    def cast_vote(self):
        # if self.target:
            
        #     selected_target = False
        pass
    
    def __str__(self):
        return self.username
    
    
