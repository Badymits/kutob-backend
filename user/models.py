from django.db import models

# Create your models here.

class User(models.Model):
    
    username = models.CharField(max_length=255, unique=True)
    password = models.CharField(default='', max_length=255, blank=True, null=True)
    
    def __str__(self):
        return self.username
