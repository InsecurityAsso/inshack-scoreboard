import datetime
import json

from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from user_manager.models import TeamProfile


class CTFSettings(models.Model):
    NOT_STARTED = "NST"
    GLOBAL_START = "STA"
    ON_SITE_END = "OSE"
    ONLINE_END = "OLE"
    STATE_CHOICES = (
        (NOT_STARTED, 'Not started'),
        (GLOBAL_START, 'Globally started'),
        (ON_SITE_END, 'On site end'),
        (ONLINE_END, 'Online end'),
    )

    state = models.CharField(max_length=3,
                             choices=STATE_CHOICES,
                             default=NOT_STARTED)

    local_scoreboard_saved = models.TextField(blank=True, null=True)
    global_scoreboard_saved = models.TextField(blank=True, null=True)
    challenges_states_json = models.TextField(blank=True, null=True, default="{}")
    challenges_states_updated_at = models.DateTimeField(default=timezone.now)

    @property
    def has_been_started(self):
        return self.state != self.NOT_STARTED

    @property
    def should_use_saved_local_scoreboard(self):
        return self.state in {self.ON_SITE_END, self.ONLINE_END}

    @property
    def should_use_saved_global_scoreboard(self):
        return self.state == self.ONLINE_END

    @property
    def challenges_states(self):
        try:
            challenges_states = json.loads(self.challenges_states_json)
            if timezone.now() - self.challenges_states_updated_at < datetime.timedelta(minutes=15):
                return challenges_states
        except Exception:
            pass

        return {}


class ChallengeManagerNoDisabled(models.Manager):
    def get_queryset(self):
        return super(ChallengeManagerNoDisabled, self).get_queryset().exclude(is_enabled=False)


class Challenge(models.Model):
    MISC = 'MIC'
    WEB = 'WEB'
    PPC = 'PPC'
    FORENSICS = 'FOR'
    REVERSE = 'REV'
    PWN = 'PWN'
    CRYPTO = 'CRY'
    NETWORK = 'NET'
    CATEGORY_CHOICES = (
        (MISC, 'MISC'),
        (PPC, 'Programming'),
        (WEB, 'Web'),
        (FORENSICS, 'Forensics'),
        (REVERSE, 'Reverse'),
        (PWN, 'Pwn'),
        (CRYPTO, 'Crypto'),
        (NETWORK, 'Network'),
    )

    TRIV = 0
    EASY = 1
    MEDIUM = 2
    HARD = 3
    HARDCORE = 4
    DIFFICULTY_CHOICES = (
        (TRIV, 'Trivial'),
        (EASY, 'Easy'),
        (MEDIUM, 'Medium'),
        (HARD, 'Hard'),
        (HARDCORE, 'Genius Level'),
    )

    # Indicative challenge's difficulty
    difficulty = models.IntegerField(choices=DIFFICULTY_CHOICES,
                                     default=MEDIUM)
    # name of the chall
    name = models.CharField(max_length=50, unique=True)
    # slug of the chall, generated from the name (unique for URL)
    slug = models.SlugField(max_length=50, blank=True, unique=True)
    # chall's description, a fun story
    description = models.TextField()
    # chall's category
    category = models.CharField(max_length=3,
                                choices=CATEGORY_CHOICES,
                                default=WEB)
    # teams having solved the challenge (by date of solving)
    flaggers = models.ManyToManyField(TeamProfile, through='TeamFlagChall', blank=True,
                                      related_name='validated_challenges')
    # chall's flag
    flag = models.CharField(max_length=255, validators=[
        RegexValidator(
            regex=r'^INSA{.*}$',
            message='Flag should be in the form ^INSA{.*}$',
        ),
    ])
    # is chall visible by everyone ?
    is_enabled = models.BooleanField(default=False)
    # file (or archive) of the chall
    static_url = models.URLField(blank=True, null=True)
    # is the chall written by a company?
    company_logo_url = models.URLField(blank=True, null=True)
    # if > -3, will override the automagic points calculus
    nb_points_override = models.IntegerField(blank=False, null=False, default=-10)

    # managers
    # except is_enabled=False
    objects = ChallengeManagerNoDisabled()
    # all challs
    all_objects = models.Manager()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.nb_of_validations = 0  # updated dynamically

    def __str__(self):
        return self.name

    def get_nb_points(self):
        if self.nb_points_override >= -2:
            return self.nb_points_override

        nb_other_validations = self.nb_of_validations - 1
        nb_validations_to_points = [
            (0, 500),
            (5, 400),
            (10, 330),
            (20, 230),
            (30, 150),
            (40, 90),
            (50, 50),
        ]
        if nb_other_validations <= 0:
            return nb_validations_to_points[0][1]
        if nb_other_validations >= nb_validations_to_points[-1][0]:
            return nb_validations_to_points[-1][1]
        for i in range(len(nb_validations_to_points) - 1):
            nb_valid_cur, nb_points_cur = nb_validations_to_points[i]
            nb_valid_next, nb_points_next = nb_validations_to_points[i + 1]
            if nb_valid_cur <= nb_other_validations < nb_valid_next:
                points = nb_points_next + (nb_points_cur - nb_points_next)*(1 - (nb_other_validations - nb_valid_cur)/(nb_valid_next - nb_valid_cur))
                return int(points)


class TeamFlagChall(models.Model):
    flagger = models.ForeignKey(TeamProfile, on_delete=models.CASCADE)
    chall = models.ForeignKey(Challenge, on_delete=models.CASCADE)
    date_flagged = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_flagged"]
        unique_together = (("flagger", "chall"),)

    def __str__(self):
        return str(self.flagger) + " flagged " + str(self.chall)


class TeamTriedChall(models.Model):
    flagger = models.ForeignKey(TeamProfile, on_delete=models.CASCADE)
    chall = models.ForeignKey(Challenge, on_delete=models.CASCADE)
    flag_fail = models.TextField(max_length=255)

    def __str__(self):
        return str(self.flagger) + " tried " + str(self.chall) + " with " + self.flag_fail
