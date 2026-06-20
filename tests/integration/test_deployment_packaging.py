from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_readme_documents_hosted_validation_deployment_contract() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "PORT" in readme
    assert "BUDDYS_DEFAULT_OPENAI_API_KEY" in readme
    assert "invite-only" in readme
    assert "/console" in readme


def test_render_yaml_packages_single_python_web_service_for_console() -> None:
    render_yaml = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "services:" in render_yaml
    assert "type: web" in render_yaml
    assert "env: python" in render_yaml
    assert "uvicorn" in render_yaml
    assert "$PORT" in render_yaml
    assert "BUDDYS_DEFAULT_MODEL" in render_yaml
    assert "BUDDYS_DEFAULT_OPENAI_API_KEY" in render_yaml


def test_readme_documents_tencent_lighthouse_deployment_contract() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Tencent Lighthouse" in readme
    assert "deploy/tencent/install_lighthouse.sh" in readme
    assert "BUDDYS_INVITE_CODE" in readme
    assert "BUDDYS_DEFAULT_OPENAI_API_KEY" in readme


def test_tencent_deployment_packaging_includes_service_nginx_and_installer() -> None:
    deploy_root = REPO_ROOT / "deploy" / "tencent"
    installer = (deploy_root / "install_lighthouse.sh").read_text(encoding="utf-8")
    service = (deploy_root / "buddys.service").read_text(encoding="utf-8")
    nginx_conf = (deploy_root / "nginx-buddys.conf").read_text(encoding="utf-8")
    env_wrapper = (deploy_root / "run_with_env_compat.sh").read_text(encoding="utf-8")
    public_ip_helper = (deploy_root / "resolve_public_ipv4.sh").read_text(encoding="utf-8")

    assert "python3-venv" in installer
    assert "nginx" in installer
    assert "/etc/buddys/buddys.env" in installer
    assert "systemctl enable buddys" in installer
    assert "run_with_env_compat.sh" in installer
    assert "resolve_public_ipv4.sh" in installer
    assert 'SERVER_NAME="$(bash "${APP_ROOT}/deploy/tencent/resolve_public_ipv4.sh")"' in installer
    assert "hostname -I" not in installer
    assert "server_name ${SERVER_NAME};" in installer
    assert installer.index('if [[ ! -d "${APP_ROOT}/src" ]]') < installer.index('SERVER_NAME="$(bash "${APP_ROOT}/deploy/tencent/resolve_public_ipv4.sh")"')

    assert "ExecStart=" in service
    assert "run_with_env_compat.sh /etc/buddys/buddys.env" in service
    assert "127.0.0.1:8787" in service
    assert "PYTHONPATH=/opt/buddys/src" in service
    assert "buddys_api.main:create_app" in service
    assert "--factory" in service

    assert "listen 80;" in nginx_conf
    assert "proxy_pass http://127.0.0.1:8787;" in nginx_conf
    assert "Upgrade $http_upgrade" in nginx_conf

    assert "BUDDYSDEFAULTOPENAIAPIKEY" in env_wrapper
    assert "BUDDYS_DEFAULT_OPENAI_API_KEY" in env_wrapper
    assert "BUDDYSINVITECODE" in env_wrapper
    assert "OPENAIAPIKEY" in env_wrapper

    assert "metadata.tencentyun.com/latest/meta-data/public-ipv4" in public_ip_helper
    assert "metadata.tencentyun.com/meta-data/public-ipv4" in public_ip_helper
    assert "hostname -I" in public_ip_helper


def test_tencent_public_ip_helper_prefers_metadata_public_ipv4_over_private_hostname(tmp_path) -> None:
    deploy_root = REPO_ROOT / "deploy" / "tencent"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = {"PATH": f"{bin_dir}:{Path('/usr/bin')}:{Path('/bin')}"}
    (bin_dir / "curl").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$*\" == *\"latest/meta-data/public-ipv4\"* ]]; then\n"
        "  printf '111.231.3.24\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    (bin_dir / "hostname").write_text(
        "#!/usr/bin/env bash\n"
        "printf '10.0.0.9 172.16.0.5\\n'\n",
        encoding="utf-8",
    )
    (bin_dir / "ip").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    for tool_name in ("curl", "hostname", "ip"):
        (bin_dir / tool_name).chmod(0o755)

    result = subprocess.run(
        ["bash", str(deploy_root / "resolve_public_ipv4.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "111.231.3.24"


def test_tencent_public_ip_helper_strips_cidr_from_ip_fallback_output(tmp_path) -> None:
    deploy_root = REPO_ROOT / "deploy" / "tencent"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = {"PATH": f"{bin_dir}:{Path('/usr/bin')}:{Path('/bin')}"}
    (bin_dir / "curl").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    (bin_dir / "hostname").write_text(
        "#!/usr/bin/env bash\n"
        "printf '10.0.0.9 172.16.0.5\\n'\n",
        encoding="utf-8",
    )
    (bin_dir / "ip").write_text(
        "#!/usr/bin/env bash\n"
        "printf '2: eth0    inet 43.159.52.1/24 brd 43.159.52.255 scope global eth0\\n'\n",
        encoding="utf-8",
    )
    for tool_name in ("curl", "hostname", "ip"):
        (bin_dir / tool_name).chmod(0o755)

    result = subprocess.run(
        ["bash", str(deploy_root / "resolve_public_ipv4.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "43.159.52.1"


def test_tencent_env_wrapper_restores_canonical_env_names_from_orcaterm_file(tmp_path) -> None:
    deploy_root = REPO_ROOT / "deploy" / "tencent"
    env_file = tmp_path / "buddys.env"
    env_file.write_text(
        "\n".join(
            [
                "BUDDYSDEFAULTOPENAIAPIKEY=default-key",
                "BUDDYSINVITECODE=invite-code",
                "BUDDYSDEFAULTMODEL=MiniMax-M3",
                "OPENAIAPIKEY=user-key",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            str(deploy_root / "run_with_env_compat.sh"),
            str(env_file),
            sys.executable,
            "-c",
            (
                "import os, json; print(json.dumps({"
                "'default': os.getenv('BUDDYS_DEFAULT_OPENAI_API_KEY'), "
                "'invite': os.getenv('BUDDYS_INVITE_CODE'), "
                "'model': os.getenv('BUDDYS_DEFAULT_MODEL'), "
                "'openai': os.getenv('OPENAI_API_KEY')"
                "}))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        '{"default": "default-key", "invite": "invite-code", "model": "MiniMax-M3", "openai": "user-key"}'
    )
