from django.urls import path

from . import views

urlpatterns = [
    path('create-room/', views.createRoom, name='create-room'),
    path('join-room/', views.joinRoom, name='join-room'),
    path('leave-room/', views.leaveRoom, name='leave-room'),
    path('update-room/', views.updateRoomSettings, name='update-room'),
    path('start/', views.startGameSession, name='start'),
    path('select-target/', views.selectTarget, name='select-target'),
    path('vote-player/', views.votePlayer, name='vote-player'),
]


