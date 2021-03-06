# inshack-scoreboard
A Django scoreboard for CTF

## Setup the DB on a separate server

```bash
$ mkdir scorebaord_dev_data
$ docker run -it --rm -p 3306:3306 \
  --name scoreboard_db \
  -e MYSQL_DATABASE=inshack \
  -e MYSQL_USER=inshack \
  -e MYSQL_PASSWORD=password \
  -e MYSQL_RANDOM_ROOT_PASSWORD=yes \
  -v $(pwd)/scorebaord_dev_data/:/var/lib/mysql \
  mysql:5.7
```

Modify *inshack_scoreboard/settings.py* accordingly. Then launch the migrations on the mysql host:

```bash
$ python3 manage.py makemigrations
$ python3 manage.py migrate
```

## Populate DB

```bash
$ echo "from django.contrib.auth.models import User; \
from challenges.models import CTFSettings; \
User.objects.create_superuser('adminctf', 'me@gmail.com', 'CHANGE_ME'); \
CTFSettings.objects.create()
" | python3 manage.py shell
```

Once the superuser is created, go to the django admin interface and create a `teamprofile` for the superuser

## Run in development

```bash
$ pip install -r deploy/requirements.txt
$ DEV=1 python manage.py runserver
```

## Run in production

First step: build (and push)

```bash
$ docker build -t registry.insecurity-insa.fr/insecurity/scoreboard -f deploy/Dockerfile .
$ # Optional: push to your own docker repository if needed
$ docker push registry.insecurity-insa.fr/insecurity/scoreboard
```

Second step, run:

```bash
$ docker run -d --restart unless-stopped \
         --name scoreboard \
         -p 8081:8081 \
         -e db_user=inshack \
         -e db_password=password \
         -e db_host=1.2.3.4 \
         -e SECRET_KEY=CHANGE_ME \
         -e ALLOWED_HOST=scoreboard.example.com \
         registry.insecurity-insa.fr/insecurity/scoreboard
```
