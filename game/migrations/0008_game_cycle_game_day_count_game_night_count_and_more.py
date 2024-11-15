# Generated by Django 5.1.1 on 2024-10-09 04:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0007_player_skip_turn'),
    ]

    operations = [
        migrations.AddField(
            model_name='game',
            name='cycle',
            field=models.IntegerField(blank=True, default=1, null=True),
        ),
        migrations.AddField(
            model_name='game',
            name='day_count',
            field=models.IntegerField(blank=True, default=1, null=True),
        ),
        migrations.AddField(
            model_name='game',
            name='night_count',
            field=models.IntegerField(blank=True, default=1, null=True),
        ),
        migrations.AddField(
            model_name='player',
            name='eliminated_on_night',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='player',
            name='revived_on_night',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
