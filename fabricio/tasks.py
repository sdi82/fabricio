import functools
import types
import weakref

from fabric import api as fab, colors
from fabric.contrib import console
from fabric.main import is_task_object

import fabricio


def infrastructure(confirm=True, color=colors.yellow):
    def _decorator(task):
        @functools.wraps(task)
        def _task(*args, **kwargs):
            if confirm and console.confirm(
                'Are you sure you want to select {infrastructure} '
                'infrastructure to run task(s) on?'.format(
                    infrastructure=color(task.__name__),
                ),
                default=False,
            ):
                return task(*args, **kwargs)
            fab.abort('Aborted')
        return _task
    if callable(confirm):
        func, confirm = confirm, infrastructure.__defaults__[0]
        return _decorator(func)
    return _decorator


class Tasks(object):

    @property
    def __name__(self):
        return self

    __class__ = types.ModuleType

    def __new__(cls, **kwargs):
        self = object.__new__(cls)
        weak_self = weakref.proxy(self)
        for attr in dir(cls):
            attr_value = getattr(cls, attr)
            if is_task_object(attr_value):
                task_decorator = fab.task(
                    default=attr_value.is_default,
                    name=attr_value.name,
                    aliases=attr_value.aliases,
                )
                task = task_decorator(
                    functools.wraps(attr_value.wrapped)(
                        functools.partial(attr_value.wrapped, weak_self),
                    ),
                )
                setattr(self, attr, task)
        return self

    def __init__(self, roles=(), hosts=()):
        for task in self:
            task.roles = roles
            task.hosts = hosts

    def __iter__(self):
        for name, attr_value in vars(self).items():
            if is_task_object(attr_value):
                yield attr_value


class DockerTasks(Tasks):

    registry_port = 5000

    def __init__(
        self,
        container,
        local_registry='localhost:5000',
        roles=(),
        hosts=(),
    ):
        super(DockerTasks, self).__init__(roles=roles, hosts=hosts)
        self.container = container
        registry_host, _, registry_port = local_registry.partition(':')
        self.local_registry_host = registry_host or 'localhost'
        self.local_registry_port = int(registry_port) or 5000

    @property
    def registry(self):
        return 'localhost:{port}'.format(port=self.registry_port)

    @property
    def local_registry(self):
        return '{registry}:{port}'.format(
            registry=self.local_registry_host,
            port=self.local_registry_port,
        )

    @property
    def image(self):
        return self.container.__class__.image

    @fab.task
    def revert(self):
        self.container.revert()

    @fab.task
    def update(self, force='no', tag=None):
        with fab.remote_tunnel(
            remote_port=self.registry_port,
            local_port=self.local_registry_port,
            local_host=self.local_registry_host,
        ):
            fabricio.run('docker pull {image}'.format(
                image=self.image[self.registry:tag]),
            )
        self.container.update(
            force=force == 'yes',
            tag=tag,
            registry=self.registry,
        )

    @fab.task
    def push(self, tag=None):
        new_tag = self.image[self.local_registry:tag]
        fabricio.local(
            'docker tag {image} {tag}'.format(
                image=self.image,
                tag=new_tag,
            ),
            use_cache=True,
        )
        fabricio.local(
            'docker push {tag}'.format(tag=new_tag),
            quiet=False,
            use_cache=True,
        )

    @fab.task(default=True)
    def deploy(self, force='no', tag=None):
        self.push(tag=tag)
        self.update(force=force, tag=tag)


class PullDockerTasks(DockerTasks):

    @fab.task
    def pull(self, tag=None):
        fabricio.local(
            'docker pull {image}'.format(image=self.image[tag]),
            quiet=False,
            use_cache=True,
        )

    @fab.task(default=True)
    def deploy(self, force='no', tag=None):
        self.pull(tag=tag)
        DockerTasks.deploy(self, force=force, tag=tag)


class BuildDockerTasks(DockerTasks):

    def __init__(
        self,
        container,
        build_path='.',
        local_registry='localhost:5000',
        roles=(),
        hosts=(),
    ):
        super(BuildDockerTasks, self).__init__(
            container=container,
            local_registry=local_registry,
            roles=roles,
            hosts=hosts,
        )
        self.build_path = build_path

    @fab.task
    def build(self, tag=None):
        fabricio.local(
            'docker build --tag {tag} {build_path}'.format(
                tag=self.image[tag],
                build_path=self.build_path,
            ),
            quiet=False,
            use_cache=True,
        )

    @fab.task(default=True)
    def deploy(self, force='no', tag=None):
        self.build(tag=tag)
        DockerTasks.deploy(self, force=force, tag=tag)
