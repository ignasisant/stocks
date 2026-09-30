"""`stocks dashboard --reload` draws the frontend from its source, not the build.

The committed bundle changes only when `npm run build` runs, so a local server
that served it drew a stale page after every frontend edit until somebody
remembered to rebuild. With `--reload` the dashboard runs Vite beside uvicorn
and tells the server where; these pin that hand-off, and the fallback for a
checkout with no Node in it.
"""

from stocks import cli


def test_without_node_the_committed_bundle_is_served(tmp_path, capsys):
    env: dict[str, str] = {}
    assert cli._start_vite(tmp_path, env) is None
    assert "STOCKS_VITE" not in env
    assert "npm run build" in capsys.readouterr().out


def test_the_server_is_told_where_vite_listens(tmp_path, monkeypatch):
    binary = tmp_path / "node_modules" / ".bin" / "vite"
    binary.parent.mkdir(parents=True)
    binary.touch()
    started = []
    monkeypatch.setattr(cli.subprocess, "Popen",
                        lambda cmd, **kw: started.append((cmd, kw)) or "vite")
    env: dict[str, str] = {}
    assert cli._start_vite(tmp_path, env) == "vite"
    (cmd, kw), = started
    host, port = env["STOCKS_VITE"].removeprefix("http://").split(":")
    assert host == "localhost"
    # Exactly that port or not at all: Vite hopping to the next free one would
    # leave the document pointing at whatever else holds this one.
    assert cmd[cmd.index("--port") + 1] == port and "--strictPort" in cmd
    # Vite reads the same variable for the origin of the URLs it writes.
    assert kw["env"] is env and kw["cwd"] == tmp_path
