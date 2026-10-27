"""The Linux upgrade guides must stop the web application server before they
replace what it is running.

This is a test about documentation because, on Linux, the documentation is the
procedure: there is no upgrade script to get wrong. ``linux_upgrade_from_4_0.rst``
used to tell the reader to stop nginx and django-q2 and then run ``uv sync`` and
``collectstatic``. That left gunicorn - which supervisor runs as its own program,
so stopping nginx does not stop it - serving with its Python already imported
while the dependencies and templates changed underneath it.

A reviewer cannot be relied on to notice an omission in a list of shell
commands, so the invariant is pinned here instead.

Only command lines are read: indented lines inside a code block that start with
the command itself. Prose that happens to mention ``uv sync`` or "stop gunicorn",
and the numbered overview at the top of each page, are ignored, so ordinary
edits to the wording do not affect the result.
"""

import pathlib
import re
import unittest

DOCS = pathlib.Path(__file__).resolve().parents[3] / 'docs' / 'install'

# Programs that serve requests, as opposed to the task cluster. Each upgrade
# page is for a particular starting point, so which one it stops differs: a
# 4.0 install runs gunicorn under supervisor, a 3.x install ran under apache.
WEB_SERVERS = ('gunicorn', 'apache2', 'apache')

# What must not happen before the web server is stopped. `uv sync` replaces
# installed packages; collectstatic replaces what the templates reference.
DESTRUCTIVE = {
    'uv sync': re.compile(r'^uv sync\b'),
    'collectstatic': re.compile(r'^(uv run )?python manage\.py collectstatic\b'),
}


def _command_lines(text):
    """(line number, command) for each indented line, i.e. code block content."""
    return [(number, line.strip()) for number, line in enumerate(text.splitlines()) if line[:1] in (' ', '\t')]


def _linux_upgrade_pages():
    return sorted(p for p in DOCS.glob('*upgrade*.rst') if 'linux' in p.name and not p.name.startswith('_'))


class TestLinuxUpgradePagesStopTheWebServer(unittest.TestCase):
    def test_there_are_pages_to_check(self):
        """Guard against the glob quietly matching nothing."""
        assert _linux_upgrade_pages(), 'no Linux upgrade pages found under %s' % DOCS

    def test_each_page_stops_a_web_server_before_changing_what_it_serves(self):
        for page in _linux_upgrade_pages():
            with self.subTest(page=page.name):
                commands = _command_lines(page.read_text(encoding='utf-8'))

                # Both orders occur in these pages: `supervisorctl stop
                # gunicorn` names the program after the verb, `service apache2
                # stop` before it. Match the command, not the word order.
                stops = [
                    number
                    for number, command in commands
                    if command.startswith('sudo ')
                    and re.search(r'\bstop\b', command)
                    and any(server in command.split() for server in WEB_SERVERS)
                ]
                assert stops, (
                    '%s never stops a web application server (%s). Replacing '
                    'dependencies or static files under live workers leaves old '
                    'code serving new templates.' % (page.name, ', '.join(WEB_SERVERS))
                )

                first_stop = min(stops)
                for name, pattern in DESTRUCTIVE.items():
                    for number, command in commands:
                        if pattern.match(command):
                            assert number > first_stop, '%s runs `%s` (line %d) before it stops the web server' % (
                                page.name,
                                name,
                                number + 1,
                            )

    def test_whatever_is_started_again_was_stopped_first(self):
        """An upgrade that ends by starting a program it never stopped is suspect.

        The 3.x page is the honest exception and is excluded: gunicorn does not
        exist on a 3.x install, so that page legitimately starts a program it
        could not have stopped.
        """
        programs = re.compile(r'supervisorctl\s+(stop|start)\s+([a-z0-9\- ]+)')

        for page in _linux_upgrade_pages():
            if 'from_3' in page.name:
                continue
            with self.subTest(page=page.name):
                stopped, started = set(), set()
                for _, command in _command_lines(page.read_text(encoding='utf-8')):
                    for action, names in programs.findall(command):
                        (stopped if action == 'stop' else started).update(names.split())
                assert started <= stopped, '%s starts %s without stopping it' % (
                    page.name,
                    ', '.join(sorted(started - stopped)),
                )
