import logging

from celery import shared_task, Task
from django.contrib.auth.models import User
from .hooks import ServicesHook
from celery_once import QueueOnce as BaseTask, AlreadyQueued
from celery_once.helpers import now_unix, queue_once_key
from django.core.cache import cache
from inspect import getcallargs


logger = logging.getLogger(__name__)


class QueueOnce(BaseTask):
    once = BaseTask.once
    once['graceful'] = True

    def get_key(self, args=None, kwargs=None):
        """
        Generate the key from the name of the task (e.g. 'tasks.example') and
        args/kwargs.
        """
        restrict_to = self.once.get('keys', None)
        args = args or {}
        kwargs = kwargs or {}
        call_args = getcallargs(self.run, *args, **kwargs)

        if isinstance(call_args.get('self'), Task):
            del call_args['self']
        if isinstance(call_args.get('task_self'), Task):
            del call_args['task_self']
        return queue_once_key(self.name, call_args, restrict_to)


class DjangoBackend:
    def __init__(self, settings):
        pass

    @staticmethod
    def raise_or_lock(key, timeout):
        now = now_unix()
        result = cache.get(key)
        if result:
            remaining = int(result) - now
            if remaining > 0:
                raise AlreadyQueued(remaining)
        else:
            cache.set(key, now + timeout, timeout)

    @staticmethod
    def clear_lock(key):
        return cache.delete(key)


@shared_task(bind=True)
def validate_services(self, pk):
    user = User.objects.get(pk=pk)
    logger.debug('Ensuring user {} has permissions for active services'.format(user))
    # Iterate through services hooks and have them check the validity of the user
    for svc in ServicesHook.get_services():
        try:
            svc.validate_user(user)
        except:
            logger.exception('Exception running validate_user for services module %s on user %s' % (svc, user))


def disable_user(user):
    logger.debug('Disabling all services for user %s' % user)
    for svc in ServicesHook.get_services():
        if svc.service_active_for_user(user):
            svc.delete_user(user)

