from pathlib import Path


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

    assert "python3-venv" in installer
    assert "nginx" in installer
    assert "/etc/buddys/buddys.env" in installer
    assert "systemctl enable buddys" in installer

    assert "ExecStart=" in service
    assert "EnvironmentFile=/etc/buddys/buddys.env" in service
    assert "127.0.0.1:8787" in service
    assert "/bin/bash -lc" in service
    assert "BUDDYSDEFAULTOPENAIAPIKEY" in service
    assert "BUDDYSINVITECODE" in service
    assert "BUDDYSDEFAULTMODEL" in service

    assert "listen 80;" in nginx_conf
    assert "proxy_pass http://127.0.0.1:8787;" in nginx_conf
    assert "Upgrade $http_upgrade" in nginx_conf
