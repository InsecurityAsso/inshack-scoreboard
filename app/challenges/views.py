import json
from _sha256 import sha256
from datetime import datetime

import logging
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.utils import timezone

from challenges.decorators import staff_member_required_basicauth
from challenges.models import Challenge, CTFSettings, TeamFlagChall
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.defaultfilters import slugify
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from news.forms import NewsForm
from news.models import News
from user_manager.models import TeamProfile

from challenges.forms import ChallengeForm

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
fh = logging.StreamHandler()
fh.setLevel(logging.DEBUG)
logger.addHandler(fh)


def _get_slug(name):
    chall_slug = slugify(name)
    nb_same_slug = Challenge.all_objects.filter(slug=chall_slug).count()
    if nb_same_slug != 0:
        chall_slug += '-' + str(nb_same_slug)
    return chall_slug


def create_or_update_challenge(request, chall_form, creating):
    if chall_form.is_valid():
        chall = chall_form.save(commit=False)
        if creating:
            chall.slug = _get_slug(chall.name)
            messages.add_message(request, messages.SUCCESS, "Challenge created. Thanks for your contribution.")
        else:
            messages.add_message(request, messages.SUCCESS, "Challenge updated. Thanks for your contribution.")
        chall.flag = sha256(chall.flag.encode('utf-8')).hexdigest()
        chall.save()
        return redirect(reverse('challenges:admin'))
    return None


@staff_member_required
@csrf_protect
@require_http_methods(["GET", "POST"])
@never_cache
def add_challenge(request: HttpRequest) -> HttpResponse:
    creating = True
    if request.method == 'POST':
        challenge_form = ChallengeForm(request.POST, request.FILES)
        response = create_or_update_challenge(request, challenge_form, creating)
        if response is not None:
            return response
    else:
        challenge_form = ChallengeForm()
    return render(request, 'challenges/add.html', locals())


@require_http_methods(["GET"])
def list_challenges(request: HttpRequest) -> HttpResponse:
    ctf_settings = CTFSettings.objects.first()
    challenges = []
    if ctf_settings.has_been_started:
        challenges = Challenge.objects.all().order_by('difficulty')
        for c in challenges:
            c.nb_of_validations = len(c.flaggers.filter(team__is_staff=False))
            c.nb_points = c.get_nb_points()
    categories = Challenge.CATEGORY_CHOICES

    challenges_states = ctf_settings.challenges_states
    logger.info(challenges_states)

    return render(request, 'challenges/list.html', locals())


@never_cache
@require_http_methods(["GET"])
def get_validated_challenges(request):
    challs_validated = []
    if request.user.is_authenticated:
        challs_validated = [c.id for c in request.user.teamprofile.validated_challenges.all()]
    return JsonResponse({"challs_validated": challs_validated})


@csrf_exempt
@never_cache
@require_http_methods(["POST"])
def validate(request: HttpRequest, chall_id: int) -> JsonResponse:
    team = request.user
    if not team.is_authenticated:
        return JsonResponse({"message": "You should login to validate your challenges", "error": True})
    team_profile = team.teamprofile
    error = True
    message = "An error occurred while validating your flag. Please be sure to fill all the fields."
    ctf_settings = CTFSettings.objects.first()
    if not ctf_settings.has_been_started and not request.user.is_staff:
        message = "You can't validate a challenge now, the CTF is not running. Please contact us for any question!"
    else:
        if team.is_staff:
            challenge = get_object_or_404(Challenge.all_objects, id=chall_id)
        else:
            challenge = get_object_or_404(Challenge.objects, id=chall_id)
        flag = request.POST.get("flag")
        if flag:
            flag_sha256 = sha256(flag.encode('utf-8')).hexdigest()
            if flag_sha256 == challenge.flag:
                if TeamFlagChall.objects.filter(flagger=team_profile, chall=challenge).count() > 0:
                    message = "This is indeed the correct flag. But your team already flagged this challenge."
                else:
                    new_team_flagger = TeamFlagChall(flagger=team_profile, chall=challenge)
                    team_profile.date_last_validation = datetime.now()
                    try:
                        new_team_flagger.save()  # fail if not unique together
                        team_profile.save()
                        message = "That's correct, congratulations !"
                        error = False
                    except Exception:
                        logger.exception("An error occurred while trying to flag a chall: ")
            else:
                with open("/srv/web/flags", "a") as f:
                    f.write("Team '" + team.username + "' tried : '" + flag + "'\n")
                message = "Sorry it's not the correct flag. Try harder."
    return JsonResponse({"message": message, "error": error})


@staff_member_required()
@csrf_protect
@never_cache
@require_http_methods(["POST", "GET"])
def update_challenge(request: HttpRequest, slug: str) -> HttpResponse:
    challenge = get_object_or_404(Challenge.all_objects, slug=slug)
    creating = False
    if request.method == 'POST':
        challenge_form = ChallengeForm(request.POST, request.FILES, instance=challenge)
        response = create_or_update_challenge(request, challenge_form, creating)
        if response is not None:
            return response
    else:
        challenge.flag = ''
        challenge_form = ChallengeForm(instance=challenge)
    return render(request, 'challenges/add.html', locals())


@staff_member_required
@csrf_protect
@never_cache
@require_http_methods(["POST"])
def delete_challenge(request, slug):
    if request.method == "POST":
        challenge = get_object_or_404(Challenge.all_objects, slug=slug)
        challenge.delete()
        messages.add_message(request, messages.SUCCESS, "The challenge has been deleted.")
    return redirect(reverse('challenges:admin'))


def get_all_teams(ctf_settings: CTFSettings) -> [User]:
    if ctf_settings.should_use_saved_global_scoreboard:
        global_scoreboard_saved, _ = json.loads(ctf_settings.global_scoreboard_saved)
        return [u for u in User.objects.filter(pk__in=list(global_scoreboard_saved))]
    else:
        return [u for u in User.objects.filter(is_active=True, is_staff=False, teamprofile__isnull=False)]


def get_local_teams(ctf_settings: CTFSettings, all_teams: [User]) -> [User]:
    if ctf_settings.should_use_saved_local_scoreboard:
        local_scoreboard_saved, _ = json.loads(ctf_settings.local_scoreboard_saved)
        return [u for u in User.objects.filter(pk__in=list(local_scoreboard_saved))]
    else:
        return list(filter(lambda t: t.teamprofile.on_site, all_teams))


def get_global_validated_challs(ctf_settings: CTFSettings, team: User) -> ([Challenge], int, {int: int}):
    if ctf_settings.should_use_saved_global_scoreboard:
        global_scoreboard_saved, _ = json.loads(ctf_settings.global_scoreboard_saved)
        pk_validated_challs, bugbounty_points = global_scoreboard_saved.get(str(team.pk), ([], 0))
        return Challenge.objects.filter(pk__in=pk_validated_challs), bugbounty_points
    else:
        return team.teamprofile.validated_challenges.all(), team.teamprofile.bug_bounty_points


def get_onsite_validated_challs(ctf_settings: CTFSettings, team: User) -> ([Challenge], int):
    if ctf_settings.should_use_saved_local_scoreboard:
        local_scoreboard_saved, _ = json.loads(ctf_settings.local_scoreboard_saved)
        pk_validated_challs, bugbounty_points = local_scoreboard_saved.get(str(team.pk), ([], 0))
        return Challenge.objects.filter(pk__in=pk_validated_challs), bugbounty_points
    else:
        return team.teamprofile.validated_challenges.all(), team.teamprofile.bug_bounty_points


def compute_live_challenge_pk_to_points() -> {int: int}:
    challenge_pk_to_points = {}
    challs = Challenge.objects.all()
    for c in challs:
        c.nb_of_validations = len(c.flaggers.filter(team__is_staff=False))
        challenge_pk_to_points[c.pk] = c.get_nb_points()
    return challenge_pk_to_points


def get_global_challenge_pk_to_points(ctf_settings: CTFSettings) -> {int: int}:
    if ctf_settings.should_use_saved_global_scoreboard:
        _, challenge_pk_to_points = json.loads(ctf_settings.global_scoreboard_saved)
        return challenge_pk_to_points
    else:
        return compute_live_challenge_pk_to_points()


def get_local_challenge_pk_to_points(ctf_settings: CTFSettings) -> {int: int}:
    if ctf_settings.should_use_saved_local_scoreboard:
        _, challenge_pk_to_points = json.loads(ctf_settings.local_scoreboard_saved)
        return challenge_pk_to_points
    else:
        return compute_live_challenge_pk_to_points()


def get_scoreboards(challenges):
    ctf_settings = CTFSettings.objects.first()
    all_teams = get_all_teams(ctf_settings)
    teams_onsite = get_local_teams(ctf_settings, all_teams)
    global_challenge_pk_to_points = get_global_challenge_pk_to_points(ctf_settings)
    local_challenge_pk_to_points = get_local_challenge_pk_to_points(ctf_settings)
    for t in all_teams:
        validated_challs, bugbounty_points = get_global_validated_challs(ctf_settings, t)
        t.teamprofile.saved_bugbounty_points = bugbounty_points
        t.teamprofile.score = sum(map(lambda c: global_challenge_pk_to_points.get(c.pk, global_challenge_pk_to_points.get(str(c.pk), 0)), validated_challs)) + bugbounty_points
        t.teamprofile.challenges_state = [(c in validated_challs) for c in challenges]
    for t in teams_onsite:
        validated_challs, bugbounty_points = get_onsite_validated_challs(ctf_settings, t)
        t.teamprofile.saved_bugbounty_points = bugbounty_points
        t.teamprofile.score = sum(map(lambda c: local_challenge_pk_to_points.get(c.pk, local_challenge_pk_to_points.get(str(c.pk), 0)), validated_challs)) + bugbounty_points
        t.teamprofile.challenges_state = [(c in validated_challs) for c in challenges]

    all_teams = sorted(all_teams, key=lambda t: (-t.teamprofile.score, t.teamprofile.date_last_validation))
    teams_onsite = sorted(teams_onsite, key=lambda t: (-t.teamprofile.score, t.teamprofile.date_last_validation))
    return all_teams, teams_onsite


@require_http_methods(["GET"])
def scoreboard(request):
    ctf_settings = CTFSettings.objects.first()
    challenges = []
    ctf_has_been_started = ctf_settings.has_been_started
    if ctf_has_been_started:
        challenges = Challenge.objects.all().order_by('difficulty', 'category')
    all_teams, teams_onsite = get_scoreboards(challenges)
    return render(request, 'challenges/scoreboard.html', locals())


@staff_member_required
@require_http_methods(["GET"])
def admin(request):
    ctf_settings = CTFSettings.objects.first()
    ctf_state = ctf_settings.get_state_display()
    ctf_has_been_started = ctf_settings.has_been_started or request.user.is_staff

    challenges = Challenge.all_objects.all().order_by('difficulty')
    for c in challenges:
        c.nb_of_validations = len(c.flaggers.filter(team__is_staff=False))
        c.nb_points = c.get_nb_points()
    categories = Challenge.CATEGORY_CHOICES
    challs_validated = request.user.teamprofile.validated_challenges

    challenges_states = ctf_settings.challenges_states

    news = News.objects.all().order_by("-updated_date")
    if request.user.is_staff:
        news_form = NewsForm()

    return render(request, 'challenges/admin.html', locals())


def change_ctf_state_to(state):
    ctf_settings = CTFSettings.objects.first()
    ctf_settings.state = state
    ctf_settings.save()


def save_scoreboards_state_and_change_ctf_state_to(state, update_local_too=True):
    ctf_settings = CTFSettings.objects.first()
    challenges = Challenge.objects.all().order_by('difficulty', 'category')
    global_scoreboard, local_scoreboard = get_scoreboards(challenges)
    ctf_settings.global_scoreboard_saved = json.dumps([
        {team.pk: ([i.pk for i in team.teamprofile.validated_challenges.all()], team.teamprofile.bug_bounty_points) for
         team in global_scoreboard},
        get_global_challenge_pk_to_points(ctf_settings)
    ])
    if update_local_too:
        ctf_settings.local_scoreboard_saved = json.dumps([
            {team.pk: ([i.pk for i in team.teamprofile.validated_challenges.all()], team.teamprofile.bug_bounty_points)
             for team in local_scoreboard},
            get_local_challenge_pk_to_points(ctf_settings)
        ])
    ctf_settings.state = state
    ctf_settings.save()


def post_news(text):
    news = News(text=text)
    try:
        news.save()
        for t in TeamProfile.objects.all():
            t.nb_unread_news += 1
            t.save()
    except Exception:
        logger.exception("Error adding news: ")


@staff_member_required
@never_cache
@csrf_protect
@require_http_methods(["POST"])
def ctf_not_started(request):
    change_ctf_state_to(CTFSettings.NOT_STARTED)
    messages.add_message(request, messages.SUCCESS, "CTF is not started")
    return redirect(reverse('challenges:admin'))


@staff_member_required
@never_cache
@csrf_protect
@require_http_methods(["POST"])
def start_ctf(request):
    change_ctf_state_to(CTFSettings.GLOBAL_START)
    post_news('The CTF has officially started! Let\'s hack ;). Please see the home page to read the rules and see '
              'when the CTF ends.')
    messages.add_message(request, messages.SUCCESS, "CTF has started!")
    return redirect(reverse('challenges:admin'))


@staff_member_required
@never_cache
@csrf_protect
@require_http_methods(["POST"])
def stop_local_scoreboard(request):
    save_scoreboards_state_and_change_ctf_state_to(CTFSettings.ON_SITE_END)
    post_news('The on-site CTF is now finished! Congratulations to the participants :). Don\'t worry, you can still '
              'play online (cf home page). And we will keep adding new challenges.')
    messages.add_message(request, messages.SUCCESS, "Local competition stopped")
    return redirect(reverse('challenges:admin'))


@staff_member_required
@never_cache
@csrf_protect
@require_http_methods(["POST"])
def end_ctf(request):
    save_scoreboards_state_and_change_ctf_state_to(CTFSettings.ONLINE_END, False)
    post_news('The CTF is now finished! Congratulations to the participants :). Thanks a lot, it was awesome!')
    messages.add_message(request, messages.SUCCESS, "CTF has ended")
    return redirect(reverse('challenges:admin'))


@staff_member_required_basicauth
@csrf_exempt
@never_cache
@require_http_methods(["POST"])
def bulk_update(request: HttpRequest):
    try:
        challenges_data = json.loads(request.body.decode())
        challenges = challenges_data["challenges"]
    except Exception:
        logger.exception("Couldn't load json")
        return JsonResponse({"message": "Couldn't load json data"}, status=400)

    try:
        assert isinstance(challenges, list)
        assert len(challenges) > 0 and isinstance(challenges[0], dict)
    except AssertionError:
        logger.exception("Expected a list of dict, representing the challenges")
        return JsonResponse({"message": "Expected a list of dict, representing the challenges"}, status=400)

    try:
        challenge_slugs = {chal["slug"] for chal in challenges}
        assert len(challenge_slugs) == len(challenges)
    except (KeyError, AssertionError):
        return JsonResponse({"message": "`slug` should be present and unique in all challenges"}, status=400)

    expected_data = """Challenges should be of this form (following documentation may not be up to date): {
              "difficulty": 0-4 (0 easier, 4 harder),
              "name": "bla bla" (len<50),
              "slug": "bla-bla" (extracted from name, identifies the challenge),
              "description": "Fun story in html",
              "category": Any of: "MIC", "WEB", "PPC", "FOR", "REV", "PWN", "CRY", "NET",
              "flag": "INSA{the flag}" (len<=255),
              "static_url": null OR "url of the static files for the chal",
              "company_logo_url": null OR "the URL of the company who wrote the chal, if any",
              "nb_points_override": integer, if greater then -3, it will override the automagic points calculus 
            }"""

    for chal in challenges:
        try:
            difficulty = chal["difficulty"]
            name = chal["name"]
            slug = chal["slug"]
            description = chal["description"]
            category = chal["category"]
            flag = chal["flag"]
            static_url = chal["static_url"]
            company_logo_url = chal["company_logo_url"]
            nb_points_override = chal["nb_points_override"]
        except KeyError:
            logger.exception("Wrong challenge format")
            return JsonResponse({"message": expected_data}, status=400)

        try:
            try:
                chal = Challenge.all_objects.get(slug=slug)
                chal.difficulty = difficulty
                chal.name = name
                chal.description = description
                chal.category = category
                chal.flag = flag
                chal.static_url = static_url
                chal.company_logo_url = company_logo_url
                chal.nb_points_override = nb_points_override
                chal.full_clean()
                chal.save()
            except ObjectDoesNotExist:
                chal = Challenge(difficulty=difficulty, name=name, slug=slug, description=description, category=category, flag=flag,
                                 static_url=static_url, company_logo_url=company_logo_url,
                                 nb_points_override=nb_points_override)
                chal.full_clean()
                chal.save()
        except ValidationError as e:
            logger.exception("Wrong challenge format")
            return JsonResponse(
                    {"message": "Challenge `{}` doesn't have the right form: {}.\n{}".format(name, e, expected_data)},
                    status=400)
        except Exception:
            logger.exception("Exception creating the challenge")
            return JsonResponse(
                    {"message": "Error while updating {}, please check the serverlogs.\nFor reference: {}".format(name, expected_data)},
                    status=500)

    Challenge.all_objects.exclude(slug__in=challenge_slugs).delete()
    return JsonResponse({"message": "OK"}, status=200)


@staff_member_required_basicauth
@csrf_exempt
@never_cache
@require_http_methods(["POST"])
def push_challenges_status(request: HttpRequest):
    # $ curl http://127.0.0.1:8000/challenges/statuses/ -u adminctf -d '{"chal-slug1": true, "chal-slug2": false}'
    try:
        challenge_states = json.loads(request.body.decode())
    except Exception:
        logger.exception("Couldn't load json")
        return JsonResponse({"message": "Couldn't load json data"}, status=400)

    try:
        assert isinstance(challenge_states, dict)
        assert len(challenge_states) > 0
    except AssertionError:
        logger.exception("Expected a dict, {'chal-slug' -> bool (true if up, false if down)}")
        return JsonResponse({"message": "Expected a dict, {'chal-slug' -> bool (true if up, false if down)}"}, status=400)

    ctf_settings = CTFSettings.objects.first()
    ctf_settings.challenges_states_json = json.dumps(challenge_states)
    ctf_settings.challenges_states_updated_at = timezone.now()
    ctf_settings.save()

    return JsonResponse({"message": "OK"}, status=200)
