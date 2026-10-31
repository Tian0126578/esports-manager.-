# SPDX-License-Identifier: GPL-3.0-or-later
# License-Filename: LICENSES/GPL-3.0-or-later
import run_public


def test_public_launcher_explains_missing_cloudflared(monkeypatch, capsys):
    monkeypatch.setattr(run_public.shutil, "which", lambda _: None)

    exit_code = run_public.main()

    output = capsys.readouterr()
    assert exit_code == 1
    assert "cloudflared is required" in output.err
    assert "winget install --id Cloudflare.cloudflared" in output.err


def test_public_launcher_refuses_to_replace_an_existing_server(
    monkeypatch, capsys
):
    monkeypatch.setattr(run_public.shutil, "which", lambda _: "cloudflared")
    monkeypatch.setattr(run_public, "_port_is_available", lambda: False)

    exit_code = run_public.main()

    output = capsys.readouterr()
    assert exit_code == 1
    assert "Port 8000 is already in use" in output.err
