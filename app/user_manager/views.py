import json
import logging

from challenges.models import CTFSettings, Challenge
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from inshack_scoreboard import settings

from user_manager.forms import UserForm, TeamProfileForm, LoginForm
from user_manager.models import Ssh

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
fh = logging.StreamHandler()
fh.setLevel(logging.DEBUG)
logger.addHandler(fh)


def create_or_update_team(request: HttpRequest, team_form: UserForm, team_profile_form: TeamProfileForm, creating: bool) -> HttpResponse:
    if not team_form.is_valid() or not team_profile_form.is_valid():
        messages.add_message(request, messages.ERROR, team_form.non_field_errors())
    else:
        try:
            if creating:
                team = User.objects.create_user(username=team_form.cleaned_data['username'],
                                                email=team_form.cleaned_data['email'],
                                                password=team_form.cleaned_data['password'],
                                                is_active=True)
            else:
                team = team_form.instance
                team.username = team_form.cleaned_data['username']
                new_pass = team_form.cleaned_data.get('password')
                if new_pass:
                    team.set_password(new_pass)
                else:
                    team.password = team_form.initial['password']
                team.email = team_form.cleaned_data['email']
                team.save()
            team_profile = team_profile_form.save(commit=False)
            team_profile.team = team
            team_profile.save()
            if creating:
                messages.add_message(request, messages.SUCCESS, 'Congratulations ! Your team is created.')
                t = authenticate(username=team.username, password=team_form.cleaned_data['password'])
                if t is not None:
                    login(request, t)
                    log_team_ip(request, t)
            else:
                messages.add_message(request, messages.SUCCESS, 'Your team has been updated.')
            return redirect(reverse('team:profile'))
        except Exception:
            logger.exception('Error while creating/updating a team. creating=' + str(creating) + ', req=' + "\n".join(request.readlines()))
            request.session['messages'] = ['Sorry, an error occurred, please alert an admin.']
    return None


@require_http_methods(["POST"])
@never_cache
@csrf_exempt
def logout_user(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        logout(request)
        messages.add_message(request, messages.INFO, "You've been logged out. Have a nice day.")
    else:
        messages.add_message(request, messages.ERROR, "Mmmh.. You have to be logged in to do this.")
    return redirect(reverse('team:login'))


@sensitive_post_parameters()
@csrf_protect
@never_cache
@require_http_methods(["GET", "POST"])
def register(request: HttpRequest) -> HttpResponse:
    if settings.REGISTER_ENABLED:
        if request.method == "POST":
            team_profile_form = TeamProfileForm(request.POST, request.FILES)
            team_form = UserForm(request.POST)
            response = create_or_update_team(request, team_form, team_profile_form, True)
            if response is not None:
                return response
        else:
            team_profile_form = TeamProfileForm()
            team_form = UserForm()
    else:
        messages.add_message(request, messages.ERROR, "You cannot register anymore, please contact an admin.")
    return render(request, 'user_manager/register.html', locals())


@staff_member_required
@never_cache
@require_http_methods(["GET"])
def mails(request: HttpRequest) -> HttpResponse:
    users = User.objects.all()
    return render(request, 'user_manager/mails.html', locals())


@sensitive_post_parameters()
@csrf_protect
@never_cache
@require_http_methods(["GET", "POST"])
def login_user(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        login_form = LoginForm(request.POST)
        if login_form.is_valid():
            team_name_or_email = login_form.cleaned_data['username_or_email']
            password = login_form.cleaned_data['password']
            team = authenticate(username=team_name_or_email, password=password)
            if team is None:
                user_by_mail = User.objects.filter(email=team_name_or_email)
                if user_by_mail and user_by_mail[0]:
                    username = user_by_mail[0].username
                    team = authenticate(username=username, password=password)
            if team is None:
                messages.add_message(request, messages.ERROR, 'Wrong team name or password. Please try again.')
            else:
                login(request, team)
                messages.add_message(request, messages.SUCCESS, "You've been successfully logged in.")
                log_team_ip(request, team)
                return redirect(request.GET.get('next', reverse('team:profile')))
    else:
        login_form = LoginForm()
    return render(request, 'user_manager/login.html', locals())


def log_team_ip(request, team):
    try:
        if team.teamprofile:
            ip = request.META["HTTP_X_FORWARDED_FOR"]
            if ip:
                ips = json.loads(team.teamprofile.ips)
                ips[ip] = True
                team.teamprofile.ips = json.dumps(ips)
                team.teamprofile.save()
    except Exception:
        logger.exception("Error logging user's IP address")


@login_required
@csrf_protect
@never_cache
@require_http_methods(["GET", "POST"])
def profile(request: HttpRequest) -> HttpResponse:
    team = request.user
    if not hasattr(team, 'teamprofile'):
        messages.add_message(request, messages.ERROR, 'We tried really hard to find it but this team does not exists.')
        return redirect(reverse('team:login'))
    team_profile = team.teamprofile

    ctf_settings = CTFSettings.objects.first()
    ctf_has_been_started = ctf_settings.has_been_started or request.user.is_staff
    if ctf_has_been_started:
        validated_challs = team_profile.validated_challenges.all()
        team_score = sum(map(lambda c: c.get_nb_points(), validated_challs))

        challs = Challenge.objects.all()
        points_to_get = sum(map(lambda c: c.get_nb_points(), challs))
        percentage_valitated_challs = 0
        if points_to_get != 0:
            percentage_valitated_challs = int(100 * (team_score / points_to_get))
        # Deactivate feature as it's not used for now
        ssh = Ssh.objects.filter(id_team_profile=team_profile.pk).first()

    if request.method == "POST":
        team_form = UserForm(request.POST, instance=team)
        team_profile_form = TeamProfileForm(request.POST, request.FILES, instance=team_profile)
        response = create_or_update_team(request, team_form, team_profile_form, False)
        if response is not None:
            return response
    else:
        team_form = UserForm(instance=team)
        team_profile_form = TeamProfileForm(instance=team_profile)

    return render(request, 'user_manager/profile.html', locals())


@staff_member_required
@never_cache
@require_http_methods(["GET"])
def mails(request):
    show_only_contactable = request.GET.get("show_only_contactable", "no")
    if show_only_contactable == "no":
        users = User.objects.all()
    else:
        users = User.objects.filter(teamprofile__wants_to_be_contacted=True)
    return render(request, 'user_manager/mails.html', locals())


@never_cache
@require_http_methods(["GET"])
def team_infos(request):
    resp = {
        "is_logged_in": request.user.is_authenticated,
        "is_admin": request.user.is_staff,
    }
    if request.user.is_authenticated:
        resp["nb_unread_messages"] = request.user.teamprofile.nb_unread_news
        resp["pk"] = request.user.pk
    return JsonResponse(resp)
