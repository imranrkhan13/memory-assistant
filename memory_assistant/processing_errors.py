"""Content-free failure categories safe for durable job status."""
import urllib.error


class ProcessingError(Exception):
    def __init__(self, code, message, transient=False):
        super().__init__(message)
        self.code = code
        self.transient = transient


def classify_error(error):
    if isinstance(error, ProcessingError):
        return error.code, str(error), error.transient
    # Only controlled messages are stored; never store arbitrary exception text.
    cause = error.__cause__
    if isinstance(cause, urllib.error.HTTPError):
        status = cause.code
        return ("RATE_LIMIT" if status == 429 else "PROVIDER_HTTP", "Provider HTTP failure; check configuration or quota.", status == 429 or status >= 500)
    if isinstance(error, (TimeoutError, ConnectionError)) or isinstance(cause, (urllib.error.URLError, TimeoutError)):
        return "TIMEOUT", "Provider connection failed or timed out.", True
    from .gemini import GeminiError
    if isinstance(error, GeminiError):
        if str(error) in ("GEMINI_API_KEY is not configured.", "Invalid Gemini model name."):
            return "CONFIGURATION", "Configure the Gemini key and model, then reprocess.", False
        return "BAD_SCHEMA", "Provider returned invalid or unusable data; review provider configuration.", False
    if isinstance(error, (ValueError, KeyError, TypeError)):
        return "INVALID_EXTRACTION", "Invalid configuration or extraction data; review and reprocess.", False
    return "PROCESSING_ERROR", "Processing interrupted; retry scheduled.", True
