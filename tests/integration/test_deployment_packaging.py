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

    assert "python3-venv" in installer
    assert "nginx" in installer
    assert "/etc/buddys/buddys.env" in installer
    assert "systemctl enable buddys" in installer
    assert "run_with_env_compat.sh" in installer
    assert "hostname -I" in installer
    assert "server_name ${SERVER_IP};" in installer

    assert "ExecStart=" in service
    assert "run_with_env_compat.sh /etc/buddys/buddys.env" in service
    assert "127.0.0.1:8787" in service

    assert "listen 80;" in nginx_conf
    assert "proxy_pass http://127.0.0.1:8787;" in nginx_conf
    assert "Upgrade $http_upgrade" in nginx_conf

    assert "BUDDYSDEFAULTOPENAIAPIKEY" in env_wrapper
    assert "BUDDYS_DEFAULT_OPENAI_API_KEY" in env_wrapper
    assert "BUDDYSINVITECODE" in env_wrapper
    assert "OPENAIAPIKEY" in env_wrapper


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
