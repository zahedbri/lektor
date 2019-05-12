import textwrap
import os

import pytest

from lektor.cli import cli


build_events = [
    "before_build",
    "before_build_all",
    "after_build",
    "after_build_all",
    "before_prune",
    "after_prune",
    "markdown_meta_init",
    "markdown_meta_postprocess",
    "process_template_context",
    "setup_env",
]

all_events = build_events + [
    # Only during creation of markdown threadlocal object. I.e. only emitted on build
    # on the first render of the *entire* test suite, or else a lot of lib load hacking.
    "markdown_config",
    "markdown_lexer_config",
    # Only during `lektor server` command, never on build or other commands.
    "server_spawn",
    "server_stop",
]


@pytest.fixture(scope="function")
def scratch_project_with_plugin(scratch_project_data, request):
    """Create a scratch project and add a plugin that has the named event listener.

    Return project and current event.
    """
    base = scratch_project_data

    # Minimum viable setup.py
    current_test_index = (request.param_index,) * 4
    setup_text = textwrap.dedent(
        u"""
        from setuptools import setup

        setup(
            name='lektor-event-test{}',
            entry_points={{
                'lektor.plugins': [
                    'event-test{} = lektor_event_test{}:EventTestPlugin{}',
                ]
            }}
        )
    """
    ).format(*current_test_index)
    base.join(
        "packages", "event-test{}".format(request.param_index), "setup.py"
    ).write_text(setup_text, "utf8", ensure=True)

    # Minimum plugin code
    plugin_text = textwrap.dedent(
        u"""
        from lektor.pluginsystem import Plugin
        import os

        class EventTestPlugin{}(Plugin):
            name = 'Event Test'
            description = u'Non-empty string'

            def on_{}(self, **extra):
                print("event on_{}", extra['extra_flags'])
                return extra
    """
    ).format(request.param_index, request.param, request.param)
    base.join(
        "packages",
        "event-test{}".format(request.param_index),
        "lektor_event_test{}.py".format(request.param_index),
    ).write_text(plugin_text, "utf8", ensure=True)

    template_text = textwrap.dedent(
        u"""
        <h1>{{ "**Title**"|markdown }}</h1>
        {{ this.body }}
    """
    )
    base.join("templates", "page.html").write_text(template_text, "utf8", ensure=True)

    from lektor.project import Project

    yield (Project.from_path(str(base)), request.param)


@pytest.mark.parametrize("scratch_project_with_plugin", build_events, indirect=True)
def test_plugin_build_events_via_cli(scratch_project_with_plugin, isolated_cli_runner):
    """Test whether a plugin with a given event can successfully use an extra flag.
    """
    proj, event = scratch_project_with_plugin
    os.chdir(proj.tree)

    result = isolated_cli_runner.invoke(cli, ["build", "-f", "EXTRA"])
    assert result.exit_code == 0

    # Test that the event was triggered and the current extra flag was passed.
    output_lines = result.output.split("\n")

    # XXX - take a closer look at result.output
    # The setuptools working_set that keeps track of plugin installations is initialized
    # at the first import of pkg_resources, and then plugins are added to the
    # working_set as they are loaded into Lektor. Since pytest runs a single process,
    # these previous plugins are never removed. So while this does test what it says it
    # does, it also hooks previously generated plugins. Avoiding this with a succint
    # teardown is currently not possible AFAICT, since setuptools provides no clear way
    # of removing entry_points. I choose this comment over what would be a convoluted and
    # very hacky teardown function. The extra computation time is negligible.
    # See https://github.com/pypa/setuptools/issues/1759

    hits = [r for r in output_lines if r.startswith("event on_{}".format(event))]

    for hit in hits:
        assert "{'EXTRA': 'EXTRA'}" in hit

    assert len(hits) != 0

    result = isolated_cli_runner.invoke(cli, ["clean", "--yes"])


@pytest.mark.parametrize("scratch_project_with_plugin", all_events, indirect=True)
def test_env_extra_flag_passthrough(scratch_project_with_plugin):
    """Test whether setting extra_flags passes through to each plugin event.
    """
    from lektor.environment import Environment

    proj, event = scratch_project_with_plugin
    os.chdir(proj.tree)

    extra = {"extra": "extra"}
    env = Environment(proj, extra_flags=extra)
    plugin_return = env.plugin_controller.emit(event)
    for plugin in plugin_return:
        assert plugin_return[plugin]["extra_flags"] == extra
