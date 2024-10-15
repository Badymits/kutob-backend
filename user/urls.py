from django.urls import path

from . import views

urlpatterns = [
    path('register/', views.createUser, name='create-user'),
    path('delete/<str:username>/', views.deleteUser, name='delete-user'),
]
