"""Headless Mornye service: Android UI belongs to the native WebView host."""
def create_window(*args, **kwargs):
    raise RuntimeError("Use Mindinguflac's Android WebView host")
def start(*args, **kwargs):
    raise RuntimeError("Use Mindinguflac's Android WebView host")
