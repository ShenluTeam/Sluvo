from services.gen_runtime_service import _provider_callback_path


def test_runninghub_callback_paths_use_registered_routes():
    assert _provider_callback_path("runninghub-image") == "runninghub/image"
    assert _provider_callback_path("runninghub-video") == "runninghub/video"


def test_unknown_callback_provider_keeps_provider_key():
    assert _provider_callback_path("custom-provider") == "custom-provider"
