# Generated by Django 5.1.1 on 2024-10-17 05:20

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0023_alter_player_eliminated_on_night_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='player',
            name='night_target',
            field=models.BooleanField(blank=True, default=False, null=True),
        ),
    ]
