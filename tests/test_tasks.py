import mock
import unittest2 as unittest

from fabric import api as fab

import fabricio

from fabricio import docker
from fabricio.tasks import Tasks, DockerTasks, PullDockerTasks, BuildDockerTasks


class TestContainer(docker.Container):

    image = docker.Image('test')


class TasksTestCase(unittest.TestCase):

    def test_tasks(self):
        class TestTasks(Tasks):

            @fab.task(default=True, aliases=['foo', 'bar'])
            def default(self):
                pass

            @fab.task(name='name', alias='alias')
            def task(self):
                pass

        roles = ['role_1', 'role_2']
        hosts = ['host_1', 'host_2']
        tasks = TestTasks(roles=roles, hosts=hosts)
        self.assertTrue(tasks.default.is_default)
        self.assertListEqual(['foo', 'bar'], tasks.default.aliases)
        self.assertEqual('name', tasks.task.name)
        self.assertListEqual(['alias'], tasks.task.aliases)
        for task in tasks:
            self.assertListEqual(roles, task.roles)
            self.assertListEqual(hosts, task.hosts)


class DockerTasksTestCase(unittest.TestCase):

    def test_update(self):
        cases = dict(
            default=dict(
                tasks_init_kwargs=dict(container=TestContainer('name')),
                tasks_update_kwargs=dict(),
                expected_command='docker pull localhost:5000/test:latest',
                expected_tunnel_params=dict(
                    remote_port=5000,
                    local_port=5000,
                    local_host='localhost',
                ),
                expected_container_update_params=dict(
                    force=False,
                    tag=None,
                    registry='localhost:5000',
                ),
            ),
            forced=dict(
                tasks_init_kwargs=dict(container=TestContainer('name')),
                tasks_update_kwargs=dict(force='yes'),
                expected_command='docker pull localhost:5000/test:latest',
                expected_tunnel_params=dict(
                    remote_port=5000,
                    local_port=5000,
                    local_host='localhost',
                ),
                expected_container_update_params=dict(
                    force=True,
                    tag=None,
                    registry='localhost:5000',
                ),
            ),
            custom_tag=dict(
                tasks_init_kwargs=dict(container=TestContainer('name')),
                tasks_update_kwargs=dict(tag='tag'),
                expected_command='docker pull localhost:5000/test:tag',
                expected_tunnel_params=dict(
                    remote_port=5000,
                    local_port=5000,
                    local_host='localhost',
                ),
                expected_container_update_params=dict(
                    force=False,
                    tag='tag',
                    registry='localhost:5000',
                ),
            ),
            custom_local_registry=dict(
                tasks_init_kwargs=dict(
                    container=TestContainer('name'),
                    local_registry='custom_host:1234',
                ),
                tasks_update_kwargs=dict(),
                expected_command='docker pull localhost:5000/test:latest',
                expected_tunnel_params=dict(
                    remote_port=5000,
                    local_port=1234,
                    local_host='custom_host',
                ),
                expected_container_update_params=dict(
                    force=False,
                    tag=None,
                    registry='localhost:5000',
                ),
            ),
        )
        for case, data in cases.items():
            with self.subTest(case=case):
                tasks = DockerTasks(**data['tasks_init_kwargs'])
                with mock.patch.object(
                    fab,
                    'remote_tunnel',
                    return_value=mock.MagicMock(),
                ) as remote_tunnel:
                    with mock.patch.object(fabricio, 'run') as run:
                        with mock.patch.object(
                            docker.Container,
                            'update',
                        ) as container_update:
                            tasks.update(**data['tasks_update_kwargs'])
                            container_update.assert_called_once_with(**data['expected_container_update_params'])
                        run.assert_called_once_with(data['expected_command'])
                    remote_tunnel.assert_called_once_with(**data['expected_tunnel_params'])

    def test_push(self):
        cases = dict(
            default=dict(
                tasks_init_kwargs=dict(
                    container=TestContainer('name'),
                ),
                tasks_push_kwargs=dict(),
                expected_commands=[
                    mock.call('docker tag test:latest localhost:5000/test:latest'),
                    mock.call('docker push localhost:5000/test:latest', quiet=False),
                ],
            ),
            custom_tag=dict(
                tasks_init_kwargs=dict(
                    container=TestContainer('name'),
                ),
                tasks_push_kwargs=dict(tag='tag'),
                expected_commands=[
                    mock.call('docker tag test:latest localhost:5000/test:tag'),
                    mock.call('docker push localhost:5000/test:tag', quiet=False),
                ],
            ),
            custom_local_registry=dict(
                tasks_init_kwargs=dict(
                    container=TestContainer('name'),
                    local_registry='custom_host:1234',
                ),
                tasks_push_kwargs=dict(),
                expected_commands=[
                    mock.call('docker tag test:latest custom_host:1234/test:latest'),
                    mock.call('docker push custom_host:1234/test:latest', quiet=False),
                ],
            ),
        )
        for case, data in cases.items():
            with self.subTest(case=case):
                tasks = DockerTasks(**data['tasks_init_kwargs'])
                with mock.patch.object(fabricio, 'local') as local:
                    tasks.push(**data['tasks_push_kwargs'])
                    local.assert_has_calls(data['expected_commands'])
                    self.assertEqual(
                        len(data['expected_commands']),
                        local.call_count,
                    )

    def test_deploy(self):
        with mock.patch.multiple(
            DockerTasks,
            push=mock.DEFAULT,
            update=mock.DEFAULT,
        ) as patched:
            tasks = DockerTasks(container='container')
            tasks.deploy(force='force', tag='tag')
            patched['push'].assert_called_once_with(tag='tag')
            patched['update'].assert_called_once_with(force='force', tag='tag')


class PullDockerTasksTestCase(unittest.TestCase):

    def test_pull(self):
        cases = dict(
            default=dict(
                tasks_pull_kwargs=dict(),
                expected_command='docker pull test:latest',
            ),
            custom_tag=dict(
                tasks_pull_kwargs=dict(tag='tag'),
                expected_command='docker pull test:tag',
            ),
        )
        for case, data in cases.items():
            with self.subTest(case=case):
                tasks = PullDockerTasks(container=TestContainer('container'))
                with mock.patch.object(fabricio, 'local') as local:
                    tasks.pull(**data['tasks_pull_kwargs'])
                    local.assert_called_once_with(
                        data['expected_command'],
                        quiet=False,
                    )

    def test_deploy(self):
        with mock.patch.object(PullDockerTasks, 'pull') as pull:
            with mock.patch.object(DockerTasks, 'deploy') as deploy:
                tasks = PullDockerTasks(container='container')
                tasks.deploy(force='force', tag='tag')
                pull.assert_called_once_with(tag='tag')
                deploy.assert_called_once_with(mock.ANY, force='force', tag='tag')


class BuildDockerTasksTestCase(unittest.TestCase):

    def test_build(self):
        cases = dict(
            default=dict(
                tasks_init_kwargs=dict(
                    container=TestContainer('name'),
                ),
                tasks_build_kwargs=dict(),
                expected_command='docker build --tag test:latest .',
            ),
            custom_build_path=dict(
                tasks_init_kwargs=dict(
                    container=TestContainer('name'),
                    build_path='foo',
                ),
                tasks_build_kwargs=dict(),
                expected_command='docker build --tag test:latest foo',
            ),
            custom_tag=dict(
                tasks_init_kwargs=dict(
                    container=TestContainer('name'),
                ),
                tasks_build_kwargs=dict(tag='tag'),
                expected_command='docker build --tag test:tag .',
            ),
        )
        for case, data in cases.items():
            with self.subTest(case=case):
                tasks = BuildDockerTasks(**data['tasks_init_kwargs'])
                with mock.patch.object(fabricio, 'local') as local:
                    tasks.build(**data['tasks_build_kwargs'])
                    local.assert_called_once_with(
                        data['expected_command'],
                        quiet=False,
                    )

    def test_deploy(self):
        with mock.patch.object(BuildDockerTasks, 'build') as build:
            with mock.patch.object(DockerTasks, 'deploy') as deploy:
                tasks = BuildDockerTasks(container='container')
                tasks.deploy(force='force', tag='tag')
                build.assert_called_once_with(tag='tag')
                deploy.assert_called_once_with(mock.ANY, force='force', tag='tag')
