from django.contrib.auth import authenticate, logout, login, get_user
from django.utils.datastructures import MultiValueDictKeyError
from django.shortcuts import render, HttpResponse, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.storage import FileSystemStorage
from django.core.mail import send_mail
from django.utils import timezone
from django.db.models import Q
from vizitcard.settings import EMAIL_HOST_USER, BASE_DIR
from app.models import *
from datetime import datetime, timedelta
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.core.files import File
from rest_framework import permissions, status
from scripts.validators import *
from random import randint
import mimetypes
import json


def index(request):
    return render(request, 'index.html', {'user': request.user, 'cards': Card.objects.filter(creator=request.user) if not request.user.is_anonymous else []})


@api_view(['POST'])
def register(request):
    username = request.POST['username']
    password = request.POST['password']
    confirm_password = request.POST['confirm_password']
    email = request.POST['email']
    errors = {'username': validate_username(username, True) or [],
              'password': validate_password(password, True) or [],
              'email': [],
              'confirm': []}
    if User.objects.filter(email=email).count():
        errors['email'].append('Почта занята')
    if password != confirm_password:
        errors['confirm'].append('Пароли не совпадают')

    for i in errors.items():
        if len(i[1]):
            return Response(errors, status=400)

    user = User.objects.create_user(username=username, email=email, password=password)
    user.is_active = False
    user.save()
    print('saved')

    token = Token.objects.create(user=user, token_type="activation")
    text = f'Hey, this is vizitcard bot! Go to this <a href="http://127.0.0.1:8000/activate/{token.token}"> link </a> to activate your account'
    send_mail('vizitcard', '', None, [email], html_message=text)
    token.save()

    return Response(b'', status=200)


def activate_user(request, token):
    try:
        token_obj = Token.objects.get(token=token, token_type='activation')
    except Token.DoesNotExist:
        return HttpResponse('Wrong token')
    if token_obj.creation_date + timedelta(days=token_obj.lifetime) > timezone.now():
        user = token_obj.user
        user.is_active = True
        user.save()
    token_obj.delete()
    return redirect('/')


def forgot_password(request):
    if request.method == 'POST':
        username = request.POST['username']
        try:
            user = User.objects.get(Q(username=username) | Q(email=username))
        except User.DoesNotExist:
            user = None
        token = Token.objects.create(token_type='forgot_password', user=user)
        text = f'Hey, you requested password change! Go to this link: 127.0.0.1:8000/forgot_password/{token.token} to activate your account'
        send_mail('vizitcard', '', None, [user.email], html_message=text)
        token.save()
    return render(request, 'forgot_password.html')


def new_password(request, token):
    try:
        token_obj = Token.objects.get(token=token, token_type='forgot_password')
    except Token.DoesNotExist:
        return HttpResponse('Неправильный токен')
    if token_obj.creation_date + timedelta(days=token_obj.lifetime) < timezone.now():
        token_obj.delete()
        return HttpResponse('Время жизни токена закончилось')
    if request.method == 'GET':
        return render(request, 'new_password.html')
    elif request.method == 'POST':
        password = request.POST['password']
        confirm = request.POST['confirm']
        user = token_obj.user
        if password != confirm:
            return HttpResponse('Пароли не совпадают')
        error = validate_password(password)
        if error:
            return HttpResponse(error)
        user.set_password(password)
        user.save()
        token_obj.delete()
        return redirect('/')


@api_view(['POST'])
def login_view(request):
    username = request.POST['username']
    password = request.POST['password']
    user = authenticate(request, username=username, password=password)
    if user is not None:
        if user.is_active:
            login(request, user)
        else:
            return Response(
                'Пользователь не активирован, пожалуйста, проверить почту и перейдите по ссылке из нашего письма',
                status=400)
    else:
        return Response('Неправильное имя пользователя или пароль', status=400)
    return Response(b'', status=200)


@login_required()
@api_view(['POST'])
def change_profile(request):
    first_name = request.POST['first_name']
    last_name = request.POST['last_name']
    biography = request.POST['biography']
    location = request.POST['location']
    password = request.POST['password']
    new = request.POST['new_password']
    try:
        avatar = request.FILES['avatar']
    except MultiValueDictKeyError:
        avatar = None

    error = ''
    user = request.user
    if first_name:
        user.first_name = first_name
    if last_name:
        user.last_name = last_name
    if biography:
        user.biography = biography
    if location:
        user.location = location
    if avatar:
        fs = FileSystemStorage(location='static/img/avatars')
        fs.save(avatar.name, avatar)
        user.avatar = 'img/avatars/' + avatar.name
    if user.check_password(password) and new:
        error = validate_password(new)
        print(error)
        if error:
            return Response(error, status=400)
        user.set_password(new)
    elif password and not user.check_password(password):
        error = 'Неправильный пароль'
    user.save()
    print(error)
    return Response(b'' if not error else error, status=200)


@login_required()
def logout_view(request):
    logout(request)
    return redirect('/')


@login_required()
def profile(request, **kwargs):
    try:
        profile_owner = User.objects.get(username=kwargs['username'])
    except:
        profile_owner = request.user
    return render(request, 'profile.html', {'user': request.user, 'profile_owner': profile_owner, 'cards': Card.objects.filter(creator=request.user) if not request.user.is_anonymous else []})


@user_passes_test(lambda u: u.is_superuser)
def admin(request):
    return render(request, 'admin.html', context={'requests': Organization.objects.filter(activated=False)})


def add_user_to_organization(user_id, organization_id):
    user = User.objects.get(id=user_id)
    org = Organization.objects.get(id=organization_id)
    if user.worker is None:
        worker = Worker(user=user)
        worker.save()
        user.worker = worker
    user.worker.org = org
    user.worker.save()
    user.save()


def delete_user_from_organization(user_id, organization_id):
    user = User.objects.get(id=user_id)
    org = Organization.objects.get(id=organization_id)
    if org == user.worker.org:
        user.worker.org = None
    user.worker.save()
    user.save()


@login_required()
def organizations(request):
    worker = User.objects.get(username=request.user.username).worker
    context = {'worker': worker}
    if worker and worker.org:
        context['workers'] = [User.objects.get(worker=i) for i in Worker.objects.filter(org=worker.org)]
        if worker.org:
            context['org'] = worker.org
    try:
        if worker.org.creator == request.user:
            context['code'] = OrganizationToken.objects.get(org=worker.org)
    except:
        pass
    return render(request, 'organizations.html', context=context)


@login_required()
@api_view(['POST'])
def enter_organization(request):
    code = request.POST.get('code', None)
    if code is None:
        return Response('Код не введен', status=400)
    try:
        code_obj = OrganizationToken.objects.get(Q(token_type='org') & Q(token=code))
    except OrganizationToken.DoesNotExist:
        return Response('Неправильный код доступа', status=400)
    add_user_to_organization(request.user.id, code_obj.org.id)
    return Response(b'', status=200)


@user_passes_test(lambda u: u.is_superuser, login_url='/')
@api_view(['POST'])
def activate_organization(request):
    org_id = request.POST.get('id', None)
    if not org_id:
        return Response('Не передан id', status=400)
    try:
        org = Organization.objects.get(pk=org_id)
    except Organization.DoesNotExist:
        return Response('Не найдена организация с таким id', status=400)
    _type = request.POST.get('type', None)
    if _type is None:
        return Response('Не указано действие', status=400)
    if _type == 'accept':
        org.activated = True
        org.save()
    else:
        org.delete()
    return Response(status=200)


@api_view(['POST'])
@login_required()
def request_create_organization(request):
    name = request.POST.get('name', None)
    description = request.POST.get('description', None)
    if not name:
        return Response('Не указано название', status=400)
    new_org = Organization(name=name, description=description, creator=request.user)
    new_org.save()

    tokens = OrganizationToken.objects.all()
    new_token = randint(100000, 999999)
    while new_token in tokens:
        new_token = randint(100000, 999999)
    new_org_token = OrganizationToken(org=new_org, token_type='org', lifetime=1e9, token=new_token)
    new_org_token.save()

    add_user_to_organization(request.user.id, new_org.id)

    user = User.objects.get(username=request.user)
    user.worker.position = 'Глава'
    user.worker.save()
    user.save()

    return Response(status=200)


@api_view(['POST'])
@login_required()
def delete_organization(request):
    print(request.POST)
    pk = request.POST.get('id', None)
    if not pk:
        return Response('id не указан', status=400)
    try:
        org = Organization.objects.get(id=pk)
    except Organization.DoesNotExist:
        return Response('Неправильный id', status=400)
    if org.creator == request.user:
        print(org)
        org.delete()
        return Response(status=200)
    return Response('Вы не являетесь создателем организации', status=200)


@api_view(['GET'])
def show_organization(request, id):
    try:
        org = Organization.objects.get(id=id)
    except Organization.DoesNotExist:
        org = None
    if org is None:
        return Response('Не существует организации с таким id', status=400)
    workers = [User.objects.get(worker=i) for i in Worker.objects.filter(org=org)]
    return render(request, 'organization.html', {'org': org, 'workers': workers})


@login_required()
@api_view(['POST'])
def delete_user_from_organization_view(request):
    id = request.POST.get('id', None)
    if id is None:
        return Response('ID пользователя не указан', status=400)
    user = User.objects.get(username=request.user)
    if user.worker.org.creator == request.user:
        u = User.objects.get(worker=Worker.objects.get(id=id))
        delete_user_from_organization(u.id, user.worker.org.id)
    return Response(b'', status=200)


@api_view(['POST'])
@login_required()
def leave_organization(request):
    user = User.objects.get(username=request.user)
    if user and user.worker:
        if user.worker.org.creator == user:
            user.worker.org.delete()
        user.worker.org = None
        user.worker.save()
        user.save()
    return Response(b'', status=200)


@login_required()
@api_view(['POST'])
def new_code(request):
    id = request.POST.get('id', None)
    if id is None:
        return Response('ID не указан', status=400)
    org = Organization.objects.get(id=id)
    OrganizationToken.objects.get(org=org).delete()
    tokens = OrganizationToken.objects.all()
    new_token = randint(100000, 999999)
    while new_token in tokens:
        new_token = randint(100000, 999999)
    OrganizationToken(org=org, token=new_token, token_type='org', lifetime=1e9).save()
    org.save()
    return Response({'code': new_token}, status=200)


def card(request, url):
    try:
        card_obj = Card.objects.get(url=url)
    except Card.DoesNotExist:
        return HttpResponse('Визитка не найдена')
    files = CardFile.objects.filter(card=card_obj)
    return render(request, 'card.html', {'user': request.user, 'card': card_obj, 'files': files})


@login_required()
@api_view(['POST'])
def create_card(request):
    name = request.POST.get('card_name', None)
    url = request.POST.get('url', None)
    if name is None or not name:
        return Response('Имя карточки не указано', status=400)
    if url is None or not (3 <= len(url) <= 30):
        return Response('Ссылка не указана или ее длина не лежит в отрезке от 3 до 30', status=400)
    if Card.objects.filter(url=url).count():
        return Response('Ссылка уже занята', status=400)

    description = request.POST.get('card_description')
    serialized_array = request.POST.get('serializedCard', '[]')
    image = request.FILES['card']

    new = Card(creator=request.user, name=name, description=description, url=url, serialized_array=serialized_array, image=File(image))
    new.save()
    for name, file in request.FILES.items():
        if name == 'card':
            continue
        file.name = name
        CardFile(card=new, file=File(file), name=name).save()
    return Response(status=200)


@login_required()
def new_card(request):
    return render(request, 'new_card.html')


@api_view(['GET'])
def download(request, path):
    file_path = './static/img/cards/'
    file = open(file_path + path, 'r')
    return Response(file, status=200)


@api_view(['POST'])
def send_activation_email(request):
    usr = request.POST.get('username')
    try:
        user = User.objects.get(Q(username=usr) | Q(email=usr))
    except User.DoesNotExist:
        return Response('Такого рользователя не существует', status=400)
    if user.is_active:
        return Response('Пользователь уже активирован', status=400)
    token = Token.objects.create(user=user, token_type="activation")
    text = f'Hey, this is vizitcard bot! Go to this <a href="http://127.0.0.1:8000/activate/{token.token}"> link </a> to activate your account'
    send_mail('vizitcard', '', None, [user.email], html_message=text)
    token.save()

    return Response(b'', status=200)


@login_required()
@api_view(['POST'])
def new_position(request):
    id = request.POST.get('id', 'None')
    pos = request.POST.get('pos', '')
    if id is None:
        return Response('ID не указан', status=400)
    try:
        change = User.objects.get(id=id)
    except User.DoesNotExist:
        change = None
    if change is None:
        return Response('Неверный ID', status=400)

    user = User.objects.get(username=request.user)
    if user == change.worker.org.creator:
        change.worker.position = pos
        change.worker.save()
        change.save()
    return Response(b'', status=200)
