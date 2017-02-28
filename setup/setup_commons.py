from codecs import open
from os import listdir, path
from sys import platform

import subprocess

import sys
from setuptools import find_packages
from setuptools.command.test import test
from golem.core.common import get_golem_path

from gui.view.generateui import generate_ui_files


class PyTest(test):
    """
    py.test integration with setuptools,
    https://pytest.org/latest/goodpractises.html\
    #integration-with-setuptools-test-commands
    """

    user_options = [('pytest-args=', 'a', "Arguments to pass to py.test")]

    def initialize_options(self):
        test.initialize_options(self)
        self.pytest_args = []

    def finalize_options(self):
        test.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        # import here, cause outside the eggs aren't loaded
        import pytest
        import sys
        errno = pytest.main(self.pytest_args)
        sys.exit(errno)


def get_long_description(my_path):
    """
    Read readme file
    :return: Content of the README file
    """
    with open(path.join(my_path, 'README.md'), encoding='utf-8') as f:
        read = f.read()
    return read


def find_required_packages():
    if platform.startswith('darwin'):
        return find_packages(exclude=['examples', 'tests'])
    return find_packages(include=['golem*', 'apps*', 'gui*'])


def parse_requirements(my_path):
    """
    Parse requirements.txt file
    :return: [requirements, dependencies]
    """
    import re
    requirements = []
    dependency_links = []
    for line in open(path.join(my_path, 'requirements.txt')):
        line = line.strip()
        m = re.match('.+#egg=(?P<package>.+)$', line)
        if m:
            requirements.append(m.group('package'))
            dependency_links.append(line)
        else:
            requirements.append(line)
    return requirements, dependency_links


def print_errors(ui_err, docker_err, task_err):
    if ui_err:
        print(ui_err)
    if docker_err:
        print(docker_err)
    if task_err:
        print(task_err)


def generate_ui():
    try:
        generate_ui_files()
    except EnvironmentError as err:
        return \
            """
            ***************************************************************
            Generating UI elements was not possible.
            Golem will work only in command line mode.
            Generate_ui_files function returned {}
            ***************************************************************
            """.format(err)


def try_pulling_docker_images():
    err_msg = __try_docker()
    if err_msg:
        return err_msg
    images_dir = 'apps'

    with open(path.join(images_dir, 'images.ini')) as f:
        for line in f:
            try:
                image, docker_file, tag = line.split()
                if subprocess.check_output(["docker", "images", "-q", image + ":" + tag]):
                    print("\n Image {} exists - skipping".format(image))
                    continue
                cmd = "docker pull {}:{}".format(image, tag)
                print("\nRunning '{}' ...\n".format(cmd))
                subprocess.check_call(cmd.split(" "))
            except ValueError:
                print("Skipping line {}".format(line))
            except subprocess.CalledProcessError as err:
                print("Docker pull failed: {}".format(err))
                sys.exit(1)


def get_golem_version(increase):
    from ConfigParser import ConfigParser
    from os.path import join
    config = ConfigParser()
    config_path = join(get_golem_path(), '.version.ini')
    config.read(config_path)
    version = config.get('version', 'version')
    update_ini()
    return version


def move_wheel():
    from shutil import move
    path_ = path.join(get_golem_path(), 'dist')
    files_ = [f for f in listdir(path_) if path.isfile(path.join(path_, f))]
    files_.sort()
    source = path.join(path_, files_[-1])
    dst = path.join(path_, __file_name())
    move(source, dst)


def get_version():
    from git import Repo
    return Repo(get_golem_path()).tags[-1].name


def update_ini():
    version_file = path.join(get_golem_path(), '.version.ini')
    version = "[version]\nversion = {}".format(get_version())
    with open(version_file, 'wb') as f_:
        f_.write(version)


def __file_name():
    """
    Get wheel name
    :return: Name for wheel
    """
    from git import Repo
    repo = Repo(get_golem_path())
    tag = repo.tags[-1]             # get latest tag
    tag_id = tag.commit.hexsha      # get commit id from tag
    commit_id = repo.head.commit.hexsha     # get last commit id
    # @todo what with platform?
    if commit_id != tag_id:         # devel package
        return "golem-{}-0x{}{}-py27-none-any.whl".format(tag.name, commit_id[:4], commit_id[-4:])
    else:                           # release package
        return "golem-{}-py27-none-any.whl".format(tag.name)


def __try_docker():
    try:
        subprocess.check_call(["docker", "info"])
    except Exception as err:
        return \
            """
            ***************************************************************
            Docker not available, not building images.
            Golem will not be able to compute anything.
            Command 'docker info' returned {}
            ***************************************************************
            """.format(err)
