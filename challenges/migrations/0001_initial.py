# -*- coding: utf-8 -*-
# Generated by Django 1.10.5 on 2017-03-05 18:56
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('user_manager', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Challenge',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nb_points', models.IntegerField(default=50)),
                ('name', models.CharField(max_length=50, unique=True)),
                ('slug', models.SlugField(blank=True, unique=True)),
                ('description', models.TextField()),
                ('category', models.CharField(choices=[('MIC', 'MISC'), ('PPC', 'Programming'), ('WEB', 'Web'), ('FOR', 'Forensics'), ('REV', 'Reverse'), ('PWN', 'Pwn'), ('CRY', 'Crypto')], default='WEB', max_length=3)),
                ('flag', models.CharField(max_length=255)),
                ('is_enabled', models.BooleanField(default=False)),
                ('chall_file', models.URLField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='CTFSettings',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('state', models.CharField(choices=[('NST', 'Not started'), ('STA', 'Globally started'), ('OSH', 'On site scoreboard hidden'), ('OSE', 'On site end'), ('OLH', 'Online scoreboard hidden'), ('OLE', 'Online end')], default='NST', max_length=3)),
                ('local_scoreboard_saved', models.TextField(blank=True, null=True)),
                ('global_scoreboard_saved', models.TextField(blank=True, null=True)),
                ('url_challenges_state', models.URLField()),
            ],
        ),
        migrations.CreateModel(
            name='TeamFlagChall',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_flagged', models.DateTimeField(auto_now_add=True)),
                ('chall', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='challenges.Challenge')),
                ('flagger', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='user_manager.TeamProfile')),
            ],
            options={
                'ordering': ['date_flagged'],
            },
        ),
        migrations.AddField(
            model_name='challenge',
            name='flaggers',
            field=models.ManyToManyField(blank=True, related_name='validated_challenges', through='challenges.TeamFlagChall', to='user_manager.TeamProfile'),
        ),
        migrations.AlterUniqueTogether(
            name='teamflagchall',
            unique_together=set([('flagger', 'chall')]),
        ),
    ]
