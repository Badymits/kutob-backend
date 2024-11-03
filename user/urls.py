from django.urls import path

from . import views

urlpatterns = [
    path('register/', views.createUser, name='create-user'),
    path('delete/<str:username>/', views.deleteUser, name='delete-user'),
    path('update-player/', views.updateUserSettings, name='update-player'),
    path('user-data/', views.returnUserData, name='user-data')
]
