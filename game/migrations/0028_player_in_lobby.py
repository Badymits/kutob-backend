# Generated by Django 5.1.1 on 2024-10-19 06:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0027_alter_player_in_game'),
    ]

    operations = [
        migrations.AddField(
            model_name='player',
            name='in_lobby',
            field=models.BooleanField(blank=True, default=False),
        ),
    ]