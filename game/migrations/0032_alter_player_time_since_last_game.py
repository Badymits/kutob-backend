# Generated by Django 5.1.1 on 2024-10-21 07:07

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0031_alter_player_time_since_last_game'),
    ]

    operations = [
        migrations.AlterField(
            model_name='player',
            name='time_since_last_game',
            field=models.DateTimeField(blank=True, default=datetime.datetime(2024, 10, 21, 15, 7, 46, 391537), null=True),
        ),
    ]