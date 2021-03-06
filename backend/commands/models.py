import functools
import subprocess
import uuid

from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

SUCCESS = 'success'
FAIL = 'fail'


def generate_token():
    return uuid.uuid4().hex


def permission_key_by_object(obj):
    return f'{obj.__class__.__name__}.{obj}'


def create_object_permission(obj):
    return Permission.objects.create(
        codename=permission_key_by_object(obj),
        name=str(obj),
        content_type=ContentType.objects.get_for_model(obj.__class__),
    )


def check_object_permission(user, obj):
    return user.has_perm('commands.' + permission_key_by_object(obj))


def log_calls(func):

    @functools.wraps(func)
    def wrapped(command, source, token=None):
        result = func(command)

        if SUCCESS in result:
            result_status = Call.SUCCESS_RESULT
            output = result[SUCCESS]
        else:
            result_status = Call.FAIL_RESULT
            output = result[FAIL]

        Call(
            command=command,
            result=result_status,
            output=output,
            source=source,
            token=token,
        ).save()

        return result

    return wrapped


class Group(models.Model):

    title = models.SlugField(unique=True)
    description = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        create_object_permission(self)

    def __str__(self):
        return self.title


class Command(models.Model):

    group = models.ForeignKey(Group, related_name='commands')
    title = models.SlugField()
    description = models.TextField(blank=True)
    body = models.TextField()
    is_disabled = models.BooleanField(default=False)

    @log_calls
    def run(self):
        try:
            output = subprocess.check_output(self.body, shell=True).decode()
            return {SUCCESS: output}
        except subprocess.CalledProcessError as exc:
            return {FAIL: str(exc)}

    def __str__(self):
        return f'{self.group.title} - {self.title}'

    class Meta:
        unique_together = ('group', 'title')


class Call(models.Model):

    SUCCESS_RESULT = 1
    FAIL_RESULT = 2

    RESULTS = (
        (SUCCESS_RESULT, SUCCESS),
        (FAIL_RESULT, FAIL),
    )

    ADMIN = 1
    API = 2

    SOURCES = (
        (ADMIN, 'Admin'),
        (API, 'Api'),
    )

    command = models.ForeignKey(Command, related_name='calls')
    source = models.IntegerField(choices=SOURCES)
    result = models.IntegerField(choices=RESULTS)
    output = models.TextField(blank=True)
    time = models.DateTimeField(auto_now=True, editable=False)
    token = models.ForeignKey(
        'AccessToken',
        related_name='calls',
        null=True,
        default=None,
    )

    def __str__(self):
        return f'{self.command} - {self.time}'


class AccessToken(models.Model):

    user = models.ForeignKey(settings.AUTH_USER_MODEL)
    token = models.CharField(
        max_length=50,
        default=generate_token,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now=True, editable=False)
    expired_at = models.DateTimeField(blank=True, null=True)
    is_disabled = models.BooleanField(default=False)

    def is_active(self):
        if (self.is_disabled
                or (self.expired_at and self.expired_at < timezone.now())):
            return False
        return True

    def has_permission(self, group):
        return check_object_permission(self.user, group)

    def __str__(self):
        return self.token
