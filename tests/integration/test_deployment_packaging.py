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
