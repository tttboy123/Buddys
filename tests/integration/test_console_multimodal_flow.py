from fastapi.testclient import TestClient

from buddys_api.main import create_app


def extract_function_body(script: str, function_name: str) -> str:
    import re

    match = re.search(rf"function {function_name}\([^)]*\) \{{(?P<body>.*?)\n\}}", script, re.S)
    assert match is not None
    return match.group("body")


def test_console_assets_support_multimodal_capture_contract() -> None:
    client = TestClient(create_app())

    html = client.get("/console").text
    script = client.get("/static/app.js").text
    submit_voice_transcript_body = extract_function_body(script, "submitVoiceTranscript")

    assert 'id="photoFileInput"' in html
    assert 'id="photoPreviewImage"' in html
    assert 'id="clearPhotoSelectionButton"' in html
    assert 'id="submitPhotoCaptureButton"' in html
    assert 'id="startVoiceCaptureButton"' in html
    assert 'id="retryVoiceCaptureButton"' in html
    assert 'id="voiceTranscriptInput"' in html
    assert 'id="submitVoiceTranscriptButton"' in html
    assert "startVoiceCapture" in script
    assert "handlePhotoSelected" in script
    assert "clearPhotoSelection" in script
    assert "submitPhotoCapture" in script
    assert "submitVoiceTranscript" in script
    assert "/state-memory/captures/conversation" in submit_voice_transcript_body
    assert "/state-memory/captures/voice" not in submit_voice_transcript_body


def test_console_assets_use_browser_speech_recognition_with_honest_unsupported_copy() -> None:
    client = TestClient(create_app())

    script = client.get("/static/app.js").text

    assert "window.SpeechRecognition" in script
    assert "window.webkitSpeechRecognition" in script
    assert "Voice capture is not available in this browser." in script
    assert "Voice capture coming soon" not in script
